"""Paketlenmiş sözlüklerin tembel, önbellekli yükleyicileri."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..text_utils import fold_key, tr_casefold

DATA_DIR = Path(__file__).resolve().parent

SPECIAL_FILES: dict[str, str] = {
    "saglik": "OZEL_SAGLIK",
    "genetik": "OZEL_GENETIK",
    "biyometrik": "OZEL_BIYOMETRIK",
    "cinsel": "OZEL_CINSEL",
    "ceza": "OZEL_CEZA",
    "ceza_genis": "OZEL_CEZA_GENIS",
    "din": "OZEL_DIN",
    "etnik": "OZEL_ETNIK",
    "siyasi": "OZEL_SIYASI",
    "felsefi": "OZEL_FELSEFI",
    "kiyafet": "OZEL_KIYAFET",
    "uyelik": "OZEL_UYELIK",
}


def _lines(name: str) -> list[str]:
    p = DATA_DIR / name
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


@lru_cache(maxsize=1)
def first_names() -> frozenset[str]:
    return frozenset(fold_key(x) for x in _lines("first_names_tr.txt"))


# tr_words.txt'nin ilk COMMON_WORD_RANK girdisi "sık sözcük" sayılır (kaynak listenin ilk 30.000 satırına karşılık gelir).
COMMON_WORD_RANK = 29098

# Ad listeleri (trnames, MIT) ile sözcük listesinin (tr_words.txt, CC BY-SA 4.0) kesişimine dayanan seçimler
# paketle dağıtılmaz; burada, çalışma anında hesaplanır. Böylece paketteki ad ve sözcük-ad dosyaları sözcük
# listesinden türetilmiş bir seçim içermez.


@lru_cache(maxsize=1)
def _all_last_names() -> frozenset[str]:
    return frozenset(fold_key(x) for x in _lines("last_names_tr.txt"))


@lru_cache(maxsize=1)
def continuation_last_names() -> frozenset[str]:
    """Yalnız bir adın ardından soyad olarak kabul edilen sözcük-soyadlar (Arı, Sağlam, Uzun).

    Seyrek soyad (sık soyadlar listesinde yok) olup aynı zamanda Türkçe sözcük olanlar.
    """
    frequent = frozenset(fold_key(x) for x in _lines("frequent_last_names_tr.txt"))
    words = tr_words()
    return frozenset(n for n in _all_last_names() if n not in frequent and n in words)


@lru_cache(maxsize=1)
def last_names() -> frozenset[str]:
    """Tek başına soyad sayılan adlar (sözcük-soyadlar hariç; onlar `continuation_last_names`)."""
    return _all_last_names() - continuation_last_names()


@lru_cache(maxsize=1)
def rare_word_first_names() -> frozenset[str]:
    """Seyrek ad olup aynı zamanda Türkçe sözcük olanlar (Telefon, Hacim...)."""
    frequent = frozenset(fold_key(x) for x in _lines("frequent_first_names_tr.txt"))
    words = tr_words()
    return frozenset(n for n in first_names() if n not in frequent and n in words)


@lru_cache(maxsize=1)
def common_words() -> dict[str, str]:
    """sözcük → 'weak' | 'strong'.

    Dosyadaki elle derlenmiş girdilere ek olarak "strong": seyrek ad + sözcük olanlar ve ad/soyad olup en sık
    COMMON_WORD_RANK sözcük arasında yer alanlar. `exclude` satırları, popüler adlar ve weak girdiler bunlara eklenmez.
    """
    out: dict[str, str] = {}
    exclude: set[str] = set()
    for ln in _lines("common_words_tr.txt"):
        w, _, kind = ln.partition("\t")
        kind = kind.strip() or "weak"
        if kind == "exclude":
            exclude.add(fold_key(w))
        else:
            out[fold_key(w)] = kind
    names = first_names() | last_names()
    frequent_words = set(_tr_words_ordered()[:COMMON_WORD_RANK])
    skip = exclude | popular_first_names() | {w for w, k in out.items() if k == "weak"}
    for w in sorted((rare_word_first_names() | (names & frequent_words)) - skip):
        out.setdefault(w, "strong")
    return out


@lru_cache(maxsize=1)
def _tr_words_ordered() -> tuple[str, ...]:
    return tuple(_lines("tr_words.txt"))


@lru_cache(maxsize=1)
def tr_words() -> frozenset[str]:
    return frozenset(_tr_words_ordered())


@lru_cache(maxsize=1)
def popular_first_names() -> frozenset[str]:
    return frozenset(_lines("popular_first_names_tr.txt"))


@lru_cache(maxsize=1)
def honorifics() -> tuple[frozenset[str], frozenset[str]]:
    pre: set[str] = set()
    post: set[str] = set()
    for ln in _lines("honorifics_tr.txt"):
        kind, term = ln.split("\t", 1)
        (pre if kind == "pre" else post).add(fold_key(term.strip().rstrip(".")))
    return frozenset(pre), frozenset(post)


@lru_cache(maxsize=1)
def org_suffixes() -> frozenset[str]:
    return frozenset(fold_key(x) for x in _lines("org_suffixes_tr.txt"))


@lru_cache(maxsize=1)
def org_names() -> tuple[str, ...]:
    return tuple(sorted({fold_key(x) for x in _lines("org_names_tr.txt")}, key=len, reverse=True))


@dataclass(frozen=True)
class Geo:
    provinces: frozenset[str]
    districts: frozenset[str]
    neighborhoods: frozenset[str]
    semtler: frozenset[str]
    postal_codes: frozenset[str]
    province_display: tuple[str, ...]
    places_tr: frozenset[str] = frozenset()  # il/ilçe/semt adları Türkçe küçük harf (katlamasız: "çan" ≠ "can")

    def is_province_or_district(self, key: str) -> bool:
        return key in self.provinces or key in self.districts

    def is_place(self, key: str) -> bool:
        return key in self.provinces or key in self.districts or key in self.neighborhoods or key in self.semtler


@lru_cache(maxsize=1)
def geo() -> Geo:
    d = json.loads((DATA_DIR / "il_ilce_tr.json").read_text(encoding="utf-8"))
    prov, dist, pcs = set(), set(), set()
    for il in d["iller"]:
        prov.add(fold_key(il["ad"]))
        for ilce in il["ilceler"]:
            dist.add(fold_key(ilce))
        pcs.update(il["posta_kodlari"])
    return Geo(
        provinces=frozenset(prov),
        districts=frozenset(dist),
        neighborhoods=frozenset(d.get("mahalleler", [])),
        semtler=frozenset(fold_key(s) for s in d.get("semtler", [])),
        postal_codes=frozenset(pcs),
        province_display=tuple(il["ad"] for il in d["iller"]),
        places_tr=frozenset(
            tr_casefold(x)
            for il in d["iller"]
            for x in [il["ad"], *il["ilceler"]]
        ) | frozenset(tr_casefold(x) for x in d.get("semtler", [])),
    )


@dataclass(frozen=True)
class SpecialTerm:
    entity: str
    term: str  # orijinal yazım
    key: str  # tr_lower
    must_capitalize: bool
    needs_origin_context: bool


@lru_cache(maxsize=1)
def special_terms() -> tuple[SpecialTerm, ...]:
    out: list[SpecialTerm] = []
    for fname, entity in SPECIAL_FILES.items():
        for ln in _lines(f"special_category/{fname}.txt"):
            cap = ln.startswith("!")
            ctx = ln.startswith("?")
            term = ln.lstrip("!?").strip()
            from ..text_utils import tr_lower

            out.append(SpecialTerm(entity, term, tr_lower(term), cap or ctx, ctx))
    return tuple(out)
