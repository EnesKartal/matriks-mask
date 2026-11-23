"""TCKN, VKN, IBAN, kart (+CVV/SKT) tanıyıcıları."""

from __future__ import annotations

import re

from ..text_utils import fre
from .base import AnalysisContext, Recognizer, Span, ctx_prefix_re
from .checksums import card_valid, iban_valid, tckn_valid, vkn_valid

# ------------------------------------------------------------------ IBAN
# karakter düzeyinde (gruplar belirsiz bölünmesin → doğrusal); grup sınırları aşağıda ayrıca çıkarılır
_IBAN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2}[0-9]{2}(?:[ \-]?[A-Za-z0-9]){11,30})(?![A-Za-z0-9])")
_GROUP_RE = re.compile(r"[ \-]?[A-Za-z0-9]{1,4}")


# "IBAN: 33 0006 …" (TR yazılmamış) veya "IBAN TR 33 …" (TR'den sonra boşluk): yalnız IBAN etiketi hemen önündeyse
_IBAN_TR_LOOSE = re.compile(r"(?<![A-Za-z0-9])(?:TR ?)?[0-9]{2}(?:[ \-]?[0-9]){22}(?![0-9])", re.IGNORECASE)
_IBAN_WORD = fre(r"(?<![a-z])iban(?:ım|im|ı|i|ın|in)?\s*(?:no|numarası|numaram)?\s*[:=]?\s*$")


