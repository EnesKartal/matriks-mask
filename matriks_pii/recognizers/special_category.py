"""KVKK m.6 özel nitelikli veri terimleri: kişiye bağlılık şartlı."""

from __future__ import annotations

import re
from functools import lru_cache

from .. import data
from ..text_utils import ascii_fold, fold_key, fre, is_sentence_start, tr_lower, trie_pattern
from .base import AnalysisContext, Recognizer, Span

_LOW = "a-zçğıöşüâîû"

# terimden sonra gelebilecek kapalı ek kümesi (çekim + sık yapım ekleri)
_SUFFIX_FORMS = sorted(
    set(
        ascii_fold(
            "nın nin nun nün ın in un ün ya ye a e yı yi yu yü ı i u ü da de ta te dan den tan ten "
            "yla yle la le lar ler ki dır dir dur dür tır tir tur tür ım im um üm ımız imiz umuz ümüz "
            "ınız iniz unuz ünüz ca ce ça çe lı li lu lü sız siz suz süz lık lik luk lük sı si su sü "
            "nı ni nu nü na ne nda nde ndan nden yım yim yum yüm sın sin sun sün yız yiz yuz yüz "
            "ydı ydi ydu ydü dı di du dü tı ti tu tü mış miş muş müş ymış ymiş sınız siniz ken yken "
            "m n s mız miz muz müz nız niz nuz nüz"
        ).split()
    ),
    key=len,
    reverse=True,
)
_POSSESSIVE_1SG = frozenset({"m", "im", "um", "mız", "miz", "muz", "imiz", "umuz"})
_PERSONAL_SUFFIXES = frozenset(ascii_fold("yım yim yum yüm ım im um üm sın sin sun sün yız yiz yuz yüz sınız siniz m").split())


@lru_cache(maxsize=8192)
def _parse(sfx: str) -> tuple[str, ...] | None:
    if not sfx:
        return ()
    best: tuple[str, ...] | None = None

    def rec(i: int, acc: tuple[str, ...]) -> None:
        nonlocal best
        if best is not None:
            return
        if i == len(sfx):
            best = acc
            return
        if len(acc) >= 4:
            return
        for f in _SUFFIX_FORMS:
            if sfx.startswith(f, i):
                rec(i + len(f), acc + (f,))

    rec(0, ())
    return best


_BIND_ENTITIES = frozenset(
    {"KISI", "TCKN", "TELEFON", "EPOSTA", "HESAP_NO", "MUSTERI_NO", "PASAPORT", "SGK", "IBAN", "KART", "DOGUM_TARIHI", "ADRES", "VKN"}
)
_MARKERS = fre(
    rf"(?<![{_LOW}])(?:ben|benim|arayan|aranan|görüşülen|bana|beni|bende|sen|senin|sana|seni|siz|sizin|size|biz|bizim|kendisi|kendim|"
    rf"müşteri|müşterimiz|müşterinin|hasta|hastamız|hastanın|çalışan|çalışanımız|çalışanın|personel|personelimiz|"
    rf"adlı|isimli|sigortalı|sigortalımız|başvuran|eşim|eşi|annem|babam|oğlum|kızım|kardeşim|ağabeyim|ablam|"
    rf"danışan|danışanımız|aday|adayın|öğrenci|kullanıcı|kullanıcımız|üye|üyemiz)(?![{_LOW}])"
)
# 1./2. tekil-çoğul şahıs fiil ekleri ("kullanıyorum", "oldum") kişiye bağlılık işaretidir
_PERSON_VERB = fre(r"(?<![a-z])[a-z]{2,}(?:iyorum|iyoruz|iyorsun|iyorsunuz|uyorum|uyoruz|yorum|yoruz|dim|dum|tim|tum)(?![a-z])")
# form/kayıt alanı etiketi + değer: kişi kaydının alanıdır → kişiye bağlı sayılır, değer (alan etiketi hariç) maskelenir
_FIELD_WORD = r"(?:alanı|hanesi|bilgisi|bilgim|durumu|durumum)"
_FIELD_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    # (a) etiket + alan sözcüğü veya iki nokta: "etnik köken alanı X", "din hanesi X", "sendika bilgisi X", "Din: X"
    # (b) kendi başına kişisel alan olan biçimler: "adli kaydı X", "sağlık raporumda X", "dinim X", "engel durumu X"
    (ent, fre(rf"(?<![a-z])(?:(?:{lab})\s*(?:{_FIELD_WORD}\s*[:=]?|[:=])|(?P<self>{self_lab}))\s+"))
    for ent, lab, self_lab in (
        ("OZEL_ETNIK", r"etnik köken|köken", r"etnik kökenim|etnik kökeni"),
        ("OZEL_DIN", r"din|mezhep|inanç", r"dinim|mezhebim"),
        ("OZEL_SAGLIK", r"engel|sağlık|kronik hastalık", r"sağlık raporumda|sağlık raporunda|engel durumu|engel durumum"),
        ("OZEL_CEZA", r"adli sicil|sabıka", r"adli kaydı|adli kaydım|adli sicil kaydı|adli sicil belgemde|adli sicil belgesinde|sabıka kaydı"),
        ("OZEL_UYELIK", r"sendika|dernek", r"sendika bilgisi|sendika üyeliği"),
        ("OZEL_SIYASI", r"siyasi görüş|parti", r"siyasi görüşü|siyasi görüşüm"),
        ("OZEL_CINSEL", r"cinsel yönelim", r"cinsel yönelimi|cinsel yönelimim"),
        ("OZEL_BIYOMETRIK", r"biyometrik", r"biyometrik girişte|biyometrik verim"),
    )
)
_FIELD_VALUE_END = re.compile(r"[,.;\n]|\s(?:ve|ama|fakat|ayrıca|bu|işe|olarak|yazılmış|yazıyor|ibaresi|mevcut|var|yok|görünüyor|eşleşmiyor)\b")
_SELF_STOP = frozenset("belgesi bulundugundan bulunmadigindan bulunuyor bulunmuyor var yok temiz oldugu olmadigi "
                       "oldugundan nedeniyle sebebiyle icin ile de da".split())
