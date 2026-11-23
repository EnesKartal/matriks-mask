"""Yer tutucuları orijinal değerlere geri çevirme (tam metin ve akış)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING

from .text_utils import APOS_CHARS, ascii_fold, tr_lower
from .tr_morphology import repair_suffix

if TYPE_CHECKING:
    from .config import TurkishPIIConfig

# ek onarımı: adlar/yerler + rakamla biten değerler (son sayının okunuşuna göre: "17291716060'ı", "…26'dan")
_REPAIR_ENTITIES = frozenset({"KISI", "ADRES", "DOGUM_YERI", "TCKN", "TELEFON", "IBAN", "KART", "VKN", "HESAP_NO",
                              "MUSTERI_NO", "DOGUM_TARIHI"})
# "\<", "\[": markdown kaçışı ("\<KISI_1\>")
_GENERIC_OPEN = ("<<", "<", "&lt;", "[[", "[", "{{", "{", "\\u003c", "\\<", "\\[")
_GENERIC_CLOSE = (">>", ">", "&gt;", "]]", "]", "}}", "}", "\\u003e", "\\>", "\\]")
# numarasız yer tutucu: LLM mekanizmayı anlatırken "<TCKN_...>" yazar; etikette tek değer varsa o değerdir
_GENERIC_ID = r"\.{2,3}|…|x{1,3}|n|\*{1,3}|\?{1,3}|#"
_SUFFIX_AFTER = re.compile(rf"[{APOS_CHARS}](?P<s>[a-zçğıöşüâîûA-ZÇĞİÖŞÜÂÎÛ]{{1,10}})(?![_0-9A-Za-zçğıöşüÇĞİÖŞÜ])")
# apostrofsuz bitişik ek ("<KISI_1>lar"): yalnız suffix_repair_attached ile; ardından boşluk/noktalama/son gelmeli
_SUFFIX_ATTACHED = re.compile(
    r"(?P<s>lar|ler|nın|nin|nun|nün|ın|in|un|ün|ya|ye|yı|yi|yu|yü|da|de|ta|te|dan|den|tan|ten|yla|yle|la|le|a|e|ı|i|u|ü)"
    r"(?=$|[\s.,;:!?)\]\"'])"
)


def _alts(items: tuple[str, ...] | list[str]) -> str:
    uniq = sorted({ascii_fold(tr_lower(x)) for x in items if x}, key=len, reverse=True)
    return "|".join(re.escape(x) for x in uniq)


@lru_cache(maxsize=64)
def _scanner_for(
    fmt: str, labels: tuple[str, ...], aliases: tuple[tuple[str, str], ...] = ()
) -> tuple[re.Pattern[str], dict[str, str], tuple[str, ...], tuple[str, ...]]:
    from .config import _PLACEHOLDER_FMT_RE

    m = _PLACEHOLDER_FMT_RE.match(fmt)
    assert m
    o, c = m["open"], m["close"]
    opens = tuple({*_GENERIC_OPEN, o} - {""})
    closes = tuple({*_GENERIC_CLOSE, c} - {""})
    lab_map = {ascii_fold(tr_lower(lab)): lab for lab in labels}
    for alias, lab in aliases:  # LLM'in çevirdiği etiket ("<PERSON_1>") → gerçek etiket; yalnız parantezli biçimde
        lab_map.setdefault(ascii_fold(tr_lower(alias)), lab)
    lab_alt = "|".join(re.escape(x) for x in sorted(lab_map, key=len, reverse=True))
    rx = re.compile(
        rf"(?:(?P<open>{_alts(list(opens))})[ \t]*)?"
        # açılış varsa önceki karakter serbest ("\u003cKISI_1": "c" harfi); yoksa sözcük sınırı
        rf"(?(open)|(?<![a-z0-9]))(?P<label>{lab_alt})[ \t]*(?P<sep>\\?[_\-]?)[ \t]*"  # "\_": markdown kaçışı
        rf"(?:(?P<n>[0-9]{{1,6}}|[a-z2-7]{{6,12}})(?![a-z0-9])|(?P<g>{_GENERIC_ID}))"
        rf"(?:[ \t]*(?P<close>{_alts(list(closes))}))?"
    )
    fo = tuple(sorted({ascii_fold(tr_lower(x)) for x in opens}, key=len, reverse=True))  # uzun olan önce ("<<" > "<")
    fc = tuple(sorted({ascii_fold(tr_lower(x)) for x in closes}, key=len, reverse=True))
    return rx, lab_map, fo, fc


def normalize_id(n: str) -> str:
    """Sıra numarasında baştaki sıfırlar LLM bozulmasıdır: "01" → "1". hmac kimlikleri (base32) aynen kalır."""
    return str(int(n)) if n.isdigit() else n


def placeholder_scanner(cfg: TurkishPIIConfig) -> tuple[re.Pattern[str], dict[str, str]]:
    rx, lab_map, _, _ = _scanner_for(cfg.placeholder_format, tuple(sorted(set(cfg.labels.values()))))
    return rx, lab_map


@dataclass
class RevertStats:
    replaced: int = 0
    unresolved: int = 0
    repaired: int = 0
    stripped_truncated: int = 0


@dataclass
class Reverter:
    mapping: dict[str, str]
    entities: dict[str, str]
    cfg: TurkishPIIConfig
    reserved: set[str] = field(default_factory=set)
    wrapped: set[str] = field(default_factory=set)  # istekte parantez içindeki değerler (dış parantez korunur)
    stats: RevertStats = field(default_factory=RevertStats)

    def __post_init__(self) -> None:
        aliases = tuple(sorted((a, self.cfg.label(e)) for a, e in self.cfg.label_aliases.items() if e in self.cfg.labels))
        self.rx, self.lab_map, self.opens, self.closes = _scanner_for(
            self.cfg.placeholder_format, tuple(sorted(set(self.cfg.labels.values()))), aliases
        )
        self._alias_keys = frozenset(ascii_fold(tr_lower(a)) for a, _ in aliases) - {
            ascii_fold(tr_lower(lab)) for lab in self.cfg.labels.values()
        }
        self.labels_lower = tuple(sorted(self.lab_map, key=len, reverse=True))
        fo, _sep, fc = self.cfg.fmt_parts
        pairs = {"<<": ">>", "<": ">", "[[": "]]", "[": "]", "{{": "}}", "{": "}", "&lt;": "&gt;", "\\u003c": "\\u003e",
                 "\\<": "\\>", "\\[": "\\]"}
        if fo:
            pairs[ascii_fold(tr_lower(fo))] = ascii_fold(tr_lower(fc))
        self._pairs = pairs
        self._fo, self._fc = ascii_fold(tr_lower(fo)), ascii_fold(tr_lower(fc))
        self._open_first = {o[0] for o in self.opens}

    def _only_key(self, label: str) -> str | None:
        keys = [k for k, e in self.entities.items() if k in self.mapping and self.cfg.label(e) == label]
        return keys[0] if len(keys) == 1 else None

    # ------------------------------------------------------------------ tam metin
    def revert(self, text: str, final: bool = False, json_escape: bool = False, prev_char: str = "") -> str:
        """Yer tutucuları geri çevirir. `json_escape`: değer bir JSON string parçasının içine yazılıyor
        (akışta tool argümanı) → kaçışlı yaz. `final`: akış sonu; yarım kalan yer tutucu ham metinde kırpılır."""
        if final and self.cfg.truncated_placeholder == "strip" and text:
            cut = self.partial_start(text, require_label=True)
            if cut is not None:
                self.stats.stripped_truncated += 1
                text = text[:cut]
        if not text or (not self.mapping and self.cfg.unresolved_placeholder == "keep"):
            return text
        probe = ascii_fold(tr_lower(text))
        if len(probe) != len(text):  # güvenlik ağı (uzunluk korunmalı)
            return text
        out: list[str] = []
        pos = 0
        for m in self.rx.finditer(probe):
            if m.start() < pos:
                continue
            label = self.lab_map.get(m["label"])
            if label is None:
                continue
            bracketed = bool(m["open"] or m["close"])
            if not bracketed and m["label"] in self._alias_keys:
                continue  # çıplak "PERSON_1" metin olabilir; takma ad yalnız parantezli biçimde geçerli
            if m["g"] is not None:
                if not bracketed:
                    continue
                only = self._only_key(label)
                if only is None:  # etikette sıfır ya da birden çok değer: hangisi olduğu bilinemez
                    self.stats.unresolved += 1
                    continue
                key = only
            else:
                if not bracketed:
                    # çıplak form: yalnız '_' ayracı ve haritada varsa
                    if m["sep"] not in ("_", "\\_"):
                        continue
                    s0 = m.start("label")
                    before = text[s0 - 1] if s0 > 0 else prev_char  # akışta önceki parçanın son karakteri
                    if before and (before.isalnum() or before == "_"):
                        continue
                key = self.cfg.format_placeholder(label, normalize_id(m["n"]))
            start, end = m.start(), m.end()
            if not bracketed:
                start = m.start("label")
            value = self.mapping.get(key)
            if value is None:
                if key in self.reserved or not bracketed:
                    continue
                self.stats.unresolved += 1
                if self.cfg.unresolved_placeholder == "strip":
                    out.append(text[pos:start])
                    pos = end
                continue
            out.append(text[pos:start])
            rendered = json.dumps(value, ensure_ascii=False)[1:-1] if json_escape else value
            if key in self.wrapped and bracketed and self._fo and self._fc:
                # "<<EPOSTA_1>>" (istekte "<ayse@x.com>"): yer tutucunun parantezleri düşer, metnin kendi parantezi kalır
                o, c = m["open"] or "", m["close"] or ""
                if o == self._fo * 2 and c == self._fc * 2:
                    rendered = text[start : start + len(self._fo)] + rendered + text[end - len(self._fc) : end]
            out.append(rendered)
            pos = end
            self.stats.replaced += 1
            ent = self.entities.get(key, "")
            if self.cfg.suffix_repair and ent in _REPAIR_ENTITIES:
                sm = _SUFFIX_AFTER.match(text, pos)
                if sm is None and self.cfg.suffix_repair_attached:
                    sm = _SUFFIX_ATTACHED.match(text, pos)
                if sm:
                    sfx = sm["s"]
                    fixed = repair_suffix(value, sfx)
                    if fixed != sfx:
                        self.stats.repaired += 1
                    out.append(text[pos : sm.start("s")])
                    out.append(fixed)
                    pos = sm.end()
        out.append(text[pos:])
        return "".join(out)

    # ------------------------------------------------------------------ kısmi yer tutucu tespiti
    def is_partial(self, s: str, require_label: bool = False) -> bool:
        """`s` (küçük harf + ASCII katlanmış) tamamlanmamış bir yer tutucunun başlangıcı olabilir mi?"""
        r = s
        had_open = False
        expected_close = ""
        for o in self.opens:
            if r.startswith(o):
                r = r[len(o) :].lstrip(" \t")
                had_open = True
                expected_close = self._pairs.get(o, "")
                break
        else:
            if any(o.startswith(r) for o in self.opens) and r:
                return not require_label
        if not r:
            return had_open and not require_label
        if require_label and not had_open:
            return False
        for lab in self.labels_lower:
            if lab.startswith(r):
                return True
            if r.startswith(lab):
                rest = r[len(lab) :]
                if re.fullmatch(r"[ \t]*\\?[_\-]?[ \t]*(?:[0-9]*|[a-z2-7]{0,12}|\.{0,3}|…|x{0,3}|\*{0,3}|\?{0,3}|#)[ \t]*", rest):
                    return True
                mm = re.fullmatch(r"[ \t]*\\?[_\-]?[ \t]*(?:[0-9]+|[a-z2-7]{6,12}|" + _GENERIC_ID + r")[ \t]*(?P<c>.*)", rest)
                # açılışla eşleşen kapanışın yarım hâli ("<<KISI_1>" + ">" bekleniyor) → kısmi
                if mm and mm["c"] and expected_close.startswith(mm["c"]) and expected_close != mm["c"]:
                    return True
        return False

    def partial_start(self, text: str, require_label: bool = False, window: int = 48) -> int | None:
        probe = ascii_fold(tr_lower(text))
        lo = max(0, len(probe) - window)
        # tamamlanmış (kapanışlı) yer tutucunun İÇİNDEKİ konumlar yeni başlangıç sayılmaz: "__KISI_1__" sonundaki "__"
        # kapanıştır, yeni bir açılış değil
        done = [(m.start(), m.end()) for m in self.rx.finditer(probe, max(0, lo - window)) if m["close"]]
        for p in range(lo, len(probe)):
            if any(a < p < b for a, b in done):
                continue
            ch = probe[p]
            if ch in self._open_first or (ch.isalpha() and (p == 0 or not probe[p - 1].isalnum())):
                if self.is_partial(probe[p:], require_label=require_label):
                    return p
        return None


class StreamingReverter:
    """Akışta parçalanmış yer tutucuları tamponlayarak geri çevirir."""

    def __init__(self, reverter: Reverter, holdback_max_chars: int = 48, json_escape: bool = False) -> None:
        self.reverter = reverter
        self.holdback = holdback_max_chars
        self.json_escape = json_escape
        self.buf = ""
        self._prev = ""

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self.buf += delta
        cut = self._safe_cut()
        if cut <= 0:
            return ""
        seg = self.buf[:cut]
        out = self.reverter.revert(seg, json_escape=self.json_escape, prev_char=self._prev)
        self._prev = seg[-1:]
        self.buf = self.buf[cut:]
        return out

    def flush(self) -> str:
        if not self.buf:
            return ""
        out = self.reverter.revert(self.buf, final=True, json_escape=self.json_escape, prev_char=self._prev)
        self._prev = self.buf[-1:]
        self.buf = ""
        return out

    def drain_raw(self) -> str:
        """Hata yolunda: tamponu geri çevirmeden boşalt (sıra korunur)."""
        out, self.buf = self.buf, ""
        return out

    def _safe_cut(self) -> int:
        buf = self.buf
        n = len(buf)
        cut = n
        p = self.reverter.partial_start(buf, window=self.holdback)
        if p is not None:
            cut = p
        if self.reverter.cfg.suffix_repair:
            # tamamlanmış yer tutucu sonda: ek gelebilir → bekle
            probe = ascii_fold(tr_lower(buf))
            tail_from = max(0, n - self.holdback)
            last = None
            for m in self.reverter.rx.finditer(probe, tail_from):
                last = m
            if last is not None:
                after = buf[last.end() :]
                if re.fullmatch(rf"(?:[{APOS_CHARS}]?[a-zçğıöşüâîûA-ZÇĞİÖŞÜÂÎÛ]{{0,10}})?", after):
                    cut = min(cut, last.start())
        if n - cut > self.holdback:
            cut = n
        return cut
