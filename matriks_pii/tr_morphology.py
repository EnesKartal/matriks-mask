"""Türkçe isim çekim eklerinin ayrıştırılması ve ünlü uyumuna göre onarımı.

* `strip_suffixes("Ahmetin")` → ["Ahmet", ...] — bitişik yazılmış ekli adların kökünü bulmak için.
* `repair_suffix("Ayşe", "e")` → "ye" — yer tutucu geri çevrilirken LLM'in yer tutucuya göre çektiği
  eki, gerçek değere göre düzeltmek için ("<KISI_1>'e" → "Ayşe'ye").
"""

from __future__ import annotations

import re
from functools import lru_cache

from .text_utils import fold_key, tr_lower, tr_upper

BACK_VOWELS = frozenset("aıouâû")
FRONT_VOWELS = frozenset("eiöüî")
VOWELS = BACK_VOWELS | FRONT_VOWELS
HARD_CONSONANTS = frozenset("çfhkpsşt")

# yüzey biçimi → sınıf (uzun olanlar önce denenir)
_MORPHEMES: dict[str, str] = {}
for _cls, _forms in {
    "GEN": "nın nin nun nün ın in un ün",
    "DAT": "ya ye a e",
    "ACC": "yı yi yu yü ı i u ü",
    "LOC": "da de ta te",
    "ABL": "dan den tan ten",
    "INS": "yla yle la le",
    "PLU": "lar ler",
    "KI": "ki",
    "COP": "dır dir dur dür tır tir tur tür",
    "P1S": "ım im um üm",
    "P1P": "ımız imiz umuz ümüz",
    "P2P": "ınız iniz unuz ünüz",
    "EQU": "ca ce ça çe",
    "P3S": "sı si su sü",  # 3. tekil iyelik, ünlüyle biten kök ("Ayşe'si"); ünsüzden sonra ACC ile aynı yüzey
    "ACC_N": "nı ni nu nü",  # -ki sonrası belirtme ("Ahmet'tekini")
    "PAST": "ydı ydi ydu ydü dı di du dü tı ti tu tü",  # geçmiş zaman kopulası ("Ahmet'ti", "Ali'ydi")
    "EVID": "ymış ymiş ymuş ymüş mış miş muş müş",  # rivayet kopulası ("Ali'ymiş")
    # sevgi/küçültme + 1. tekil iyelik ("Ayşecim", "Ahmetçiğim")
    "DIM1": "cim cım cum cüm çim çım çum çüm",
    "DIM2": "ciğim cığım cuğum cüğüm çiğim çığım çuğum çüğüm",
}.items():
    for _f in _forms.split():
        _MORPHEMES[_f] = _cls

_FORMS_BY_LEN = sorted(_MORPHEMES, key=len, reverse=True)
_FORM_SET = frozenset(_MORPHEMES)
_FORM_LENS = sorted({len(f) for f in _MORPHEMES}, reverse=True)


# Damak l'si ile biten (son hecesi ince okunan) adlar: ek ince ünlü alır (TDK: alkolü, helalimiz → Kemal'e, Celal'i)
_FRONT_L_STEMS = frozenset(
    fold_key(x) for x in "kemal celal cemal bilal hilal nihal ikbal iclal zulal meral hayal resul rasul emsal kemâl celâl".split()
)


def last_vowel(word: str) -> str | None:
    words = word.split()
    if words and fold_key(re.sub(r"[^\w]", "", words[-1])) in _FRONT_L_STEMS:
        return "e"
    for c in reversed(tr_lower(word)):
        if c in VOWELS:
            # şapkalı ünlü inceliği gösterir (hâl, usûl): ek ince ünlü alır
            return {"â": "e", "î": "i", "û": "ü"}.get(c, c)
    return None


def _v2(word: str) -> str:
    lv = last_vowel(word)
    return "a" if lv is None or lv in BACK_VOWELS else "e"


def _v4(word: str) -> str:
    lv = last_vowel(word) or "e"
    return {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}.get(lv, "i")


def _ends_vowel(word: str) -> bool:
    return bool(word) and tr_lower(word[-1]) in VOWELS


def _ends_hard(word: str) -> bool:
    return bool(word) and tr_lower(word[-1]) in HARD_CONSONANTS


def generate(cls: str, stem: str) -> str:
    """`stem` sonuna gelecek `cls` ekinin doğru yüzey biçimi."""
    v2, v4 = _v2(stem), _v4(stem)
    vowel_end = _ends_vowel(stem)
    hard = _ends_hard(stem)
    if cls == "GEN":
        return ("n" + v4 + "n") if vowel_end else (v4 + "n")
    if cls == "DAT":
        return ("y" + v2) if vowel_end else v2
    if cls == "ACC":
        return ("y" + v4) if vowel_end else v4
    if cls == "LOC":
        return ("t" if hard else "d") + v2
    if cls == "ABL":
        return ("t" if hard else "d") + v2 + "n"
    if cls == "INS":
        return ("yl" + v2) if vowel_end else ("l" + v2)
    if cls == "PLU":
        return "l" + v2 + "r"
    if cls == "KI":
        return "ki"
    if cls == "COP":
        return ("t" if hard else "d") + v4 + "r"
    if cls == "P1S":
        return "m" if vowel_end else v4 + "m"
    if cls == "P1P":
        return ("m" + v4 + "z") if vowel_end else (v4 + "m" + v4 + "z")
    if cls == "P2P":
        return ("n" + v4 + "z") if vowel_end else (v4 + "n" + v4 + "z")
    if cls == "EQU":
        return ("ç" if hard else "c") + v2
    if cls == "P3S":
        return ("s" + v4) if vowel_end else v4
    if cls == "ACC_N":
        return "n" + v4
    if cls == "PAST":
        return ("yd" + v4) if vowel_end else (("t" if hard else "d") + v4)
    if cls == "EVID":
        return (("ym" if vowel_end else "m") + v4) + "ş"
    if cls == "DIM1":
        return ("ç" if hard else "c") + v4 + "m"
    if cls == "DIM2":
        return ("ç" if hard else "c") + v4 + "ğ" + v4 + "m"
    raise ValueError(cls)