_CONVERB = re.compile(r"^[a-z]+(?:digindan|dugundan|tigindan|tugundan|diginden|dugunden|masi|mesi|arak|erek|ken|inca|ince|unca|unce)$")
_QUESTION_WORDS = frozenset("nasil ne nedir neden nereden nerede hangi kim icin ile de da mi mu nasildir alinir".split())
_VERB_LIKE = re.compile(r"^[a-z]+(?:ir|ur|ar|er|yor|di|du|ti|tu|dir|dur|tir|tur|mektedir|maktadir|mistir|mustur|dim|dum)$")
_UNION_NAME = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])[A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü]{0,30}(?:[\- ][A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü]{0,30}){0,3}-(?:Sen|SEN|İş|İŞ|Is)\b(?:\s+(?:sendikası|SENDİKASI))?\s+(?:üyesi|ÜYESİ|üyeyim|üyeliği)")

_UNION_LEAD_STOP = frozenset({"ben", "biz", "sen", "siz", "o", "benim", "bizim", "müşterimiz", "müşteri", "eşim", "annem", "babam"})
_ORG_MEMBER = re.compile(
    r"(?<![\wÇĞİÖŞÜçğıöşü])(?:[A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü]{1,30}\s){1,3}(?:Vakfı|Derneği|Barosu|Odası|Kulübü|Sendikası|Platformu)"
    r"\s+(?:üyesi|üyeyim|üyesiyim|üyeliği)"
)
_ORIGIN_CTX = fre(rf"^['’]?[{_LOW}]*\s*(?:kökenli|asıllı|kökenliyim|asıllıyım|kökenlidir|asıllıdır)")
_MY_BLOOD = fre(r"kan grub(?:um|umuz|unuz)\s*[:=]?\s*$")
_BLOOD_RE = re.compile(r"(?<![A-Za-z0-9])(?:AB|A|B|0|O)\s?(?:Rh|RH|rh)\s?(?:\+|-|pozitif|negatif)", re.ASCII)


