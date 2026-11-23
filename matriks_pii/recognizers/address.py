"""Türkiye adresleri: çapa tabanlı genişletme."""

from __future__ import annotations

import re

from .. import data
from ..text_utils import fold_key, fre, is_capitalized
from .base import AnalysisContext, Recognizer, Span

_L = "A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû"
_APOS_SPLIT = re.compile(r"['’]")
_TOKEN_RE = re.compile(rf"[{_L}0-9]+(?:['’][{_L}]+)?|[/:\-,.()]")

# casefolded metinde aranır; (?![harf]) ile "Katılım", "Mahalle baskısı" dışlanır
_ANCHOR_RE = fre(
    r"(?<![a-zçğıöşü0-9])(?:"
    r"(?P<mah>mahallesi|mah\.|mah(?=\s)|mh\.)"
    r"|(?P<sok>sokak|sokağı|sok\.|sk\.)"
    r"|(?P<cad>caddesi|cad\.|cd\.)"
    r"|(?P<blv>bulvarı|bulvar|blv\.|bulv\.|bulv(?=\s))"
    r"|(?P<kirsal>köyü|kyü\.|kyü(?=\s)|mevkii|mvk\.|beldesi|kasabası|yaylası)"
    r"|(?P<apt>apartmanı|apartman|apt\.|apt(?=\s))"
    r"|(?P<site>sitesi|blok|blokları|plaza|residence|rezidans|konutları|evleri)"
    r"|(?P<no>no(?:[ \t]{0,3}[:.])?[ \t]{0,5}[0-9]+(?:[ \t]?[/\-][ \t]?[0-9a-z])?(?![0-9]))"
    r"|(?P<daire>daire(?:[ \t]{0,3}[:.])?[ \t]{0,5}[0-9]+|d[ \t]?[:.][ \t]*[0-9]+)"
    r"|(?P<kat>kat(?:[ \t]{0,3}[:.])?[ \t]{0,5}[0-9]+|k[ \t]?[:.][ \t]*[0-9]+)"
    r"|(?P<pk>posta kodu(?:[ \t]{0,3}[:.])?[ \t]{0,5}[0-9]{5}|p\.?k\.?(?:[ \t]{0,3}[:.])?[ \t]{0,5}[0-9]{5})"
    r")(?![a-zçğıöşü])"
)
_POSTAL_RE = re.compile(r"(?<![0-9.,])(0[1-9]|[1-7][0-9]|8[01])[0-9]{3}(?![0-9.,])")
_LABEL_WORDS = frozenset(
    fold_key(x)
    for x in "adres adresi adresim adresimiz ev iş ikametgah ikamet teslimat fatura gönderim kargo şube ofis".split()
)
_CONNECTORS = frozenset({"no", "kat", "daire", "blok", "d", "k"})


def _true_sentence_start(text: str, pos: int) -> bool:
    """Metnin ya da cümlenin (., !, ?, satır sonu) ilk sözcüğü mü? (İki nokta sonrası sayılmaz: "Adresim: Ahmet Yılmaz Sok.")"""
    before = text[:pos]
    prev = before.rstrip()
    return not prev or prev[-1] in ".!?" or "\n" in before[len(prev):]


