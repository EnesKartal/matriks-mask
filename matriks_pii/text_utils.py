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
# web/PDF kopyalarındaki bölünmez ve dar boşluklar ("TR33 0006 …")
for _cp in (0x00A0, *range(0x2002, 0x200B), 0x202F, 0x205F):
    _FULLWIDTH[_cp] = 0x20
_FW_RE = re.compile("[\uff01-\uff5e\u3000\u00a0\u2002-\u200a\u202f\u205f]")
# Unicode tireler ("4111‑1111‑…"): ana taramada EŞLENMEZ (değere bitişik "–" ASCII tire gibi sınırı bozardı:
# "5580…7216–CVV"); ayrı bir ek taramada eşlenir ve sonuç birleştirilir (engine.analyze)
_DASHES = {cp: 0x2D for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2212)}
_DASH_RE = re.compile("[\u2010-\u2013\u2212]")


def ascii_width(s: str) -> str:
    """Tam genişlik (U+FF01–FF5E) karakterleri ve Unicode boşlukları ASCII karşılığına çevirir; uzunluk korunur.

    Kullanıcı ya da kopyala-yapıştır "１７２９…" gibi tam genişlik rakam getirebilir (maskeleme atlatma)."""
    return s.translate(_FULLWIDTH) if _FW_RE.search(s) else s


def ascii_dashes(s: str) -> str | None:
    """Unicode tireleri ASCII "-" yapar (uzunluk korunur); metinde Unicode tire yoksa None."""
    return s.translate(_DASHES) if _DASH_RE.search(s) else None


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


# ------------------------------------------------------------------ URL (%XX) ve HTML varlık çözümü (yalnız tarama kopyası)
_PCT_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_HTML_ENT = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_FORM_PLUS = re.compile(r"(?<=[0-9A-Za-z])\+(?=[0-9A-Za-z])")
_URL_HINT = re.compile(r"://|[?=&]")


_TOKEN = re.compile(r"\S+")


def _url_pct_runs(text: str) -> Iterable[re.Match[str]]:
    """URL/form kodlaması olan `%XX` dizileri. Türkçe yüzde yazımı ("%40 arttı", "(%53)") çözülmez.
    Doğrusal: her boşluksuz parça bir kez taranır (parça içi ipucu ve dizi sayısı parça başına bir kez hesaplanır)."""
    for tm in _TOKEN.finditer(text):
        lo, hi = tm.span()
        if text.find("%", lo, hi) < 0:
            continue
        runs = list(_PCT_RUN.finditer(text, lo, hi))
        if not runs:
            continue
        url_like = len(runs) >= 2 or _URL_HINT.search(text, lo, hi) is not None
        for m in runs:
            if url_like:
                yield m
                continue
            s, e = m.span()
            before = text[s - 1] if s > lo else ""
            after = text[e] if e < hi else ""
            if before and (before.isalnum() or before in "._-+") and after.isalnum():
                yield m


def _decode_once(text: str) -> tuple[str, list[int], list[int]] | None:
    import html

    segs: list[tuple[int, int, list[tuple[str, int, int]]]] = []  # (başlangıç, bitiş, [(karakter, orj_s, orj_e)])
    if "&" in text:
        for m in _HTML_ENT.finditer(text):
            r = html.unescape(m.group())
            if r != m.group() and r:
                segs.append((m.start(), m.end(), [(c, m.start(), m.end()) for c in r]))
    if "%" in text:
        for m in _url_pct_runs(text):
            chars: list[tuple[str, int, int]] = []
            buf = b""
            buf_start = m.start()
            ok = True
            for k in range(m.start(), m.end(), 3):
                if not buf:
                    buf_start = k
                buf += bytes([int(text[k + 1 : k + 3], 16)])
                try:
                    c = buf.decode("utf-8")
                except UnicodeDecodeError:
                    if len(buf) >= 4:
                        ok = False
                        break
                    continue
                chars.extend((ch, buf_start, k + 3) for ch in c)
                buf = b""
            if ok and not buf and chars:
                segs.append((m.start(), m.end(), chars))
    if not segs:
        return None
    segs.sort()
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pos = 0
    for s, e, chars in segs:
        for k in range(pos, s):
            out.append(text[k])
            starts.append(k)
            ends.append(k + 1)
        for ch, cs, ce in chars:
            out.append(ch)
            starts.append(cs)
            ends.append(ce)
        pos = e
    for k in range(pos, len(text)):
        out.append(text[k])
        starts.append(k)
        ends.append(k + 1)
    return "".join(out), starts, ends


def form_plus_spaces(text: str) -> str | None:
    """Form/sorgu parçasında (anahtar=değer) harf/rakam arasındaki "+" → boşluk; uzunluk korunur. Yoksa None.
    Ek tarama olarak kullanılır; asıl taramada "+" korunur ("ayse+banka@gmail.com" e-postası bütün kalır)."""
    if "+" not in text or "=" not in text:
        return None
    chars: list[str] | None = None
    for tm in _TOKEN.finditer(text):
        lo, hi = tm.span()
        if text.find("+", lo, hi) < 0 or text.find("=", lo, hi) < 0:
            continue
        for pm in _FORM_PLUS.finditer(text, lo, hi):
            if chars is None:
                chars = list(text)
            chars[pm.start()] = " "
    return "".join(chars) if chars is not None else None


def decode_for_scan(text: str, max_passes: int = 2) -> tuple[str, list[int], list[int]] | None:
    """URL kodlu (`%40`, `%20`; yalnız URL/form bağlamında) ve HTML varlıklı (`&#64;`, `&amp;`) metnin çözülmüş tarama
    kopyası. Döner: (çözülmüş metin, her karakterin orijinaldeki başlangıcı, bitişi) ya da çözülecek bir şey yoksa None.
    Çift kodlama (`%2540`) için en çok `max_passes` tur. Orijinal metin değiştirilmez; maskeleme orijinal aralığa uygulanır.
    """
    if "%" not in text and "&" not in text:
        return None
    cur = text
    starts = list(range(len(text)))
    ends = list(range(1, len(text) + 1))
    changed = False
    for _ in range(max_passes):
        r = _decode_once(cur)
        if r is None:
            break
        cur, s2, e2 = r
        starts = [starts[i] for i in s2]
        ends = [ends[j - 1] for j in e2]
        changed = True
    return (cur, starts, ends) if changed else None