class IbanRecognizer(Recognizer):
    """TR + yabancı IBAN. mod-97'den geçmeyen IBAN adayları dışlama bölgesine yazılır."""

    name = "iban"
    entities = ("IBAN",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = self._find_strict(text, ctx)
        taken = [(s.start, s.end) for s in out]
        for m in _IBAN_TR_LOOSE.finditer(text):
            s, e = m.start(), m.end()
            if any(a < e and s < b for a, b in taken) or not _IBAN_WORD.search(ctx.casefolded[max(0, s - 14) : s]):
                continue
            compact = re.sub(r"[ \-]", "", m.group()).upper()
            if not compact.startswith("TR"):
                compact = "TR" + compact
            if iban_valid(compact) or (ctx.cfg.checksum_policy == "context" and len(compact) == 26):
                out.append(Span(s, e, "IBAN", m.group(), 0.9, self.name, compact))
        return out

    def _find_strict(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        for m in _IBAN_RE.finditer(text):
            s = m.start(1)
            cc = text[s : s + 2]
            is_tr = cc.upper() == "TR"
            if not is_tr and not cc.isupper():
                continue
            # 4 karakterlik başlıktan sonraki grupların bitiş konumları
            ends = [s + 4]
            for g in _GROUP_RE.finditer(text, s + 4, m.end(1)):
                ends.append(g.end())
            found = None
            for e in reversed(ends):
                cand = text[s:e]
                compact = re.sub(r"[ \-]", "", cand)
                if len(compact) < 15:
                    break
                if iban_valid(compact):
                    found = (e, compact)
                    break
            if found is None and is_tr and ctx.cfg.checksum_policy == "context":
                for e in reversed(ends):
                    compact = re.sub(r"[ \-]", "", text[s:e])
                    if len(compact) == 26 and compact[2:].isdigit():
                        found = (e, compact)
                        break
            if found:
                e, compact = found
                out.append(Span(s, e, "IBAN", text[s:e], 0.95 if is_tr else 0.85, self.name, compact.upper()))
            else:
                # en uzun "rakam ağırlıklı" önek dışlama bölgesi olur (sondaki yalnız-harf grupları hariç)
                e_ex = s + 4
                for e in ends[1:]:
                    grp = text[e_ex:e].strip(" -")
                    if grp.isalpha():
                        break
                    e_ex = e
                compact = re.sub(r"[ \-]", "", text[s:e_ex])
                if len(compact) >= 15 and sum(c.isdigit() for c in compact) >= 10:
                    ctx.add_exclusion(s, e_ex)
        return out


# ------------------------------------------------------------------ TCKN
_TCKN_RE = re.compile(r"(?<![0-9])[1-9][0-9]{10}(?![0-9])")
_TCKN_CTX = ctx_prefix_re("tc", r"t\.c\.", "kimlik", "tckn", "nüfus", "tc no")
# checksum_policy=context için: değerin HEMEN önündeki etiket (≤ ~25 karakter)
_LABEL_TAIL = r"(?:\s*(?:no|numarası|numarasi|numaram|numaranız|si|sı|i|ı|nin|nın)?\s*[:.=]?\s*)$"
_TCKN_LABEL = fre(rf"(?<![a-z])(?:tc|t\.c\.|tckn|kimlik|tc kimlik|kimlik no){_LABEL_TAIL}")
_VKN_LABEL = fre(rf"(?<![a-z])(?:vergi|vkn|vergi kimlik|vergi no){_LABEL_TAIL}")
_IBAN_LABEL = fre(rf"(?<![a-z])(?:iban|ıban|hesap){_LABEL_TAIL}|(?:iban|ıban)\s+[a-zçğıöşü ]{{0,25}}$")
_CARD_LABEL = fre(rf"(?<![a-z])(?:kart|kartı|kartım|kredi kartı|banka kartı|card){_LABEL_TAIL}")


def _labeled(ctx: AnalysisContext, start: int, rx: object, window: int = 28) -> bool:
    return ctx.cfg.checksum_policy == "context" and rx.search(ctx.casefolded[max(0, start - window) : start]) is not None  # type: ignore[attr-defined]
_TCKN_GROUPED_RE = re.compile(
    r"(?<![0-9])(?:[1-9][0-9]{2}[ \-.][0-9]{3}[ \-.][0-9]{3}[ \-.][0-9]{2}|[1-9][0-9]{3}[ \-.][0-9]{4}[ \-.][0-9]{3}"
    r"|[1-9][0-9][ \-.][0-9]{3}[ \-.][0-9]{3}[ \-.][0-9]{3}"  # 17.291.716.060 (binlik ayraçlı)
    r"|[1-9](?: [0-9]){10})(?![0-9])"  # 1 7 2 9 1 7 1 6 0 6 0 (tek tek; bağlam şart)
)
# kontrol basamağı politikası "context": etiketli değerde rakam yerine O harfi ("1729171606O") → yazım hatası/atlatma
_TCKN_O_RE = re.compile(r"(?<![0-9A-Za-z])[1-9](?=[0-9Oo]{10}(?![0-9A-Za-z]))(?=[0-9]*[Oo])[0-9Oo]{10}")


class TcknRecognizer(Recognizer):
    name = "tckn"
    entities = ("TCKN",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = []
        for m in _TCKN_RE.finditer(text):
            if ctx.in_exclusion(m.start(), m.end()):
                continue
            v = m.group()
            if tckn_valid(v):
                out.append(Span(m.start(), m.end(), "TCKN", v, 0.95, self.name, v))
            elif _labeled(ctx, m.start(), _TCKN_LABEL):
                out.append(Span(m.start(), m.end(), "TCKN", v, 0.75, self.name, v))
            elif not ctx.cfg.tckn_require_checksum and ctx.has_context(m.start(), m.end(), _TCKN_CTX):
                out.append(Span(m.start(), m.end(), "TCKN", v, 0.6, self.name, v))
        if ctx.cfg.checksum_policy == "context":
            for m in _TCKN_O_RE.finditer(text):
                if _labeled(ctx, m.start(), _TCKN_LABEL) and not ctx.in_exclusion(m.start(), m.end()):
                    digits = re.sub("[Oo]", "0", m.group())
                    out.append(Span(m.start(), m.end(), "TCKN", m.group(), 0.75, self.name, digits))
        # gruplu yazım ("275 395 931 48", "172-917-160-60"): checksum + kimlik bağlamı birlikte şart
        for m in _TCKN_GROUPED_RE.finditer(text):
            digits = re.sub(r"[ \-.]", "", m.group())
            if len(digits) == 11 and (tckn_valid(digits) or _labeled(ctx, m.start(), _TCKN_LABEL)) and not ctx.in_exclusion(m.start(), m.end()):
                if ctx.context_before(m.start(), _TCKN_CTX, window=25):
                    out.append(Span(m.start(), m.end(), "TCKN", m.group(), 0.85, self.name, digits))
        return out


# ------------------------------------------------------------------ VKN
_VKN_RE = re.compile(r"(?<![0-9])[0-9]{10}(?![0-9])")
_VKN_CTX = ctx_prefix_re("vergi", "vkn", r"v\.k\.n", "mükellef")
_VERGI_WORD = ctx_prefix_re("vergi", "vkn")


class VknRecognizer(Recognizer):
    name = "vkn"
    entities = ("VKN",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = []
        for m in _VKN_RE.finditer(text):
            v = m.group()
            if ctx.in_exclusion(m.start(), m.end()):
                continue
            if not vkn_valid(v):
                if _labeled(ctx, m.start(), _VKN_LABEL):
                    out.append(Span(m.start(), m.end(), "VKN", v, 0.75, self.name, v))
                continue
            if not ctx.has_context(m.start(), m.end(), _VKN_CTX):
                continue
            if v[0] == "5" and not ctx.has_context(m.start(), m.end(), _VERGI_WORD):
                continue
            out.append(Span(m.start(), m.end(), "VKN", v, 0.9, self.name, v))
        return out


# ------------------------------------------------------------------ KART
_CARD_RE = re.compile(
    r"(?<![0-9\-])(?:"
    r"[0-9]{13,19}"
    r"|[0-9]{4}([ \-])[0-9]{4}\1[0-9]{4}\1[0-9]{4}(?:\1[0-9]{1,3})?"
    r"|[0-9]{4}[ \-][0-9]{6}[ \-][0-9]{5}"
    r"|[0-9]{4}[ \-][0-9]{6}[ \-][0-9]{4}"  # Diners 4-6-4
    r")(?![0-9\-])"
)
_CVV_CTX = fre(r"(?<![a-zçğıöşü])(?:cvv2?|cvc2?|güvenlik kodu|guvenlik kodu|kart doğrulama kodu)(?![a-zçğıöşü])")
_CVV_NUM = re.compile(r"(?<![0-9/.,])[0-9]{3,4}(?![0-9]|[/.,][0-9])")
_SKT_RE = re.compile(r"(?<![0-9/.])(0[1-9]|1[0-2])\s?/\s?([0-9]{2}|20[0-9]{2})(?![0-9/])")
_SKT_CTX = fre(r"(?<![a-zçğıöşü])(?:skt|son kullanma|son kul\.|expiry|exp|expiration|geçerlilik|valid thru)(?![a-zçğıöşü])")


class CardRecognizer(Recognizer):
    name = "credit_card"
    entities = ("KART", "KART_CVV", "KART_SKT")

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        for m in _CARD_RE.finditer(text):
            if ctx.in_exclusion(m.start(), m.end()):
                continue
            digits = re.sub(r"[ \-]", "", m.group())
            if card_valid(digits):
                out.append(Span(m.start(), m.end(), "KART", m.group(), 0.95, self.name, digits))
            elif 13 <= len(digits) <= 19 and _labeled(ctx, m.start(), _CARD_LABEL):
                out.append(Span(m.start(), m.end(), "KART", m.group(), 0.75, self.name, digits))
        cards = [(s.start, s.end) for s in out]
        cf = ctx.casefolded
        # CVV: bağlam kelimesinden sonraki 25 karakter içindeki 3-4 hane
        for c in _CVV_CTX.finditer(cf):
            seg_end = min(len(text), c.end() + 25)
            n = _CVV_NUM.search(text, c.end(), seg_end)
            if n and not any(a < n.end() and n.start() < b for a, b in cards):
                out.append(Span(n.start(), n.end(), "KART_CVV", n.group(), 0.85, self.name, n.group()))
        for m in _SKT_RE.finditer(text):
            if ctx.has_context(m.start(), m.end(), _SKT_CTX, window=40):
                norm = f"{m.group(1)}/{m.group(2)[-2:]}"
                out.append(Span(m.start(), m.end(), "KART_SKT", m.group(), 0.8, self.name, norm))
        return out