class AddressRecognizer(Recognizer):
    name = "address"
    entities = ("ADRES",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        cf = ctx.casefolded
        anchors = [(m.start(), m.end(), m.lastgroup or "") for m in _ANCHOR_RE.finditer(cf)]
        g = data.geo()
        postals = []
        for m in _POSTAL_RE.finditer(text):
            if m.group() in g.postal_codes:
                postals.append((m.start(), m.end()))
        if not anchors and not postals:
            return []
        toks = [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]
        if not toks:
            return []

        def tok_index(pos: int) -> int:
            lo, hi = 0, len(toks) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if toks[mid][1] <= pos:
                    lo = mid + 1
                else:
                    hi = mid
            return lo

        # her token'ın bir çapa/posta kodu içinde olup olmadığı: tek geçişte (O(n))
        anchor_flags = [False] * len(toks)
        for a, b in [(x, y) for x, y, _ in anchors] + postals:
            k = tok_index(a)
            while k < len(toks) and toks[k][0] < b:
                if a <= toks[k][0] and toks[k][1] <= b:
                    anchor_flags[k] = True
                k += 1

        def in_anchor(i: int) -> bool:
            return anchor_flags[i]

        compat_cache: dict[int, bool] = {}

        def compatible(i: int) -> bool:
            v = compat_cache.get(i)
            if v is None:
                v = compat_cache[i] = _compatible(i)
            return v

        def _compatible(i: int) -> bool:
            s, e, w = toks[i]
            if in_anchor(i):
                return True
            if w in "/:-,.()":
                return True
            if w.isdigit():
                return len(w) <= 5
            base = _APOS_SPLIT.split(w, 1)[0]
            if is_capitalized(base) and fold_key(base) not in _LABEL_WORDS:
                return True
            k = fold_key(base)
            return k in _CONNECTORS or g.is_place(k)

        regions: list[tuple[int, int]] = []
        seeds = [tok_index(a) for a, _, _ in anchors] + [tok_index(a) for a, _ in postals]
        for si in sorted(set(seeds)):
            # sola genişle: en fazla 5 sözcük; virgülde dur (önceki token çapa değilse)
            i, words = si, 0
            while i - 1 >= 0 and compatible(i - 1):
                s_prev, e_prev, w_prev = toks[i - 1]
                gap = text[e_prev : toks[i][0]]
                if "\n" in gap and not in_anchor(i - 1) or len(gap) > 2:
                    break
                if w_prev == "," and not (i - 2 >= 0 and in_anchor(i - 2)):
                    break
                # sıra sayısı noktası ("5. sokak") adresin parçasıdır; diğer noktalar cümle sınırı
                if w_prev == "." and not in_anchor(i - 1) and not (i - 2 >= 0 and toks[i - 2][2].isdigit()):
                    break
                if w_prev.isalpha():
                    words += 1
                    if words > 5:
                        break
                i -= 1
            j, words = si, 0
            while j + 1 < len(toks) and compatible(j + 1):
                gap = text[toks[j][1] : toks[j + 1][0]]
                if len(gap) > 2 or ("\n" in gap and not in_anchor(j + 1)):
                    break
                w_next = toks[j + 1][2]
                # çapanın parçası olmayan nokta cümle sonudur ("...Karatay/Konya. Talep: ...")
                if w_next == "." and not in_anchor(j + 1) and not in_anchor(j):
                    break
                if w_next.isalpha() and not in_anchor(j + 1):
                    words += 1
                    if words > 8:
                        break
                j += 1
            regions.append((i, j))

        # bitişik/çakışan bölgeleri birleştir
        regions.sort()
        merged: list[list[int]] = []
        for a, b in regions:
            if merged and a <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])

        out: list[Span] = []
        for a, b in merged:
            # baştaki/sondaki noktalama ve etiket sözcüklerini kırp
            while a <= b and (toks[a][2] in "/:-,.()" or fold_key(toks[a][2]) in _LABEL_WORDS):
                a += 1
            # cümle başındaki sıradan sözcük ("Kartımı Alsancak Mah. …"): ardından büyük harfli ad geliyorsa adres değildir
            tr_words = data.tr_words()
            while (a + 1 <= b and toks[a][2].isalpha() and not in_anchor(a) and _true_sentence_start(text, toks[a][0])
                   and fold_key(toks[a][2]) in tr_words and not g.is_place(fold_key(toks[a][2]))
                   and toks[a + 1][2][:1].isupper() and toks[a + 1][2].isalpha() and not in_anchor(a + 1)):
                a += 1
            while b >= a and toks[b][2] in "/:-,(":
                b -= 1
            if b >= a and toks[b][2] == "." and not in_anchor(b):
                b -= 1
            if a > b:
                continue
            s, e = toks[a][0], toks[b][1]
            # çapa sınırını kesmesin
            for x, y, _ in anchors:
                if x < e < y:
                    e = y
            seg_anchors = [kind for x, y, kind in anchors if s <= x and y <= e]
            seg_postal = [(x, y) for x, y in postals if s <= x and y <= e]
            n_anchor = len(seg_anchors) + (1 if seg_postal else 0)
            seg_words = [fold_key(re.split(r"['’]", t[2])[0]) for t in toks[a : b + 1] if t[2][:1].isalpha()]
            has_place = any(g.is_province_or_district(w) or w in g.semtler for w in seg_words)
            bare_number = any(t[2].isdigit() and len(t[2]) <= 4 for t in toks[a : b + 1])
            ok = n_anchor >= 2 and any(k != "site" for k in seg_anchors) or (
                n_anchor == 1 and has_place and (bool(seg_postal) or seg_anchors == ["no"])
            ) or (
                # "Bağdat Cad. 100 Kadıköy": tek cadde/sokak/bulvar çapası + kapı numarası + il/ilçe
                n_anchor == 1 and has_place and bare_number and seg_anchors in (["cad"], ["sok"], ["blv"])
            )
            if not ok:
                continue
            score = 0.8 + (0.1 if seg_postal else 0.0)
            v = text[s:e]
            # sondaki iyelik/hâl eki apostrofu ("İstanbul'da") span içinde kalabilir; normalize et
            norm = " ".join(fold_key(v).split())
            out.append(Span(s, e, "ADRES", v, score, self.name, norm))
        return out