class SpecialCategoryRecognizer(Recognizer):
    name = "special_category"
    phase = 2
    entities = tuple(data.SPECIAL_FILES.values())

    def __init__(self) -> None:
        terms = data.special_terms()
        self.words = data.tr_words()
        self.by_key: dict[str, list[data.SpecialTerm]] = {}
        for t in terms:
            self.by_key.setdefault(ascii_fold(" ".join(t.key.split())), []).append(t)
        pat = trie_pattern(self.by_key)
        self.rx = fre(rf"(?<![{_LOW}0-9])(?P<t>{pat})(?P<apos>['’]?)(?P<s>[{_LOW}]*)")

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        cf = ctx.casefolded
        out: list[Span] = []
        for m in self.rx.finditer(cf):
            key = " ".join(m["t"].split())
            sfx = m["s"]
            parsed = _parse(sfx)
            if parsed is None:
                continue
            s = m.start("t")
            e = m.end()
            raw = text[s : m.end("t")]
            for term in self.by_key.get(key, []):
                # katlama çakışmasını önle: "hacim" ≠ "hacı"+"m". Orijinal yazım terimle uyumlu olmalı.
                if not _spelling_ok(raw, " ".join(term.key.split()), len(key)):
                    continue
                if term.must_capitalize and not text[s].isupper():
                    continue
                sent_start = term.must_capitalize and is_sentence_start(text, s)
                if sfx and not m["apos"] and fold_key(key + sfx) in self.words and fold_key(key) not in self.words:
                    continue  # "Lazım", "Romantik" gibi kendi başına sık sözcük olan biçimler
                if term.needs_origin_context and not _ORIGIN_CTX.match(cf[m.end("t") : m.end("t") + 30]):
                    continue
                if term.entity == "OZEL_ETNIK" and sfx in ("ca", "ce"):
                    continue  # "Kürtçe", "Lazca": dil adı, etnik köken bilgisi değil
                personal = bool(parsed) and (
                    (parsed[-1] in _PERSONAL_SUFFIXES and (len(parsed[-1]) >= 2 or bool(m["apos"])))
                    or any(p in _POSSESSIVE_1SG for p in parsed[:-1])
                )
                # cümle başında büyük harf bilgi taşımaz ("Roman okudum") → yalnız güçlü bağ (kişi span'i/işaretçi)
                if not personal and not self._bound(ctx, s, e, verbs=not sent_start):
                    continue
                s2, e2 = _extend(cf, s, e, term.entity)
                out.append(Span(s2, e2, term.entity, text[s2:e2], 0.8, self.name, cf[s2:e2]))
                break
        for ent, rx in _FIELD_RULES:
            if self.cfg_action(ctx, ent) == "IGNORE":
                continue
            for m in rx.finditer(cf):
                vs = m.end()
                end_m = _FIELD_VALUE_END.search(cf, vs, min(len(cf), vs + 60))
                ve = end_m.start() if end_m else min(len(cf), vs + 40)
                while ve > vs and not text[ve - 1].isalnum():
                    ve -= 1
                first_word = cf[vs:ve].split(" ", 1)[0]
                if m["self"]:
                    # "adli sicil kaydı X" biçimi etiketsizdir: kişiye bağlı olmalı ("…belgesi e-Devlet'ten alınır" değil)
                    if not self._bound(ctx, m.start(), vs):
                        continue
                    if first_word in _SELF_STOP or _VERB_LIKE.match(first_word) or _CONVERB.match(first_word):
                        s2, e2 = m.start("self"), m.end("self")  # değer yok: ifadenin kendisi özel nitelikli bilgidir
                        out.append(Span(s2, e2, ent, text[s2:e2], 0.75, self.name, cf[s2:e2]))
                        continue
                if ve - vs >= 2 and first_word not in _QUESTION_WORDS and not _VERB_LIKE.match(first_word):
                    out.append(Span(vs, ve, ent, text[vs:ve], 0.75, self.name, cf[vs:ve]))
        for m in _ORG_MEMBER.finditer(text):  # "TEMA Vakfı üyesi", "Ankara Barosu üyesi" (kişiye bağlı)
            s, e = m.start(), m.end()
            # önündeki kişi adı span'e girmesin ("Hüseyin Kılıç TEMA Vakfı üyesi")
            s = max([s] + [sp.end for sp in ctx.prior_spans if sp.entity == "KISI" and sp.start < e and sp.end > s])
            while s < e and text[s].isspace():
                s += 1
            if e - s > 8 and self._bound(ctx, m.start(), e):
                out.append(Span(s, e, "OZEL_UYELIK", text[s:e], 0.8, self.name, ascii_fold(text[s:e].lower())))
        for m in _UNION_NAME.finditer(text):
            s, e = m.start(), m.end()
            # regex önündeki kişi adını da yutabilir ("Ahmet Yılmaz Türk-İş üyesi") → kişi span'inden sonra başlat
            kisi_end = max((sp.end for sp in ctx.prior_spans if sp.entity == "KISI" and sp.start < e and sp.end > s), default=s)
            s = max(s, kisi_end)
            while s < e and text[s].isspace():
                s += 1
            first = text[s:e].split(" ", 1)[0]
            if first.lower() in _UNION_LEAD_STOP and " " in text[s:e]:  # "Ben Türk-İş üyesiyim" → zamir span'e girmez
                s += len(first) + 1
            if e - s < 3:
                continue
            out.append(Span(s, e, "OZEL_UYELIK", text[s:e], 0.8, self.name, ascii_fold(text[s:e].lower())))
        for m in _BLOOD_RE.finditer(text):
            if self._bound(ctx, m.start(), m.end()) or _MY_BLOOD.search(ctx.casefolded[max(0, m.start() - 15) : m.start()]):
                out.append(Span(m.start(), m.end(), "OZEL_SAGLIK", m.group(), 0.85, self.name, m.group().upper().replace(" ", "")))
        return _merge_adjacent(text, out)

    @staticmethod
    def cfg_action(ctx: AnalysisContext, entity: str) -> str:
        return ctx.cfg.action(entity)

    def _bound(self, ctx: AnalysisContext, s: int, e: int, verbs: bool = True) -> bool:
        ss, se = ctx.sentence_of(s)
        lo, hi = max(ss, s - 200), min(se, e + 200)
        if ctx.prior_in(lo, hi, _BIND_ENTITIES):
            return True
        cf = ctx.casefolded
        for rx in (_MARKERS, _PERSON_VERB) if verbs else (_MARKERS,):
            for m in rx.finditer(cf, lo, hi):
                if m.end() <= s or m.start() >= e:
                    return True
        return False


