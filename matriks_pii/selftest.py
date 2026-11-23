"""Kurulum doğrulama aracı: LiteLLM config.yaml içindeki matriks-pii guardrail'lerini değersiz olarak sınar.

    python -m matriks_pii.selftest --config config.yaml              # tam kontrol
    python -m matriks_pii.selftest --config config.yaml --quick      # < 2 sn (k8s startupProbe)
    python -m matriks_pii.selftest --config config.yaml --json       # makine okunur çıktı
    python -m matriks_pii.selftest --config config.yaml --probe "metin"            # tespitler (değersiz)
    python -m matriks_pii.selftest --config config.yaml --probe "metin" --show-values
    python -m matriks_pii.selftest --config config.yaml --corpus holdout.jsonl     # P/R/F2 tablosu

Çıkış kodu: herhangi bir FAIL varsa 1. Hiçbir çıktı (--show-values hariç) kişisel veri içermez.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GUARDRAIL_CLASS = "TurkishPIIGuardrail"
_LITELLM_KEYS = ("guardrail", "mode", "default_on", "stream_scope", "guardrail_id", "logging_only_scope")

# (metin, beklenen varlıklar) — sentetik değerler; beklenen küme config'de IGNORE olmayanlarla kesiştirilir
SELFTEST_PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TC kimlik no 17291716060", ("TCKN",)),
    ("Vergi no 4540536920", ("VKN",)),
    ("IBAN TR330006100519786457841326", ("IBAN",)),
    ("Kart 4111 1111 1111 1111", ("KART",)),
    ("Tel 0532 234 56 78", ("TELEFON",)),
    ("E-posta ayse@ornek.com", ("EPOSTA",)),
    ("34 ABC 123 plakalı araç", ("PLAKA",)),
    ("Sayın Ayşe Demir bugün aradı.", ("KISI",)),
    ("Adres: Atatürk Mah. Gül Sok. No:5 Kadıköy/İstanbul", ("ADRES",)),
    ("Müşterimiz Ayşe Demir diyabet hastası.", ("KISI", "OZEL_SAGLIK")),
    ("api_key=sk-abc123def456ghi789jkl012mno345pqr", ("GIZLI_ANAHTAR",)),
    ("THYAO hissesi 300 TL'den 1.250 lot işlem gördü.", ()),
)
_QUICK_PROBES = (0, 7, 11)


@dataclass
class Check:
    level: str  # OK | WARN | FAIL
    name: str
    message: str = ""


@dataclass
class Report:
    guardrail: str
    checks: list[Check] = field(default_factory=list)

    def add(self, level: str, name: str, message: str = "") -> None:
        self.checks.append(Check(level, name, message))

    @property
    def failed(self) -> bool:
        return any(c.level == "FAIL" for c in self.checks)


def load_guardrails(path: str) -> list[tuple[str, dict[str, Any]]]:
    import yaml

    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = []
    for g in doc.get("guardrails") or []:
        lp = (g or {}).get("litellm_params") or {}
        if str(lp.get("guardrail", "")).endswith(GUARDRAIL_CLASS):
            out.append((str(g.get("guardrail_name") or "matriks-pii"), dict(lp)))
    return out


def _mode_hooks(mode: Any) -> set[str]:
    if isinstance(mode, str):
        return {mode}
    if isinstance(mode, list):
        return {str(m) for m in mode}
    return set()


def _expected(cfg: Any, ents: tuple[str, ...]) -> set[str]:
    return {e for e in ents if e in cfg.entities and cfg.action(e) != "IGNORE"}


async def _store_roundtrip(cfg: Any, name: str) -> str:
    from .session import MaskSession
    from .store import build_store

    store = build_store(cfg, namespace=name)
    if not await store.ping():
        raise RuntimeError("ping başarısız")
    s = MaskSession(cfg)
    s.map["<KISI_1>"] = "selftest"
    s.entities["<KISI_1>"] = "KISI"
    sid = f"{name}:selftest:{os.getpid()}:{time.time_ns()}"
    await store.put(sid, s)
    got = await store.pop(sid)
    if got is None or got.map.get("<KISI_1>") != "selftest":
        raise RuntimeError("yaz/oku/sil gidiş-dönüşü tutmadı")
    return cfg.session_store.backend


def check_guardrail(name: str, params: dict[str, Any], quick: bool = False) -> tuple[Report, Any]:
    from .config import TurkishPIIConfig
    from .engine import PIIEngine

    rep = Report(name)
    hooks = _mode_hooks(params.get("mode"))
    if {"pre_call", "post_call"} <= hooks:
        rep.add("OK", "mode", "pre_call + post_call")
    elif "pre_call" in hooks:
        rep.add("FAIL", "mode", "post_call eksik: yanıt geri çevrilmez (guardrail eklemeye çalışır ama UI/DB yönetimi ezebilir)")
    else:
        rep.add("FAIL", "mode", f"mode={sorted(hooks) or params.get('mode')!r}; [pre_call, post_call] olmalı")
    ss = params.get("stream_scope")
    if ss == "non_streaming" or (isinstance(ss, dict) and ss.get("post_call") == "non_streaming"):
        rep.add("WARN", "stream_scope", "post_call akışta çalışmaz → akış yanıtları geri çevrilmez")
    rep.add("OK" if params.get("default_on") else "WARN", "default_on",
            "her istekte" if params.get("default_on") else "yalnız istekte 'guardrails' ile açılır")
    if os.environ.get("MATRIKS_PII_DEBUG_TRACEBACK") == "1":
        rep.add("FAIL", "debug", "MATRIKS_PII_DEBUG_TRACEBACK=1 üretimde kapatılmalı")
    kwargs = {k: v for k, v in params.items() if k not in _LITELLM_KEYS}
    try:
        t0 = time.perf_counter()
        cfg, _rest = TurkishPIIConfig.from_kwargs(kwargs)
        engine = PIIEngine(cfg)
        rep.add("OK", "config", f"profil={cfg.profile} config_hash={cfg.version_hash} kurulum={1000 * (time.perf_counter() - t0):.0f} ms")
    except Exception as e:  # değersiz: ValueError iletileri değer taşımaz (config.py)
        rep.add("FAIL", "config", f"{type(e).__name__}: {e}")
        return rep, None
    if cfg.dry_run:
        rep.add("WARN", "dry_run", "gölge mod: hiçbir şey maskelenmiyor")
    if cfg.fail_mode != "closed" or cfg.revert_fail_mode != "closed":
        rep.add("WARN", "fail_mode", f"fail_mode={cfg.fail_mode} revert_fail_mode={cfg.revert_fail_mode}")
    try:
        backend = asyncio.run(_store_roundtrip(cfg, name))
        rep.add("OK", "session_store", f"{backend}: ping + {'şifreli ' if backend == 'redis' else ''}yaz/oku/sil")
    except Exception as e:
        rep.add("FAIL", "session_store", f"{type(e).__name__}")
    probes = [SELFTEST_PROBES[i] for i in _QUICK_PROBES] if quick else list(SELFTEST_PROBES)
    bad = 0
    for i, (text, ents) in enumerate(probes):
        exp = _expected(cfg, ents)
        got = {s.entity for s in engine.detected(text)}
        if got != exp:
            bad += 1
            rep.add("FAIL", f"probe[{i}]", f"beklenen={sorted(exp)} bulunan={sorted(got)}")
    if not bad:
        rep.add("OK", "probes", f"{len(probes)} kanonik sondaj")
    if quick:
        return rep, engine
    if cfg.name_detection.ner_backend != "none":
        try:
            t0 = time.perf_counter()
            engine.analyze("Ali Veli bugün geldi.")
            rep.add("OK", "ner", f"yükleme+ilk çağrı {1000 * (time.perf_counter() - t0):.0f} ms")
        except Exception as e:
            rep.add("FAIL", "ner", type(e).__name__)
    if cfg.audit_log.enabled and cfg.audit_log.path:
        d = os.path.dirname(os.path.abspath(cfg.audit_log.path))
        ok = os.path.isdir(d) and os.access(d, os.W_OK)
        rep.add("OK" if ok else "WARN", "audit_log", "dizin yazılabilir" if ok else "dizin yok veya yazılamıyor")
    para = "Sayın Ahmet Yılmaz, 17291716060 TC kimlik numaralı müşterimizin TR330006100519786457841326 IBAN'ına THYAO alımı. "
    text = (para * 30)[:2048]
    engine.cache.clear()
    ts = []
    for _ in range(20):
        engine.cache.clear()
        t0 = time.perf_counter()
        engine.analyze(text)
        ts.append(1000 * (time.perf_counter() - t0))
    p50 = statistics.median(ts)
    rep.add("OK" if p50 < 10 else "WARN", "latency_2kb", f"p50={p50:.2f} ms (executor eşiği {cfg.executor_threshold_chars} kr)")
    return rep, engine


class CorpusFormatError(ValueError):
    pass


def corpus_report(engine: Any, path: str) -> dict[str, dict[str, float]]:
    st: dict[str, Counter[str]] = {}
    for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            c = json.loads(line)
            if not isinstance(c, dict) or not isinstance(c.get("text"), str):
                raise ValueError
            exp_list = [(str(e["entity"]), str(e["value"])) for e in c.get("entities", [])]
        except (ValueError, KeyError, TypeError):  # değer içermeyen ileti
            raise CorpusFormatError(
                f"{path}:{no}: --corpus JSONL bekler (satır başına bir JSON): "
                '{"text": "...", "entities": [{"entity": "KISI", "value": "..."}]}'
            ) from None
        got = Counter((s.entity, s.text) for s in engine.detected(c["text"]))
        exp = Counter(exp_list)
        for ent, val in got | exp:
            tp = min(got[(ent, val)], exp[(ent, val)])
            s = st.setdefault(ent, Counter())
            s["tp"] += tp
            s["fp"] += got[(ent, val)] - tp
            s["fn"] += exp[(ent, val)] - tp
    out = {}
    for ent, s in sorted(st.items()):
        p = s["tp"] / (s["tp"] + s["fp"]) if s["tp"] + s["fp"] else 1.0
        r = s["tp"] / (s["tp"] + s["fn"]) if s["tp"] + s["fn"] else 1.0
        f2 = 5 * p * r / (4 * p + r) if p + r else 0.0
        out[ent] = {"p": round(p, 3), "r": round(r, 3), "f2": round(f2, 3), "tp": s["tp"], "fp": s["fp"], "fn": s["fn"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m matriks_pii.selftest", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--guardrail", help="yalnız bu guardrail_name")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--probe")
    ap.add_argument("--show-values", action="store_true")
    ap.add_argument("--corpus")
    a = ap.parse_args(argv)
    found = [(n, p) for n, p in load_guardrails(a.config) if not a.guardrail or n == a.guardrail]
    if not found:
        print(f"FAIL: {a.config} içinde {GUARDRAIL_CLASS} guardrail'i yok", file=sys.stderr)
        return 1
    results: list[dict[str, Any]] = []
    failed = False
    for name, params in found:
        rep, engine = check_guardrail(name, params, quick=a.quick)
        failed |= rep.failed
        res: dict[str, Any] = {"guardrail": name, "checks": [asdict(c) for c in rep.checks]}
        if engine is not None and a.probe:
            res["probe"] = [
                {"entity": s.entity, "start": s.start, "end": s.end, "score": s.score, "recognizer": s.recognizer,
                 **({"value": s.text} if a.show_values else {})}
                for s in engine.detected(a.probe)
            ]
        if engine is not None and a.corpus:
            try:
                res["corpus"] = corpus_report(engine, a.corpus)
            except (CorpusFormatError, OSError) as e:
                print(f"FAIL: {e}", file=sys.stderr)
                return 2
        results.append(res)
    if a.json:
        print(json.dumps({"ok": not failed, "guardrails": results}, ensure_ascii=False, indent=2))
    else:
        for res in results:
            print(f"== {res['guardrail']}")
            for c in res["checks"]:
                print(f"  [{c['level']:<4}] {c['name']}: {c['message']}")
            if "probe" in res:
                if a.show_values:
                    print("  UYARI: --show-values kişisel veri basar; yalnız yerel hata ayıklamada kullanın")
                for s in res["probe"]:
                    print("  probe:", " ".join(f"{k}={v}" for k, v in s.items()))
            if "corpus" in res:
                print(f"  {'varlık':<16}{'P':>7}{'R':>7}{'F2':>7}")
                for ent, m in res["corpus"].items():
                    print(f"  {ent:<16}{m['p']:>7}{m['r']:>7}{m['f2']:>7}")
        print("SONUÇ:", "FAIL" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
