"""Türkçe'ye duyarlı metin yardımcıları.

Kural: metin asla normalize edilip yerine konmaz; bütün offset'ler orijinal string üzerindedir.
`tr_lower` uzunluk korur (İ→i, I→ı); bağlam aramaları bu küçük harfli kopya üzerinde yapılır.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

APOS_CHARS = "'’ʼ`"
APOS = "['’ʼ`]"

_ASCII_FOLD = str.maketrans(
    {
        "İ": "I",
        "ı": "i",
        "Ş": "S",
        "ş": "s",
        "Ğ": "G",
        "ğ": "g",
        "Ü": "U",
        "ü": "u",
        "Ö": "O",
        "ö": "o",
        "Ç": "C",
        "ç": "c",
        "Â": "A",
        "â": "a",
        "Î": "I",
        "î": "i",
        "Û": "U",
        "û": "u",
    }
)

TR_UPPER_LETTERS = "ABCÇDEFGĞHIİJKLMNOÖPQRSŞTUÜVWXYZÂÎÛ"
TR_LOWER_LETTERS = "abcçdefgğhıijklmnoöpqrsştuüvwxyzâîû"


_FULLWIDTH = {cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)}  # ！..～ → !..~ (rakam, Latin harf, noktalama)
_FULLWIDTH[0x3000] = 0x20  # ideografik boşluk
_FW_RE = re.compile("[\uff01-\uff5e\u3000]")


def ascii_width(s: str) -> str:
    """Tam genişlik (U+FF01–FF5E) karakterleri ASCII karşılığına çevirir; uzunluk korunur.

    Kullanıcı ya da kopyala-yapıştır "１７２９…" gibi tam genişlik rakam getirebilir (maskeleme atlatma)."""
    return s.translate(_FULLWIDTH) if _FW_RE.search(s) else s


def tr_lower(s: str) -> str:
    """Türkçe küçük harf; uzunluk korunur (str.lower 'İ' için iki karakter üretir)."""
    out = s.replace("İ", "i").replace("I", "ı").lower()
    if len(out) != len(s):  # nadir: başka bir genişleyen karakter (ör. ẞ) — karakter karakter düşür
        out = "".join(c if len(tr_lower_char(c)) != 1 else tr_lower_char(c) for c in s)
    return out


def tr_lower_char(c: str) -> str:
    if c == "İ":
        return "i"
    if c == "I":
        return "ı"
    return c.lower()


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def tr_casefold(s: str) -> str:
    """Anahtar üretimi için: NFC + Türkçe küçük harf (uzunluk korunması gerekmez)."""
    return unicodedata.normalize("NFC", tr_lower(unicodedata.normalize("NFC", s)))


def ascii_fold(s: str) -> str:
    return s.translate(_ASCII_FOLD)


def fold_text(s: str) -> str:
    """Uzunluk korunan arama kopyası: Türkçe küçük harf + ASCII katlama ("İMEİ", "IMEI" → "imei")."""
    return ascii_fold(tr_lower(s))


def fre(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """`fold_text` uygulanmış metinde aranacak deseni derler (desendeki Türkçe harfler de katlanır)."""
    return re.compile(ascii_fold(pattern), flags)


def trie_pattern(words: Iterable[str], space: str = r"\s+") -> str:
    """Sözcük listesinden önek ağacı biçimli regex alternasyonu (düz `a|b|c`'ye göre çok daha hızlı; en uzun eşleşme
    tercih edilir). Sözcük içindeki boşluk `space` desenine çevrilir."""
    trie: dict[str, dict] = {}  # type: ignore[type-arg]
    for w in words:
        if not w:
            continue
        node = trie
        for c in w:
            node = node.setdefault(c, {})
        node[""] = {}

    def emit(node: dict) -> str:  # type: ignore[type-arg]
        end = "" in node
        alts = [(space if c == " " else re.escape(c)) + emit(node[c]) for c in sorted(k for k in node if k)]
        if not alts:
            return ""
        body = alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"
        if end:
            return "(?:" + body + ")?"
        return body

    return emit(trie)


def fold_key(s: str) -> str:
    """Sözlük araması için anahtar: NFC → Türkçe küçük harf → ASCII katlama."""
    return ascii_fold(tr_casefold(s))


def is_title(tok: str) -> bool:
    """İlk harf büyük, kalanlar küçük (Türkçe harflerle)."""
    if not tok or not tok[0].isalpha():
        return False
    return tok[0].isupper() and (len(tok) == 1 or tok[1:] == tr_lower(tok[1:]))


def is_all_upper(tok: str) -> bool:
    letters = [c for c in tok if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def is_capitalized(tok: str) -> bool:
    return is_title(tok) or is_all_upper(tok)


_SENT_BOUNDARY = re.compile(r"[.!?…]+(?=\s|$)[\s\"'’”)\]]*|\n")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Kaba cümle sınırları: [.!?\\n] + boşluk."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_BOUNDARY.finditer(text):
        end = m.end()
        if end > start:
            spans.append((start, end))
        start = end
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def is_sentence_start(text: str, pos: int) -> bool:
    """`pos` cümlenin ilk sözcüğü mü? (Önünde yalnız boşluk/tırnak/madde işareti var.)"""
    i = pos - 1
    while i >= 0 and text[i] in " \t\"'“”‘’«»(-*•>#":
        i -= 1
    if i < 0:
        return True
    c = text[i]
    if c in ".!?\n…:;|":
        # "Dr." gibi kısaltmalardan sonra cümle başı sayma
        if c == ".":
            j = i - 1
            while j >= 0 and text[j].isalpha():
                j -= 1
            word = text[j + 1 : i]
            if word and fold_key(word) in _ABBREV_NOT_SENTENCE_END:
                return False
            if j >= 0 and text[j].isdigit():
                # "12." gibi sıra sayısından sonra devam
                return True
        return True
    return False


_ABBREV_NOT_SENTENCE_END = frozenset(
    {"dr", "av", "prof", "doc", "sn", "ogr", "muh", "uzm", "bkz", "vb", "vs", "no", "mah", "sok", "cad", "apt", "bul", "blv", "mh", "sk", "cd", "st", "yrd", "op", "ecz", "dt", "hz"}
)


def window(text: str, start: int, end: int, size: int) -> tuple[int, int]:
    return max(0, start - size), min(len(text), end + size)


def strip_invisible(s: str) -> str:
    return "".join(c for c in s if unicodedata.category(c) != "Cf")
