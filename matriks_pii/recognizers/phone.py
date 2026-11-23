"""Türkiye telefon numaraları (mobil, sabit hat, 850, isteğe bağlı 444/800)."""

from __future__ import annotations

import re
from typing import Any

from ..text_utils import fre
from .base import AnalysisContext, Recognizer, Span, ctx_prefix_re

_PHONE_RE = re.compile(
    r"(?<![0-9A-Za-z+])(?P<pre>(?:(?:\+|00)?90[\s.\-]?)?\(?0?\)?[\s.\-]?)\(?"
    r"(?P<ac>5[0-6][0-9]|[2-4][0-9]{2}|8(?:00|50|11|12|22|88|98)|900)\)?[\s.\-]?"
    r"(?P<p1>[0-9]{3})[\s.\-]?(?P<p2>[0-9]{2})[\s.\-]?(?P<p3>[0-9]{2})(?![0-9])"
)
_444_RE = re.compile(r"(?<![0-9])444[\s.\-]?[0-9][\s.\-]?[0-9]{3}(?![0-9])")

LANDLINE = frozenset(
    "212 216 222 224 226 228 232 236 242 246 248 252 256 258 262 264 266 272 274 276 282 284 286 288 "
    "312 318 322 324 326 328 332 338 342 344 346 348 352 354 356 358 362 364 366 368 370 372 374 376 378 "
    "380 382 384 386 388 392 412 414 416 418 422 424 426 428 432 434 436 438 442 446 452 454 456 458 462 "
    "464 466 472 474 476 478 482 484 486 488 850 812".split()  # 812: BTK mobil erişim (konum bağımsız)
)
# BTK numaralandırma planında tahsisli GSM blokları
MOBILE = frozenset(
    [f"50{d}" for d in "1256789"] + [f"51{d}" for d in "0123456"] + [f"53{d}" for d in "0123456789"]
    + [f"54{d}" for d in "0123456789"] + [f"55{d}" for d in "0123456789"] + ["561"]
)
TOLL_FREE = frozenset({"800", "888", "898", "900", "811", "822"})
_PHONE_CTX = ctx_prefix_re(
    "tel", "telefon", "gsm", "cep", "mobil", "whatsapp", "faks", "fax", "irtibat", "iletişim", "ara", "arayın",
    "arayabilirsiniz", "numaram", "numarası:", "numaranız", "hat", "phone", "mobile",
    "numarasından", "numarasına", "numarasını", "numaramdan", "numarama", "numaranızdan",
)
# "sipariş numarasını 5321234567 ver": numara sözcüğü başka bir kayıt türüne aitse telefon bağlamı sayılmaz
_NOT_PHONE_NUMBER = fre(
    r"(?<![a-z])(?:sipariş|siparis|fiş|fis|takip|dosya|kargo|sözleşme|sozlesme|fatura|iade|kayıt|kayit|poliçe|police|"
    r"müşteri|musteri|referans|başvuru|basvuru|talep|işlem|islem)\s+(?:no|numara[a-zçğıöşü]*)"
)
# harf O ile yazılmış sıfır ("O532 123 45 67"): yalnız telefon bağlamı hemen önündeyse (uzunluk korunan kopya)
_LETTER_O = re.compile(r"(?<![A-Za-z])[Oo](?=\s?[0-9])")


class PhoneRecognizer(Recognizer):
    name = "phone"
    entities = ("TELEFON",)

    def __init__(self, mask_800: bool = False, mask_444: bool = False) -> None:
        self.mask_800 = mask_800
        self.mask_444 = mask_444

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = self._scan(text, text, ctx)
        if _LETTER_O.search(text):
            alt = _LETTER_O.sub("0", text)
            for sp in self._scan(alt, text, ctx):
                if "O" in sp.text.upper() and _PHONE_CTX.search(ctx.casefolded[max(0, sp.start - 15) : sp.start]):
                    out.append(sp)
        return out

    def _has_ctx(self, ctx: AnalysisContext, start: int, end: int) -> bool:
        if not ctx.has_context(start, end, _PHONE_CTX, window=30):
            return False
        return not _NOT_PHONE_NUMBER.search(ctx.casefolded[max(0, start - 30) : start])

    def _scan(self, text: str, orig: str, ctx: AnalysisContext) -> list[Span]:
        """`text` üzerinde eşleştir, span metnini `orig`'den al (aynı uzunluk)."""
        out: list[Span] = []
        pos, n = 0, len(text)
        while pos < n:
            m = _PHONE_RE.search(text, pos)
            if not m:
                break
            start = m.start()
            while start < m.end() and text[start] in " \t.-)":
                start += 1
            # "(0216 345 67 89)": kapanmayan açılış parantezi numaraya ait değildir
            if text[start] == "(" and ")" not in text[start : start + 6]:
                start += 1
            ok, score = self._check(m)
            if ok and ctx.in_exclusion(m.start(), m.end()):
                ok = False
            if ok:
                has_ctx = self._has_ctx(ctx, start, m.end())
                compact = re.fullmatch(r"[0-9]{10}", text[start : m.end()]) is not None
                if compact and not has_ctx:
                    # ayraçsız, öneksiz 10 hane: emir/sipariş numarası olabilir → bağlam şart
                    ok = False
                elif has_ctx:
                    score = min(0.95, score + 0.1)
            if not ok:
                pos = m.start() + 1
                continue
            norm = "+90" + m["ac"] + m["p1"] + m["p2"] + m["p3"]
            out.append(Span(start, m.end(), "TELEFON", orig[start : m.end()], score, self.name, norm))
            pos = m.end()
        if self.mask_444 and text is orig:
            for m in _444_RE.finditer(text):
                out.append(Span(m.start(), m.end(), "TELEFON", m.group(), 0.7, self.name, re.sub(r"\D", "", m.group())))
        return out

    def _check(self, m: re.Match[str]) -> tuple[bool, float]:
        ac, p1 = m["ac"], m["p1"]
        mobile = ac in MOBILE
        # sabit hatta abone numarası 0/1 ile başlamaz; mobilde yalnız 0 (KVKK: kaçırma maliyeti > yanlış alarm)
        if p1[0] in "01" and not mobile:
            return False, 0.0
        pre = re.sub(r"[\s.\-()]", "", m["pre"] or "")
        has_prefix = pre in {"+90", "0090", "90", "0", "900", "+900", "00900"}
        if ac in TOLL_FREE:
            return (True, 0.8) if self.mask_800 else (False, 0.0)
        if not mobile and ac not in LANDLINE:
            return False, 0.0
        if has_prefix:
            return True, 0.9
        return True, (0.7 if mobile else 0.6)


class PhoneRecognizerFactory:
    @staticmethod
    def build(cfg: Any) -> PhoneRecognizer:
        return PhoneRecognizer(mask_800=cfg.phone.mask_800, mask_444=cfg.phone.mask_444)
