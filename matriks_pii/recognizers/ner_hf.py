"""Opsiyonel Hugging Face NER adaptörü (`pip install matriks-mask[ner]`).

Model tembel yüklenir; yalnız `ner_label_map` ile eşlenen etiketler (varsayılan PER→KISI) üretilir.
LOC/ORG maskelenmez. Model çıktısı sonradan düzeltilir: alt sözcük parçaları ("Jer" + "om" + "e Powell") sözcük
sınırlarına genişletilip birleştirilir; sözlük modunun yanlış pozitif korumaları (cümle başında sık sözcük olan tek ad,
kurum/tarihî kişi adları, kısaltmalar) NER span'lerine de uygulanır.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import threading
from typing import Any

from .. import data, metrics
from ..text_utils import fold_key, is_sentence_start, trie_pattern
from .base import AnalysisContext, Recognizer, Span

_APOS = "'’ʼ`"


def _chunks(text: str, sentences: list[tuple[int, int]], max_chars: int) -> list[tuple[int, str]]:
    """Cümleleri biriktirerek ≤ max_chars parçalar; tek cümle uzunsa boşlukta, boşluk yoksa sert böler."""
    pieces: list[tuple[int, int]] = []
    for s, e in sentences or [(0, len(text))]:
        while e - s > max_chars:
            cut = text.rfind(" ", s + 1, s + max_chars)
            cut = cut if cut > s else s + max_chars
            pieces.append((s, cut))
            s = cut
        pieces.append((s, e))
    out: list[tuple[int, str]] = []
    cur_s, cur_e = None, None
    for s, e in pieces:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif e - cur_s <= max_chars:
            cur_e = e
        else:
            out.append((cur_s, text[cur_s:cur_e]))
            cur_s, cur_e = s, e
    if cur_s is not None:
        out.append((cur_s, text[cur_s:cur_e]))
    return out


class HFNerRecognizer(Recognizer):
    name = "ner_hf"
    entities = ("KISI",)

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg.name_detection
        self._pipe: Any = None
        self._lock = threading.Lock()
        # zaman aşımı için ayrı havuz (zaman aşımı çalışan çıkarımı iptal etmez, yalnız isteği serbest bırakır)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.cfg.ner_max_concurrency, thread_name_prefix="matriks-ner"
        )
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        self.names = data.first_names() | data.last_names()
        self.common = data.common_words()
        self.words = data.tr_words()
        orgs = data.org_names()
        self.org_re = re.compile(r"(?<![a-z0-9])(?:" + trie_pattern(orgs, space=" ") + r")(?![a-z0-9])") if orgs else None

    def _pipeline(self) -> Any:
        if self._pipe is None:
            with self._lock:
                if self._pipe is None:
                    try:
                        from transformers import pipeline  # type: ignore[import-not-found]
                    except ImportError as e:  # pragma: no cover
                        raise RuntimeError("ner_backend=hf için 'pip install matriks-mask[ner]' gerekli") from e
                    pipe = pipeline(
                        "token-classification",
                        model=self.cfg.ner_model,
                        aggregation_strategy="simple",
                        device=self.cfg.ner_device,
                    )
                    model = getattr(pipe, "model", None)
                    if model is not None and hasattr(model, "eval"):
                        model.eval()
                    self._pipe = pipe
        return self._pipe

    def preload(self) -> None:
        self._pipeline()

    def _run(self, pipe: Any, chunk: str) -> list[dict[str, Any]]:
        fut = self._executor.submit(pipe, chunk)
        return list(fut.result(timeout=self.cfg.ner_timeout_seconds))

    def _infer(self, text: str, ctx: AnalysisContext) -> list[dict[str, Any]]:
        """Metni cümle sınırında ≤ ner_max_chars parçalara böler; ofsetleri metne göre kaydırır."""
        out: list[dict[str, Any]] = []
        pipe = self._pipeline()  # eksik bağımlılık/model hatası olduğu gibi yükselir (kurulum hatası, çalışma hatası değil)
        for start, chunk in _chunks(text, ctx.sentences, self.cfg.ner_max_chars):
            if not chunk.strip():
                continue
            try:
                res = self._run(pipe, chunk)
            except (concurrent.futures.TimeoutError, Exception) as e:  # 3.10: futures.TimeoutError ≠ builtins
                metrics.inc_event(None, "ner_failed")
                if self.cfg.ner_fail_mode == "closed":
                    raise RuntimeError(f"matriks_pii: NER başarısız ({type(e).__name__})") from None
                logging.getLogger("matriks_pii").error("matriks_pii: NER başarısız (%s); sözlük sonuçlarıyla devam", type(e).__name__)
                return []
            for r in res:
                r = dict(r)
                r["start"] = int(r["start"]) + start
                r["end"] = int(r["end"]) + start
                out.append(r)
        return out

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        if not text.strip():
            return []
        res = self._infer(text, ctx)
        raw: list[tuple[int, int, str, float]] = []
        for r in res:
            label = str(r.get("entity_group") or r.get("entity") or "")
            ent = self.cfg.ner_label_map.get(label) or self.cfg.ner_label_map.get(label.split("-")[-1])
            if not ent:
                continue
            score = float(r.get("score", 0.0))
            if score < self.cfg.ner_min_score:
                continue
            s, e = int(r["start"]), int(r["end"])
            # alt sözcük parçasını sözcük sınırına genişlet ("Jer" → "Jerome")
            while s > 0 and text[s - 1].isalpha():
                s -= 1
            while e < len(text) and text[e].isalpha():
                e += 1
            while s < e and not text[s].isalnum():
                s += 1
            while e > s and not text[e - 1].isalnum():
                e -= 1
            if e > s:
                raw.append((s, e, ent, score))
        merged: list[list[Any]] = []
        for s, e, ent, score in sorted(raw):
            if merged and merged[-1][2] == ent and (s <= merged[-1][1] or text[merged[-1][1] : s].isspace()):
                merged[-1][1] = max(merged[-1][1], e)
                merged[-1][3] = max(merged[-1][3], score)
            else:
                merged.append([s, e, ent, score])
        org_zones = [(m.start(), m.end()) for m in self.org_re.finditer(ctx.casefolded)] if self.org_re else []
        out: list[Span] = []
        for s, e, ent, score in merged:
            for i in range(s, e):  # apostroflu eki span dışında bırak
                if text[i] in _APOS:
                    e = i
                    break
            if e <= s or not self._plausible(text, s, e, org_zones):
                continue
            out.append(Span(s, e, ent, text[s:e], min(0.95, score), self.name, " ".join(fold_key(text[s:e]).split())))
        return out

    def _plausible(self, text: str, s: int, e: int, org_zones: list[tuple[int, int]]) -> bool:
        if any(a <= s and e <= b for a, b in org_zones):
            return False  # kurum adı / tarihî kişi ("Atatürk", "Koç Holding")
        toks = text[s:e].split()
        if len(toks) == 1:
            tok = toks[0]
            key = fold_key(tok)
            if tok.isupper() and len(tok) <= 5 and key not in self.names:
                return False  # kısaltma ("JSON", "THYAO")
            if key not in self.names and key in self.words:
                return False  # ad sözlüğünde olmayan sık Türkçe sözcük
            if self.common.get(key) and is_sentence_start(text, s):
                return False  # "Kaya gibi…", "Mert bir duruşla…": sözlük modundaki cümle başı kuralı
        return True
