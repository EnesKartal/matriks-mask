"""Türkçe kişi adı tanıyıcı: sözlük + bağlam + morfoloji."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .. import data
from ..text_utils import (
    APOS_CHARS,
    ascii_fold,
    fold_key,
    fre,
    is_all_upper,
    is_capitalized,
    is_sentence_start,
    tr_lower,
    trie_pattern,
)
from ..tr_morphology import strip_suffixes
from .base import AnalysisContext, Recognizer, Span

_L = "A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû̀-ͯ"
_TOKEN_RE = re.compile(rf"(?P<b>[{_L}]+)(?:[{APOS_CHARS}](?P<s>[{_L}]+))?")

MONTHS = frozenset("ocak subat mart nisan mayis haziran temmuz agustos eylul ekim kasim aralik".split())
DAYS = frozenset("pazartesi sali carsamba persembe cuma cumartesi pazar".split())
_PLACE_SUFFIX = re.compile(r"^(?:n?(?:da|de|ta|te|dan|den|tan|ten|daki|deki|taki|teki)|y?[ae])$")
_SEP = r"[\s_\-]*"
_NAME_GAPS = (" ", "\u00a0", "\t")
_ORIGIN_AFTER = re.compile(r"\s+(?:kokenli|asilli)")  # katlanmış metinde


def _origin_follows(folded: str, pos: int) -> bool:
    return _ORIGIN_AFTER.match(folded, pos) is not None
_NATIONALITY_CTX = frozenset({"uyrugu", "uyruk", "uyruklu", "vatandasligi", "milliyeti", "nationality"})
_LOCATIVE = re.compile(r"^n?(?:da|de|ta|te|dan|den|tan|ten|daki|deki|taki|teki)$")
# ad sözlüğünde bulunan ama selamlama/işlev sözcüğü olan token'lar (tr_lower)
NOT_NAMES = frozenset(
    "merhaba selam selamlar sevgili değerli sayın günaydın iyi tamam evet hayır lütfen teşekkürler dün bugün yarın "
    "ayrıca ancak fakat ama çünkü için ile ve hoş geldiniz saygılarımla not konu ek bilgi rica "
    # akrabalık/ilişki sözcükleri: ada yapışırsa aynı kişi iki farklı yer tutucu alır ("Eşim Mehmet Demir" / "Mehmet Demir")
    "eşim eşi eşin annem annesi babam babası oğlum oğlu kızım kızı kardeşim kardeşi ablam abim ağabeyim "
    "müşterimiz müşterim danışanım öğrencim velisi vasisi vekili kefili "
    # adres kısaltmaları: "İnönü Cad.", "Zafer Mvk." ad-soyad sanılmasın
    "cad cd sok sk mah mh blv bulv apt mvk kyü köy no kat daire pk".split()
)

_CTX_STRONG = fre(
    rf"(?<![a-z])(?:anne{_SEP}adı|baba{_SEP}adı|annesinin{_SEP}adı|babasının{_SEP}adı|annesi|babası|annesinin|babasının|"
    rf"kızlık{_SEP}soyadı)[\"']?\s*[:=\-]?\s*[\"']?\s*$"
)
# form/JSON alan etiketi: "Ad: Tuba", "Soyad: Kocaman", "\"ad\": \"Volkan\"" → güçlü bağlam
_CTX_FIELD = fre(
    rf"(?<![a-z])(?:ad|adı|adi|soyad|soyadı|soyadi|isim|ismi|soyisim|soyismi|ad{_SEP}soyad|adı{_SEP}soyadı|"
    rf"name|first{_SEP}name|last{_SEP}name|full{_SEP}name|surname|müşteri{_SEP}adı|musteri{_SEP}adi|customer{_SEP}name|"
    rf"hesap{_SEP}sahibi|kart{_SEP}sahibi|yetkili{_SEP}kişi|ilgili{_SEP}kişi)[\"']?\s*[:=]\s*[\"']?\s*$"
)
# bağlam: aday ADDAN ÖNCE ("müşteri Ahmet", "Sigortalı Ayşe", "ben Zeynep")
_CTX_BEFORE = fre(
    rf"(?<![a-z])(?:adı|adım|ismi|ismim|soyadı|soyadım|ad{_SEP}soyad|adı{_SEP}soyadı|ben|benim{_SEP}adım|"
    r"müşteri|müşterimiz|müşterisi|müşteriniz|kullanıcı|kullanıcımız|sahibi|yetkili|yetkilisi|başvuran|başvuru sahibi|"
    r"sigortalı|sigortalımız|çalışan|çalışanımız|personel|personelimiz|eşi|eşim|vasisi|vekili|kefil|kefili|alıcı|"
    r"gönderen|hastamız|danışan|danışanımız|danışmanımız|danışman|öğrenci|öğrencimiz|veli|temsilci|temsilcisi|temsilcimiz|"
    r"muhatap|ilgili kişi|tanık|davacı|davalı|şikayetçi|lehtar|borçlu|alacaklı|arkadaşım|kardeşim|annem|babam|oğlum|"
    r"kızım|arayan|aranan|görüşülen|hoş geldiniz|merhaba|sayın|değerli|cc|kime|kimden|from|to|imza|imzalayan)"
    r"\s*[:\-,]?\s*$"
)
# bağlam: aday ADDAN SONRA ("Ahmet isimli müşteri", "Kerem aradı", "Kerem ile konuştum")
_CTX_AFTER = fre(
    r"^\s*(?:isimli|adlı|adındaki|isminde|adında|ismindeki|adına|kişisi|kişisine|kişisinin|kişisinden|"
    r"oğlu|kızı|eşi|oğlum|kızım|babası|annesi)(?![a-zçğıöşü])"
)
_IMZA = fre(r"(?<![a-z])(?:imza|imzalayan|saygılarımla|saygılarımızla|onaylayan|hazırlayan|düzenleyen|gönderen|kontrol eden|"
            r"yetkili|sorumlu)\s*[:,]?\s*$")
_CTX_AFTER_VERB = fre(
    r"^\s*(?:(?:ile|ve)\s+(?:konuştum|görüştüm|konuştuk|görüştük|toplantı)|aradı|arıyor|aramış|geldi|gelecek|gitti|söyledi|"
    r"dedi|demiş|yazdı|yazmış|istedi|istiyor|sordu|soruyor|konuştu|gönderdi|iletti|onayladı|imzaladı|bildirdi|belirtti|"
    r"talep etti|yatırdı|çekti|hazırladı|aktardı|bekliyor|izinde|toplantıda|şikayet etti)(?![a-zçğıöşü])"
)


@dataclass(slots=True)
class _Tok:
    start: int
    end: int  # kök sonu (apostrof veya bitişik ek öncesi)
    full_end: int
    base: str
    suffix: str
    key: str
    cap: bool
    upper: bool
    low: bool  # tamamen küçük harf
    first: bool
    last: bool
    common: str  # '' | 'weak' | 'strong'
    place: bool
    apos: bool  # apostroflu ek: Türkçe yazımda yalnız özel adlara gelir


class PersonRecognizer(Recognizer):
    name = "person"
    entities = ("KISI",)

    def __init__(self) -> None:
        self.firsts = data.first_names()
        self.lasts = data.last_names()
        self.cont_lasts = self.lasts | data.continuation_last_names()
        self.common = data.common_words()
        self.words = data.tr_words()
        self.pre_hon, self.post_hon = data.honorifics()
        self.org_suffixes = data.org_suffixes()
        geo = data.geo()
        self.places_tr = geo.places_tr  # Türkçe yazımla karşılaştır ("Çan" ilçesi ≠ "Can" adı)
        self.neighborhoods = geo.neighborhoods
        # özel nitelikli veri terimleri (Kürt, Arap, Rum...) ad sözlüğündeki ASCII karşılıklarıyla çakışmasın
        # köken bağlamı isteyen terimler (Arap, Türkmen, Kurt...) aynı zamanda yaygın soyad: not_names'e girmez; bunun
        # yerine "kökenli/asıllı" öncesinde ad dizisi durur (_origin_follows)
        self.not_names = frozenset(
            t.key for t in data.special_terms() if t.must_capitalize and not t.needs_origin_context
        ) | NOT_NAMES
        orgs = data.org_names()
        self.org_re = (
            re.compile(r"(?<![a-z0-9])(?:" + trie_pattern(orgs, space=" ") + r")(?![a-z0-9])") if orgs else None
        )

    # ------------------------------------------------------------------ tokenizasyon
    def _tokens(self, text: str, folded: str | None = None) -> list[_Tok]:
        toks: list[_Tok] = []
        for m in _TOKEN_RE.finditer(text):
            base = m.group("b")
            suffix = m.group("s") or ""
            apos = m.end() != m.start() + len(base)
            if base.isascii() or folded is None:
                nfc = base if base.isascii() else unicodedata.normalize("NFC", base)
                key = folded[m.start() : m.start() + len(base)] if folded is not None else fold_key(nfc)
            else:
                nfc = unicodedata.normalize("NFC", base)
                key = folded[m.start() : m.start() + len(base)] if nfc == base else fold_key(nfc)
            end = m.start() + len(base)
            if not nfc[:1].isupper():
                low = nfc.islower()
                toks.append(
                    _Tok(m.start(), end, m.end(), base, suffix, key, False, False, low,
                         low and key in self.firsts, low and key in self.lasts, self.common.get(key, ""), False, apos)
                )
                continue
            rest = nfc[1:]
            upper = len(nfc) >= 2 and nfc.isupper()
            cap = upper or not rest or rest.islower()
            lowered = tr_lower(nfc)
            not_name = lowered in self.not_names
            first = key in self.firsts and not not_name
            last = key in self.lasts and not not_name
            # bitişik ek ("Ahmetin", "Ayşeye"): tam sözcük sık Türkçe sözcük değilse kök aranır
            if cap and not suffix and not (first or last) and not not_name and len(key) >= 4 and key not in self.words:
                for cand in strip_suffixes(nfc):
                    if tr_lower(cand) in self.not_names:
                        break  # "Kürtçe" → "Kürt": özel nitelikli terim ad sayılmaz
                    ck = fold_key(cand)
                    if (ck in self.firsts or ck in self.lasts) and len(ck) >= 3:
                        if len(nfc) == len(base):
                            end = m.start() + len(cand)
                        key, first, last = ck, ck in self.firsts, ck in self.lasts
                        suffix = nfc[len(cand) :]
                        break
            toks.append(
                _Tok(m.start(), end, m.end(), base, suffix, key, cap, upper, False, first, last,
                     self.common.get(key, ""),
                     lowered in self.places_tr
                     or (apos and bool(_LOCATIVE.match(fold_key(suffix))) and key in self.neighborhoods),
                     apos)
            )
        return toks

    def _is_hon(self, t: _Tok) -> bool:
        return t.key in self.pre_hon or t.key in self.post_hon

    @staticmethod
    def _ctx_bonus(ctx: AnalysisContext, start: int, full_end: int) -> float:
        before = ctx.casefolded[max(0, start - 40) : start]
        after = ctx.casefolded[full_end : full_end + 30]
        if _CTX_FIELD.search(before):
            return 0.5
        if _CTX_STRONG.search(before):
            return 0.4
        if _CTX_BEFORE.search(before) or _CTX_AFTER.match(after):
            return 0.3
        if _CTX_AFTER_VERB.match(after):
            return 0.25
        return 0.0

    # ------------------------------------------------------------------ ana akış
    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        folded = ascii_fold(ctx.casefolded)
        toks = self._tokens(text, folded)
        if not toks:
            return []
        org_zones = [(m.start(), m.end()) for m in self.org_re.finditer(folded)] if self.org_re else []

        def in_org(s: int, e: int) -> bool:
            return any(s < b and a < e for a, b in org_zones)

        def gap_ok(a: _Tok, b: _Tok) -> bool:
            if a.suffix:
                return False
            g = text[a.full_end : b.start]
            if g in _NAME_GAPS:  # boşluk, NBSP, sekme (yapıştırılmış tablo)
                return True
            # tireli çift soyad: "Demir-Yılmaz"
            return g == "-" and a.last and b.last and a.cap and b.cap

        results: list[tuple[int, int, float, str]] = []
        used = [False] * len(toks)
        full_name_keys: set[str] = set()

        i, n = 0, len(toks)
        while i < n:
            t = toks[i]
            lower_seq = t.low and t.first
            if not ((t.cap and (t.first or t.last)) or lower_seq) or self._is_hon(t):
                i += 1
                continue
            j = i
            while j + 1 < n and j - i < 3 and gap_ok(toks[j], toks[j + 1]):
                nx = toks[j + 1]
                if self._is_hon(nx):
                    break
                if lower_seq:
                    ok = nx.low and (nx.first or nx.last) and not (j > i and nx.common == "strong")
                else:
                    case_ok = (
                        nx.upper == t.upper
                        # "Ahmet YILMAZ": Title ad + BÜYÜK soyad (imza/resmî yazışma)
                        or (not t.upper and nx.upper and (nx.last or nx.key in self.cont_lasts) and nx.common != "strong")
                        # "YILMAZ Ahmet": resmî liste sırası
                        or (t.upper and not nx.upper and t.last and nx.first and j == i)
                    )
                    tail_dash = text[nx.full_end : nx.full_end + 1] == "-"
                    ok = (
                        nx.cap and case_ok and not in_org(nx.start, nx.end) and nx.key not in MONTHS | DAYS
                        and not _origin_follows(ctx.casefolded, nx.full_end)
                        and (not tail_dash or (j + 2 < n and toks[j + 2].last and toks[j + 2].cap))
                        and (nx.first or nx.last or (nx.key in self.cont_lasts and tr_lower(nx.base) not in self.not_names))
                    )
                if not ok:
                    break
                j += 1
            seq = toks[i : j + 1]
            if len(seq) >= 2:
                score = self._score_full(seq)
                if score is not None:
                    s, e = seq[0].start, seq[-1].end
                    if lower_seq:  # küçük harfle yazılmış ad-soyad: daha zayıf kanıt, bağlam çok önemli
                        score -= 0.3
                        if ctx.casefolded[e : e + 1].isalnum():
                            score = 0.0
                    score += self._ctx_bonus(ctx, s, seq[-1].full_end) * (1.0 if lower_seq else 0.5)
                    score = self._adjust(text, toks, j, score, in_org(s, e))
                    results.append((s, e, score, " ".join(x.key for x in seq)))
                    if score >= 0.5:
                        full_name_keys.update(x.key for x in seq)
                    for k in range(i, j + 1):
                        used[k] = True
                    i = j + 1
                    continue
            i += 1

        # sözlükte olmayan (nadir/yabancı) ad veya soyad içeren ikililer: "Deniz Kurgusal", "Simber Şensoy", "Özerdinç Manço'ya"
        for k in range(n - 1):
            a, b = toks[k], toks[k + 1]
            if used[k] or used[k + 1] or not (a.cap and b.cap) or a.upper != b.upper or not gap_ok(a, b):
                continue
            if self._is_hon(a) or self._is_hon(b) or a.key in self.org_suffixes or b.key in self.org_suffixes:
                continue
            if {a.key, b.key} & (MONTHS | DAYS) or tr_lower(a.base) in self.not_names or tr_lower(b.base) in self.not_names:
                continue
            if text[b.full_end : b.full_end + 1] == "-":
                continue
            ctx_b = self._ctx_bonus(ctx, a.start, b.full_end)
            a_rare = not (a.first or a.last) and len(a.key) >= 3 and a.key not in self.words and not a.place
            b_rare = not (b.first or b.last) and len(b.key) >= 3 and b.key not in self.words and not b.place
            score = 0.0
            if a.first and a.common != "strong" and not (b.first or b.last):
                if b_rare:
                    score = 0.7
                elif ctx_b >= 0.3 and not b.place:
                    score = 0.6  # "Yaren Deneme adına": sözcük-soyad ancak güçlü bağlamla
            elif a_rare and b.last and not b.place:
                score = 0.75 if (ctx_b > 0 or b.apos) else 0.0
            elif a_rare and b_rare and ctx_b >= 0.3:
                score = 0.7
            if score <= 0:
                continue
            s, e = a.start, b.end
            score = self._adjust(text, toks, k + 1, score, in_org(s, e))
            if score >= 0.5:
                results.append((s, e, score, a.key + " " + b.key))
                used[k] = used[k + 1] = True

        for idx, t in enumerate(toks):
            if used[idx]:
                continue
            sc = self._score_single(text, ctx, toks, idx, full_name_keys)
            if sc is None:
                continue
            sc = self._adjust(text, toks, idx, sc, in_org(t.start, t.end))
            results.append((t.start, t.end, sc, t.key))

        # "SOYAD, AD" ve "A. SOYAD" kalıpları
        for m in re.finditer(rf"(?<![{_L}])([A-ZÇĞİÖŞÜ][{_L}]+),\s([A-ZÇĞİÖŞÜ][{_L}]+)(?![{_L}])", text):
            sk, fk = fold_key(m.group(1)), fold_key(m.group(2))
            same_case = not (not is_all_upper(m.group(1)) and is_all_upper(m.group(2)))  # "YILMAZ, Ahmet" olur
            # "Tolga Erdoğan, Pınar Aksu" bir ad listesidir: soyadın önünde ad ya da adın ardında soyad varsa atla
            prev_w = re.search(rf"([{_L}]+)\s+$", text[max(0, m.start() - 30) : m.start()])
            next_w = re.match(rf"\s+([{_L}]+)", text[m.end() : m.end() + 30])
            if (prev_w and is_capitalized(prev_w.group(1)) and fold_key(prev_w.group(1)) in self.firsts) or (
                next_w and is_capitalized(next_w.group(1)) and fold_key(next_w.group(1)) in self.lasts
            ):
                continue
            if same_case and sk in self.lasts and fk in self.firsts and self.common.get(sk) != "strong" and not in_org(m.start(), m.end()):
                results.append((m.start(), m.end(), 0.7 if fk not in self.common else 0.55, fk + " " + sk))
        for m in re.finditer(rf"(?<![{_L}.])([A-ZÇĞİÖŞÜ])\.\s?([A-ZÇĞİÖŞÜ][{_L}]+)(?![{_L}])", text):
            lk = fold_key(m.group(2))
            # sözcük-soyad ("A. Yılmaz") yalnız hitap/imza bağlamında ("Sayın A. Yılmaz", "imza: A. Yılmaz")
            ctx_ok = bool(_CTX_BEFORE.search(ctx.casefolded[max(0, m.start() - 30) : m.start()])
                          or _CTX_FIELD.search(ctx.casefolded[max(0, m.start() - 30) : m.start()])
                          or _IMZA.search(ctx.casefolded[max(0, m.start() - 30) : m.start()]))
            if lk in self.lasts and (not self.common.get(lk) or ctx_ok) and not in_org(m.start(), m.end()):
                results.append((m.start(), m.end(), 0.8, m.group(1).lower() + ". " + lk))

        return [
            Span(s, e, "KISI", text[s:e], round(min(sc, 0.99), 3), self.name, " ".join(key.split()))
            for s, e, sc, key in results
            if sc > 0
        ]

    # ------------------------------------------------------------------ skorlar
    def _score_full(self, seq: list[_Tok]) -> float | None:
        head, tail = seq[0], seq[-1]
        if all(x.place for x in seq):
            return None  # "Çan Çanakkale", "Kadıköy İstanbul": yer adı dizisi
        if not head.first:
            # "YILMAZ Ahmet" (soyad-ad) — resmi listelerde
            if head.last and tail.first and len(seq) == 2 and not head.common:
                return 0.75
            return None
        if tail.last or tail.key in self.cont_lasts:
            score = 0.9
        elif all(x.first for x in seq):
            score = 0.75
        else:
            return None
        # ad-soyad dizisi tek başına güçlü kanıttır; sözlük çakışmasına yalnız hafif ceza
        commons = [x.common for x in seq]
        for c in commons:
            if c:
                score -= 0.05 if c == "weak" else 0.15
        if all(commons) and "strong" in commons:
            score -= 0.2
        return score

    def _score_single(
        self, text: str, ctx: AnalysisContext, toks: list[_Tok], idx: int, full_keys: set[str]
    ) -> float | None:
        t = toks[idx]
        if not t.cap:
            # form/JSON alanında küçük harfli ad ("Ad: ahmet", "ad": "ahmet"): alan etiketi güçlü kanıttır
            if t.low and (t.first or t.last) and len(t.key) >= 3 and not self._is_hon(t) \
                    and _CTX_FIELD.search(ctx.casefolded[max(0, t.start - 40) : t.start]):
                return 0.7
            return None
        if self._is_hon(t):
            return None
        field = _CTX_FIELD.search(ctx.casefolded[max(0, t.start - 40) : t.start]) is not None
        prev = toks[idx - 1] if idx > 0 else None
        nxt = toks[idx + 1] if idx + 1 < len(toks) else None
        gap_prev = text[prev.full_end : t.start] if prev else ""
        prev_adjacent = prev is not None and gap_prev in (" ", ". ", ".", " ") and not prev.suffix
        next_adjacent = nxt is not None and text[t.full_end : nxt.start] in (" ", " ") and not t.suffix
        hon_pre = prev_adjacent and prev is not None and prev.key in self.pre_hon
        hon_post = next_adjacent and nxt is not None and nxt.key in self.post_hon
        listed = t.first or t.last

        if (t.key in MONTHS or t.key in DAYS) and not (hon_pre or hon_post or field):
            return None
        if prev is not None and prev.key in _NATIONALITY_CTX:
            return None  # "uyruğu Türk", "vatandaşlığı Alman"
        if _origin_follows(ctx.casefolded, t.full_end):
            return None  # "Kurt kökenli", "Arap asıllı": etnik köken ifadesi, kişi adı değil
        # tek başına BÜYÜK HARF token (hisse kodu, kısaltma) aday değildir; istisna: apostroflu ekli sözlük adı ("AHMET'in")
        upper_named = t.apos and len(t.key) >= 3 and listed and not t.common and not t.place
        if t.upper and not (hon_pre or hon_post or field or upper_named):
            return None
        if field and listed and not t.upper:
            return 0.85  # "Soyad: Bozkurt", "Ad: Irmak": açık alan etiketi yer adı/sözcük cezasını geçersiz kılar
        if hon_pre or hon_post:
            if listed:
                return 0.85
            if len(t.base) >= 3 and not t.common and not t.place and t.key not in self.words:
                return 0.75  # sözlükte olmayan ad + unvan ("Sayın Zühtü")
            return None
        if not listed:
            strong_ctx = _CTX_STRONG.search(ctx.casefolded[max(0, t.start - 40) : t.start]) is not None
            if (field or strong_ctx) and len(t.base) >= 2 and not t.place and t.key not in self.words:
                return 0.7  # form alanında sözlük dışı ad ("Ad: Zühtü", "name": "John")
            return None
        family = nxt is not None and next_adjacent and nxt.key.startswith(("ailesi", "ailesin", "soyadl", "soyad"))
        score = (0.35 if is_sentence_start(text, t.start) else 0.6) if t.first and not family else 0.3
        if (t.apos or (t.suffix and not t.common)) and not t.place:
            # "Ayşe'nin", "Can'a": apostrof yalnız özel adlara gelir → sözlük cezası uygulanmaz;
            # bitişik ek ("Ahmetin", "Ayşeye") sözlükte olmayan sözcükten kök çıkarıldıysa aynı kanıt
            score += 0.25
        elif t.common:
            score -= 0.1 if t.common == "weak" else 0.25
        if t.place:
            score -= 0.4 if (t.suffix and _PLACE_SUFFIX.match(fold_key(t.suffix))) else 0.3
        score += self._ctx_bonus(ctx, t.start, t.full_end)
        nb = self._coord_neighbor(text, toks, idx)
        if t.first and nb is not None and (not t.common or (t.common == "weak" and nb.apos)):
            score += 0.25  # "Ahmet ve Ayşe", "Ayşe, Ahmet ile": bağlaçla bağlı komşu da ad → kişi listesi
        if t.key in full_keys and ctx.cfg.name_detection.propagate_names:
            score += 0.4
        return score

    def _coord_neighbor(self, text: str, toks: list[_Tok], idx: int) -> _Tok | None:
        """Sağda/solda "ve"/"ile" ya da ", " ile bağlı, büyük harfli, sözlükte ad/soyad olan komşu var mı?"""
        t = toks[idx]

        def name_like(o: _Tok) -> bool:
            return o.cap and (o.first or o.last) and not self._is_hon(o) and not o.upper

        cands: list[_Tok] = []
        if idx + 1 < len(toks) and not t.suffix:
            a = toks[idx + 1]
            gap = text[t.full_end : a.start]
            if gap == ", ":
                cands.append(a)
            elif gap == " " and a.key in ("ve", "ile") and idx + 2 < len(toks) and text[a.full_end : toks[idx + 2].start] == " ":
                cands.append(toks[idx + 2])
        if idx > 0:
            b = toks[idx - 1]
            gap = text[b.full_end : t.start]
            if gap == ", " and not b.suffix:
                cands.append(b)
            elif gap == " " and b.key in ("ve", "ile") and idx > 1 and text[toks[idx - 2].full_end : b.start] == " ":
                cands.append(toks[idx - 2])
        return next((o for o in cands if name_like(o)), None)

    def _adjust(self, text: str, toks: list[_Tok], j: int, score: float, org: bool) -> float:
        if org:
            return 0.0
        nxt = toks[j + 1] if j + 1 < len(toks) else None
        # adın kendisi ekli ise ("Kaya'nın portföyü") ardından gelen sözcük kurum eki değildir
        # yalnız BÜYÜK harfle başlayan devam kurum unvanıdır ("Anadolu Sigorta", "Deniz Yatırım"); küçük harfli sıradan
        # sözcük ("Ayşe Demir ilaç aldı", "portföy raporu") cümlenin devamıdır
        if nxt is not None and nxt.cap and not toks[j].apos and text[toks[j].full_end : nxt.start] in (" ", " "):
            if nxt.key in self.org_suffixes or fold_key(text[nxt.start : nxt.full_end]) in self.org_suffixes:
                score -= 0.5
        if toks[j].key in self.org_suffixes:
            score -= 0.5
        return score