# terimi tamamlayan sözcükler: "kemoterapi tedavisi", "HIV pozitif", "CHP üyesi", "parmak izi verisi" (ASCII katlanmış)
_CONTINUATION = frozenset(
    ascii_fold(
        "tedavisi tedavi tedavisinde testi test sonucu sonuçları analizi analiz verisi verileri şablonu kaydı kaydında "
        "pozitif negatif üyesi üyeliği yöneticisi adayı ameliyatı ameliyat raporu raporlu mahkumiyeti mahkûmiyeti "
        "davası davasında tanısı teşhisi ilacı ilaçları hastası hastasıdır hastasıyım taşıyıcısı mutasyonu geçmişi disease hastalığı"
    ).split()
)
_CONTINUATION_PAIRS = frozenset({("il", "yoneticisi"), ("ilce", "yoneticisi"), ("meclis", "uyesi"), ("analiz", "sonucu"),
                                 ("gen", "testi"), ("tedavi", "goruyor"),
                                 # hepatit B/C taşıyıcısı (genetik değil, sağlık)
                                 ("b", "tasiyicisi"), ("c", "tasiyicisi"), ("b", "pozitif"), ("c", "pozitif"),
                                 ("b", "virusu"), ("c", "virusu")})
_HEALTH_PREMODIFIERS = frozenset(
    ascii_fold("kalp böbrek karaciğer görme işitme akciğer beyin göz kemik ruh sinir mide bağırsak tiroid omurga diz bel").split()
)
_WORD_AT = re.compile(r"\s+([a-z0-9]+)")


def _extend(cf: str, s: int, e: int, entity: str) -> tuple[int, int]:
    """Span'i tamamlayıcı sözcüklerle (sağda en fazla 2) ve sağlık için organ/duyu niteleyicisiyle (solda) genişletir."""
    for _ in range(2):
        m = _WORD_AT.match(cf, e)
        if not m:
            break
        w = m.group(1)
        if w in _CONTINUATION:
            e = m.end()
            continue
        m2 = _WORD_AT.match(cf, m.end())
        if m2 and (w, m2.group(1)) in _CONTINUATION_PAIRS:
            e = m2.end()
            continue
        break
    if entity == "OZEL_SAGLIK":
        pm = re.search(r"([a-z]+)\s+$", cf[max(0, s - 20) : s])
        if pm and pm.group(1) in _HEALTH_PREMODIFIERS:
            s = s - len(pm.group(0))
    return s, e


def _spelling_ok(raw: str, term_key: str, n_letters: int) -> bool:
    """Katlanmış eşleşmenin orijinal yazımla uyumu.

    Kabul: harf aynı (Türkçe küçük harfte) | büyük ASCII 'I' terimde 'i' (HIV) |
    metin tamamen ASCII yazılmış ve terim ≥5 harf (klavyesi Türkçe olmayan kullanıcı: "sabikali").
    """
    if len(raw) != len(term_key):
        return False
    low = tr_lower(raw)
    ascii_typed = raw.isascii() and n_letters >= 5
    for rc, lc, tc in zip(raw, low, term_key, strict=True):
        if lc == tc or (lc.isspace() and tc.isspace()):
            continue
        if rc == "I" and tc == "i":
            continue
        if ascii_typed and ascii_fold(tc) == lc:
            continue
        return False
    return True


def _merge_adjacent(text: str, spans: list[Span]) -> list[Span]:
    """Aynı kategoride, aralarında yalnız boşluk/virgül olan terimleri tek span'de birleştirir
    ("diyabet hastasıdır" → tek yer tutucu)."""
    spans = sorted(spans, key=lambda s: (s.start, -s.end))
    out: list[Span] = []
    for sp in spans:
        if out:
            prev = out[-1]
            if sp.start < prev.end:
                if sp.end > prev.end and sp.entity == prev.entity:
                    out[-1] = Span(prev.start, sp.end, prev.entity, text[prev.start : sp.end], max(prev.score, sp.score), prev.recognizer, prev.normalized + " " + sp.normalized)
                continue
            gap = text[prev.end : sp.start]
            if sp.entity == prev.entity and len(gap) <= 2 and gap.strip(" ") == "":
                out[-1] = Span(prev.start, sp.end, prev.entity, text[prev.start : sp.end], max(prev.score, sp.score), prev.recognizer, prev.normalized + " " + sp.normalized)
                continue
        out.append(sp)
    return out
