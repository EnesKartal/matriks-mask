"""Yazıyla yazılmış sayılar ("tc sıfır beş dört altı...", "kart no dört iki yedi dokuz...").

Kullanıcılar maskelemeyi aşmak ya da sesli asistan dökümü nedeniyle numaraları yazıyla yazabilir. Ardışık sayı
sözcükleri rakama çevrilir; önündeki etikete göre (tc, kart, iban, telefon, müşteri no, hesap, vergi) tür belirlenir.
Etiket yoksa yalnız kendi doğrulamasından geçen değerler (TCKN checksum, kart Luhn+BIN, 05xx cep) kabul edilir.
"""

from __future__ import annotations

import re

from ..text_utils import fre
from .base import AnalysisContext, Recognizer, Span
from .checksums import card_valid, tckn_valid

UNITS = {"sifir": 0, "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
TENS = {"on": 10, "yirmi": 20, "otuz": 30, "kirk": 40, "elli": 50, "altmis": 60, "yetmis": 70, "seksen": 80, "doksan": 90}
_WORD = re.compile(r"[a-z]+")  # katlanmış metinde
_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("TCKN", fre(r"(?<![a-z])(?:tc|t\.c\.|tckn|kimlik)(?:\s*(?:no|numarası|numaram|si|sı))?\s*[:.]?\s*$")),
    ("IBAN", fre(r"(?<![a-z])(?:iban|ıban)(?:\s*(?:no|numarası|numaram|ım|im))?\s*[:.]?\s*(?:tr)?\s*$")),
    ("KART", fre(r"(?<![a-z])(?:kart|kartı|kartım|kredi kartı)(?:\s*(?:no|numarası|numaram))?\s*[:.]?\s*$")),
    ("TELEFON", fre(r"(?<![a-z])(?:tel|telefon|telefonu|telefonum|cep|gsm|numaram|numarası|numarasi)\s*[:.]?\s*$")),
    ("MUSTERI_NO", fre(r"(?<![a-z])müşteri\s*(?:no|numarası|numaram)\s*[:.]?\s*$")),
    ("HESAP_NO", fre(r"(?<![a-z])(?:hesap|hesap no|hesap numarası|talimatını)\s*[:.]?\s*$")),
    ("VKN", fre(r"(?<![a-z])(?:vergi|vkn)(?:\s*(?:no|numarası|kimlik))?\s*[:.]?\s*$")),
)
_LEN_OK = {"TCKN": (11, 11), "IBAN": (24, 26), "KART": (13, 19), "TELEFON": (10, 12), "MUSTERI_NO": (5, 12),
           "HESAP_NO": (6, 16), "VKN": (10, 10)}


class NumberWordsRecognizer(Recognizer):
    name = "number_words"
    entities = tuple(_LEN_OK)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        cf = ctx.casefolded
        if not any(w in cf for w in ("sifir", "bir", "iki", "uc", "dort", "bes", "alti", "yedi", "sekiz", "dokuz")):
            return []
        out: list[Span] = []
        words = [(m.start(), m.end(), m.group()) for m in _WORD.finditer(cf)]
        i, n = 0, len(words)
        while i < n:
            if words[i][2] not in UNITS and words[i][2] not in TENS:
                i += 1
                continue
            j = i
            digits = ""
            while j < n and (words[j][2] in UNITS or words[j][2] in TENS):
                if j > i and cf[words[j - 1][1] : words[j][0]].strip(" ,-") != "":
                    break  # sözcükler arasında boşluk/virgül dışında bir şey var
                w = words[j][2]
                if w in TENS:
                    nxt = words[j + 1][2] if j + 1 < n else ""
                    gap_ok = j + 1 < n and cf[words[j][1] : words[j + 1][0]].strip() == ""
                    if nxt in UNITS and UNITS[nxt] != 0 and gap_ok:
                        digits += str(TENS[w] + UNITS[nxt])
                        j += 2
                        continue
                    digits += str(TENS[w])
                else:
                    digits += str(UNITS[w])
                j += 1
            if len(digits) >= 7 and j - i >= 5:
                s, e = words[i][0], words[j - 1][1]
                ent = self._entity(cf[max(0, s - 30) : s], digits)
                if ent:
                    out.append(Span(s, e, ent, text[s:e], 0.8, self.name, digits))
            i = max(j, i + 1)
        return out

    @staticmethod
    def _entity(before: str, digits: str) -> str | None:
        for ent, rx in _LABELS:
            if rx.search(before):
                lo, hi = _LEN_OK[ent]
                return ent if lo <= len(digits) <= hi or ent in ("TCKN", "IBAN", "KART") and len(digits) >= 9 else None
        if len(digits) == 11 and tckn_valid(digits):
            return "TCKN"
        if card_valid(digits):
            return "KART"
        if len(digits) in (10, 11) and digits.lstrip("0").startswith("5"):
            return "TELEFON"
        return None