@lru_cache(maxsize=4096)
def parse_suffix(suffix: str) -> tuple[str, ...] | None:
    """Ek dizisini morfem sınıflarına ayırır; tamamı ayrıştırılamazsa None."""
    s = tr_lower(suffix)
    if not s:
        return ()

    best: tuple[str, ...] | None = None

    def rec(i: int, acc: tuple[str, ...]) -> None:
        nonlocal best
        if best is not None and len(acc) >= len(best):
            return
        if i == len(s):
            best = acc
            return
        if len(acc) >= 3:
            return
        for f in _FORMS_BY_LEN:
            if s.startswith(f, i):
                rec(i + len(f), acc + (_MORPHEMES[f],))

    rec(0, ())
    return best


def _all_upper(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _match_case(template: str, out: str, word: str = "") -> str:
    """Ek, DEĞERİN harf büyüklüğünü izler: "AHMET" + in → "İN"; "Ayşe Demir" + "İN" → "in"."""
    if _all_upper(word) or (not word and _all_upper(template)):
        return tr_upper(out)
    return out


_UNITS = ("sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_TENS = {"1": "on", "2": "yirmi", "3": "otuz", "4": "kırk", "5": "elli", "6": "altmış", "7": "yetmiş", "8": "seksen", "9": "doksan"}
_TRAIL_NUM = re.compile(r"[0-9]+$")


def _digit_stem(word: str) -> str | None:
    """Rakamla biten değerin son sayısının okunuşu ("No: 6" → altı, 100 → yüz, 17291716060 → altmış)."""
    m = _TRAIL_NUM.search(word)
    if m is None:
        return None
    num = m.group()
    if len(num) >= 7 and num.endswith("000000"):
        return "milyon"
    if len(num) >= 4 and num.endswith("000"):
        return "bin"
    if len(num) >= 3 and num.endswith("00"):
        return "yüz"
    if len(num) >= 2 and num.endswith("0"):
        return _TENS[num[-2]]
    return _UNITS[int(num[-1])]


def repair_suffix(word: str, suffix: str) -> str:
    """`word` + `suffix` için ünlü uyumu/ünsüz benzeşmesi/kaynaştırma harfi doğru eki döner.

    Ayrıştırılamayan ek aynen döner. Rakamla biten değerde son sayının okunuşu esas alınır ("No: 6'da", "100'de");
    harf/rakam dışıyla biten (kısaltma noktası, parantez) değerde ek aynen döner.
    """
    if not word or not suffix:
        return suffix
    stem_word = word if word[-1].isalpha() else _digit_stem(word) if word[-1].isdigit() else None
    if stem_word is None:
        return suffix
    classes = parse_suffix(suffix)
    if not classes:
        return suffix
    stem = stem_word
    out = ""
    for cls in classes:
        piece = generate(cls, stem)
        out += piece
        stem = stem + piece
    # rakamla biten değerde ("TR33 … 26", "No: 6") büyüklük değerden değil ekten izlenir
    return _match_case(suffix, out, word if word[-1].isalpha() else "")


_SOFT_TO_HARD = {"d": "t", "b": "p", "c": "ç", "ğ": "k"}


def strip_suffixes(token: str, max_layers: int = 2) -> tuple[str, ...]:
    """Bitişik eklerin soyulmasıyla elde edilen olası kökler (uzundan kısaya).

    Kök en az 2 harf olmalı. Ünsüz yumuşaması (Ahmed-e → Ahmet) için sert karşılık da eklenir.
    """
    results: list[str] = []
    low = tr_lower(token)

    def rec(stem_low: str, stem_orig: str, depth: int) -> None:
        if depth == max_layers:
            return
        for k in _FORM_LENS:  # uzundan kısaya; aynı uzunlukta en fazla bir biçim sona uyabilir
            if len(stem_low) - k >= 2 and stem_low[-k:] in _FORM_SET:
                n_low = stem_low[:-k]
                n_orig = stem_orig[:-k]
                if n_orig not in results:
                    results.append(n_orig)
                last = n_low[-1]
                if last in _SOFT_TO_HARD:
                    hard = n_orig[:-1] + (_SOFT_TO_HARD[last] if n_orig[-1].islower() else _SOFT_TO_HARD[last].upper())
                    if hard not in results:
                        results.append(hard)
                rec(n_low, n_orig, depth + 1)

    rec(low, token, 0)
    return tuple(results)
