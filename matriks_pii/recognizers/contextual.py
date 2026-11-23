"""Bağlam zorunlu kimlikler, doğum tarihi/yeri, extra_regex."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .. import data
from ..text_utils import ascii_fold, fold_key, fre, is_capitalized, tr_lower
from .base import AnalysisContext, Recognizer, Span
from .checksums import luhn_valid, tckn_valid, vkn_valid

_W = r"[a-zçğıöşüâîû]"


def _label(*alts: str) -> str:
    return "(?:" + "|".join(alts) + ")"


@dataclass(frozen=True)
class CtxRule:
    entity: str
    value: re.Pattern[str]
    context: re.Pattern[str]  # casefolded metinde, değerden ÖNCE (pencere içinde) aranır
    score: float
    window: int = 60
    validate: object = None  # Callable[[str], float|None] — skoru döner veya None (reddet)
    ignore_case: bool = True
    after_ok: bool = False  # bağlam değerden sonra da gelebilir


def _mersis_score(v: str) -> float | None:
    # şirket: "0" + 10 haneli VKN + 5 hane; şahıs işletmesi: 11 haneli TCKN ile başlar
    if (v[0] == "0" and vkn_valid(v[1:11])) or vkn_valid(v[:10]) or tckn_valid(v[:11]):
        return 0.9
    return 0.6


def _imei_score(v: str) -> float | None:
    return 0.9 if luhn_valid(v) else None


def _vin_score(v: str) -> float | None:
    return 0.8 if (any(c.isdigit() for c in v) and any(c.isalpha() for c in v)) else None


_UUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"


_ANCHORS: dict[str, tuple[str, ...]] = {}  # bağlam deseni → katlanmış ilk sözcükler (hızlı `in` ön kontrolü)


def _ctx(*words: str) -> re.Pattern[str]:
    # "müşteri no" ~ "musteri_no" ~ "müşteri-no" (JSON/form anahtarları)
    alts = "|".join(w.replace(" ", r"[\s_\-]+") for w in sorted(words, key=len, reverse=True))
    rx = fre(rf"(?<![0-9a-z])(?:{alts})")
    _ANCHORS[rx.pattern] = tuple(sorted({ascii_fold(tr_lower(w.split()[0])) for w in words}))
    return rx


def _num(pat: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-Za-z])(?:{pat})(?![0-9A-Za-z])")


RULES: tuple[CtxRule, ...] = (
    # seri harfi + 7/8 hane; harf sonrası boşluk yalnız BÜYÜK harfte ("U 12345678"; "o 12345678" zamir olabilir)
    CtxRule("PASAPORT", re.compile(r"(?<![0-9A-Za-z])(?:[A-Z] ?|[a-z])[0-9]{7,8}(?![0-9A-Za-z])"), _ctx("pasaport", "passport"), 0.8),
    CtxRule(
        "KIMLIK_SERI",
        re.compile(r"(?<![0-9A-Za-z])(?:[A-Za-z][0-9]{2}[A-Za-z][0-9]{5}|[A-Za-z]{3}[0-9]{6}"
                   r"|[A-Z][0-9]{2} ?[0-9]{6})(?![0-9A-Za-z])"),  # eski nüfus cüzdanı: seri "A07" + no "123456"
        _ctx("seri no", "seri numarası", "seri numaram", "belge no", "kimlik kartı", "cüzdan seri", "nüfus cüzdanı", "cüzdan no"),
        0.7,
    ),
    CtxRule(
        "EHLIYET",
        _num(r"[A-Za-z]?[0-9]{5,7}"),
        _ctx("ehliyet", "sürücü belgesi", "sürücü belge"),
        0.7,
    ),
    # finans/kurumsal kimlikler (SGK "sicil no" bağlamından ÖNCE: "MKK sicil no" SGK değildir)
    CtxRule("MKK_SICIL", _num(r"[0-9]{7,11}"), _ctx("mkk sicil", "mkk no", "mkk", "yatırımcı sicil", "yatirimci sicil"), 0.8,
            window=40),
    CtxRule("POLICE_NO", _num(r"(?:[A-Za-z]{1,5}-)?(?:[0-9]{2,6}[-/])?[0-9]{4,15}|[A-Za-z]{1,4}[0-9]{6,15}"),
            _ctx("poliçe no", "poliçe numarası", "poliçe numaram", "police no", "poliçe"), 0.75, window=40),
    CtxRule("TICARET_SICIL", _num(r"[0-9]{4,8}(?:-[0-9]{1,2})?"), _ctx("ticaret sicil", "sicil müdürlüğü", "ticaret sicili"),
            0.75, window=50),
    CtxRule("ADRES_KODU", _num(r"[0-9]{10}"), _ctx("adres kodu", "uavt", "dask adres", "adres no"), 0.75, window=40),
    CtxRule("SGK", _num(r"[0-9]{26}"), _ctx("işyeri sicil", "iş yeri sicil", "işyeri sgk"), 0.85),
    CtxRule(
        "SGK",
        _num(r"[0-9]{7,13}|[0-9]{4}[ \-][0-9]{4}[ \-][0-9]{4}[ \-][0-9]{1,2}"),
        _ctx("sgk", "sigorta sicil", "sicil no", "sicil numarası", "sicil numaram", "ssk no", "bağ-kur", "bağkur no", "emekli sicil"),
        0.7,
    ),
    CtxRule("MERSIS", _num(r"[0-9]{16}"), _ctx("mersis"), 0.6, validate=_mersis_score, window=40),
    CtxRule("ETTN", re.compile(rf"(?<![0-9A-Za-z\-]){_UUID}(?![0-9A-Za-z\-])"), _ctx("ettn", "e-fatura", "efatura", "e-arşiv"), 0.8),
    CtxRule(
        "HESAP_NO",
        _num(r"[0-9]{6,12}|[0-9]{3,5}-[0-9]{5,9}(?:-[0-9]{1,3})?"),
        _ctx("hesap no", "hesap numarası", "hesap numaram", "hesap numaranız", "hesap numarasi", "hesap #", "account no", "account number", "yatırım hesap no", "müşteri hesap no"),
        0.7,
        window=40,
    ),
    CtxRule(
        "MUSTERI_NO",
        _num(r"[0-9]{5,12}|[A-Za-z]{1,4}-?[0-9]{5,12}"),
        _ctx("müşteri no", "müşteri numarası", "müşteri numaram", "müşteri numaranız", "müşteri numarasi", "cari kod", "cari hesap kodu"),
        0.7,
        window=40,
    ),
    CtxRule("IMEI", _num(r"[0-9]{15}"), _ctx("imei"), 0.9, validate=_imei_score, window=20),
    CtxRule("SASI_NO", re.compile(r"(?<![0-9A-Za-z])[A-HJ-NPR-Za-hj-npr-z0-9]{17}(?![0-9A-Za-z])"), _ctx("şasi", "sasi", "vin"), 0.8, validate=_vin_score),
)

_ACCOUNT_FMT = re.compile(r"(?<![0-9A-Za-z\-])[0-9]{4}-[0-9]{7}-[0-9]{1,3}(?![0-9\-])")

_KRIPTO = (
    re.compile(r"(?<![0-9A-Za-z])(?:bc1[a-z0-9]{20,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|T[1-9A-HJ-NP-Za-km-z]{33})(?![0-9A-Za-z])"),
    re.compile(r"(?<![0-9A-Za-z])0x[a-fA-F0-9]{40}(?![0-9A-Za-z])"),
)

_KRIPTO_LOOSE = re.compile(r"(?<![0-9A-Za-z])T[0-9A-Za-z]{33}(?![0-9A-Za-z])")
_KRIPTO_CTX = fre(r"(?<![a-z])(?:kripto|cüzdan|wallet|usdt|trx|tron|çekim adres)")

_SIFRE_RE = fre(
    r"(?<![a-zçğıöşü])(?:şifre(?:m|si|niz|n)?|parola(?:m|sı|nız)?|pin(?: kodu| kodum|im| i|i)?|password|passwd|pwd|parolası)"
    r"[\"']?\s*(?:[:=]|\bis\b)\s*[\"']?(?P<v>[^\s\"']{4,64})"  # JSON: "password": "…"
)
# Değer gerçek bir sır gibi görünmeli: rakam veya sembol içermeli (yalnız harfli değer düz sözcüktür: "password is
# never printed", "password: hashed", "Password: string"); yer tutucu, değişken/ortam değişkeni adı ve teknik
# terimler sır sayılmaz (kod, API belgesi, commit mesajı).
_PW_STOP = frozenset(
    "md5 sha1 sha256 sha384 sha512 sha-256 sha-512 argon2 argon2id pbkdf2 base64 utf-8 utf8 aes-256 aes256 "
    "rsa-2048 bcrypt2 scrypt2 v1 v2 v3 http2 oauth2 mfa2 2fa".split()
)
_PW_PLACEHOLDER = re.compile(r"[*x•●·#.\-_?]+|[<{\[(%$].*|.*\.\.\..*|.*(?:\{\{|\}\}).*", re.IGNORECASE)
_PW_IDENT = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?:\(.*)?"  # self.password, process.env.DB, cfg.get(
    r"|[A-Za-z_][A-Za-z0-9_]*\(.*"                                   # getenv("X"), input()
    r"|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"                                 # DB_PASSWORD, PG_PASS_2
    r"|[a-z][a-z0-9]*(?:_[a-z0-9]+)+"                                 # user_pw, new_password1
)


def _pw_value_ok(v: str) -> bool:
    """Parola alanından sonra gelen değer gerçek bir sır olabilir mi (yanlış pozitif süzgeci)."""
    if not any(not c.isalpha() for c in v):  # yalnız harf: düz sözcük
        return False
    return not (v.casefold() in _PW_STOP or _PW_PLACEHOLDER.fullmatch(v) or _PW_IDENT.fullmatch(v))


# iki noktasız biçim: değer rakam içermeli (ör. "şifremi unuttum" eşleşmesin)
_SIFRE_LOOSE_RE = fre(
    r"(?<![a-zçğıöşü])(?:şifre(?:m|mi|si|sini|niz|nizi)?|parola(?:m|mı|sı)?|pin(?: kodu| kodum|im| i|i)?|password)"
    r"\s+(?:olarak\s+|da\s+|de\s+)?(?P<v>(?=\S*[0-9])\S{4,64})"
)

_MAP_PIN = fre(r"(?:harita|konum|iğne|map)\s*$")
_NUFUS_LABEL = fre(
    r"(?<![a-zçğıöşü])(?:cilt no|cilt|aile sıra no|aile sıra|sıra no|hane no|kütük no|kayıt no)(?:[ \t]{0,3}[:.])?[ \t]{0,5}(?P<v>[0-9]{1,6})(?![0-9])"
)
_NUFUS_GATE = fre(r"(?<![a-zçğıöşü])(?:cilt|nüfusa kayıtlı|nüfus kayıt|nüfus kaydı|kütük)")


class ContextualIdRecognizer(Recognizer):
    name = "contextual_ids"
    entities = tuple({r.entity for r in RULES}) + ("KRIPTO_CUZDAN", "SIFRE", "NUFUS_KAYIT")

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        cf = ctx.casefolded
        # aynı değer birden çok kurala uyarsa: bağlam ifadeleri örtüşüyorsa ("MKK sicil no" ⊃ "sicil no") daha erken başlayan
        # (daha özgül) kazanır; örtüşmüyorsa ("hesap no: X, müşteri no: Y") değere en yakın bağlam kazanır
        nearest: dict[tuple[int, int], tuple[tuple[int, int], Span]] = {}
        for rule in RULES:
            anchors = _ANCHORS.get(rule.context.pattern)
            if anchors is not None and not any(a in cf for a in anchors):
                continue  # bağlam sözcüğünün ilk kelimesi bile yok → regex aramaya gerek yok
            if not rule.context.search(cf):
                continue  # bağlam sözcüğü metinde hiç yok → değer taraması gereksiz
            for m in rule.value.finditer(text):
                s, e = m.start(), m.end()
                if ctx.in_exclusion(s, e):
                    continue
                lo = max(0, s - rule.window)
                ctx_hits = list(rule.context.finditer(cf, lo, s))
                if not ctx_hits:
                    continue
                hit = (ctx_hits[-1].start(), ctx_hits[-1].end())
                score: float | None = rule.score
                if rule.validate is not None:
                    score = rule.validate(m.group())  # type: ignore[operator]
                    if score is None and rule.entity == "IMEI" and ctx.cfg.checksum_policy == "context":
                        score = 0.7  # etiketli ama kontrol basamağı hatalı: yine de cihaz kimliği
                    if score is None:
                        continue
                v = m.group()
                sp = Span(s, e, rule.entity, v, score if score is not None else 0.0, self.name, re.sub(r"[\s\-]", "", v).upper())
                prev = nearest.get((s, e))
                if prev is None:
                    nearest[(s, e)] = (hit, sp)
                else:
                    (ps, pe), _ = prev
                    overlap = hit[0] < pe and ps < hit[1]
                    better = hit[0] < ps if overlap else hit[1] > pe
                    if better:
                        nearest[(s, e)] = (hit, sp)
        out.extend(sp for _, sp in nearest.values())
        for m in _KRIPTO_LOOSE.finditer(text):
            if _KRIPTO_CTX.search(cf[max(0, m.start() - 30) : m.start()]):
                out.append(Span(m.start(), m.end(), "KRIPTO_CUZDAN", m.group(), 0.75, self.name, m.group()))
        for rx in _KRIPTO:
            for m in rx.finditer(text):
                out.append(Span(m.start(), m.end(), "KRIPTO_CUZDAN", m.group(), 0.8, self.name, m.group()))
        seen_pw: set[int] = set()
        for m in list(_SIFRE_RE.finditer(cf)) + list(_SIFRE_LOOSE_RE.finditer(cf)):
            s, e = m.start("v"), m.end("v")
            if s in seen_pw or _MAP_PIN.search(cf[max(0, m.start() - 12) : m.start()]):
                continue  # "harita pini 40.71, …": konum iğnesi, PIN değil
            seen_pw.add(s)
            v = text[s:e].rstrip(".,;)")
            e = s + len(v)
            if len(v) >= 4 and _pw_value_ok(v):
                out.append(Span(s, e, "SIFRE", v, 0.9, self.name, v))
        for m in _ACCOUNT_FMT.finditer(text):
            out.append(Span(m.start(), m.end(), "HESAP_NO", m.group(), 0.75, self.name, m.group().replace("-", "")))
        if _NUFUS_GATE.search(cf):
            for m in _NUFUS_LABEL.finditer(cf):
                s, e = m.start("v"), m.end("v")
                out.append(Span(s, e, "NUFUS_KAYIT", text[s:e], 0.6, self.name, text[s:e]))
        return out


# ------------------------------------------------------------------ Doğum tarihi / yeri
_AYLAR = "ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık"
_DATE_RE = fre(
    rf"(?<![0-9])(?:(?P<d1>[0-9]{{1,2}})[./\-](?P<m1>[0-9]{{1,2}})[./\-](?P<y1>(?:19|20)[0-9]{{2}})"
    rf"|(?P<d2>[0-9]{{1,2}})\s+(?P<m2>{_AYLAR})\s+(?P<y2>(?:19|20)[0-9]{{2}})"
    rf"|(?P<y3>(?:19|20)[0-9]{{2}})-(?P<m3>[0-9]{{2}})-(?P<d3>[0-9]{{2}}))(?![0-9])"
)
# 2 haneli yıl ("d.t. 12.03.85"): yalnız doğum etiketi 20 karakter içinde önündeyse (fatura/vade tarihleri tuzağı)
_DATE2_RE = re.compile(r"(?<![0-9])(?P<d>[0-9]{1,2})[./\-](?P<m>[0-9]{1,2})[./\-](?P<y>[0-9]{2})(?![0-9./\-])")
_DOB_CTX = fre(
    r"(?<![a-zçğıöşü])(?:doğum|dogum|d\.t\.|d\.tarihi|doğdu|doğmuş|doğumlu|yaşı|yaşında|yaşındaki|yaşındayım|date of birth|dob)"
)
_DOB_AFTER = fre(
    r"^['’]?[a-zçğıöşü]{0,4}(?:\s+[a-zçğıöşü]+['’]?[a-zçğıöşü]{0,4})?\s*,?\s*"
    r"(?:doğumlu|doğdu|doğmuş|doğumluyum|tarihinde doğ|günü doğ)"
)
_BIRTHPLACE_BEFORE = fre(
    r"(?:doğum yeri|doğum yerim|doğum yer|doğduğu yer|doğduğum yer|d\.yeri|d\.\s?y\.|doğum yeri ve tarihi|place of birth)\s*[:\-/]?\s*$"
)
_BIRTHPLACE_AFTER = fre(r"^(?:['’]?(?:da|de|ta|te)\s+doğ|\s+doğumlu|['’]?(?:lı|li|lu|lü)\s+olup\s+[0-9]{4}\s+doğumlu)")
_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû]+")


class DobRecognizer(Recognizer):
    name = "date_of_birth"
    entities = ("DOGUM_TARIHI", "DOGUM_YERI")

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        cf = ctx.casefolded
        strict = ctx.cfg.profile == "strict"
        for m in _DATE_RE.finditer(cf):
            s, e = m.start(), m.end()
            # aynı satırda: bağlam 80 karakter önce ("doğum tarihi: ...") ya da hemen sonra ("... doğumlu")
            nl_before = cf.rfind("\n", 0, s)
            nl_after = cf.find("\n", e)
            lo = max(nl_before + 1, s - 80)
            hi = min(nl_after if nl_after >= 0 else len(cf), e + 25)
            if _DOB_CTX.search(cf[lo:s]) or _DOB_AFTER.match(cf[e:hi]):
                out.append(Span(s, e, "DOGUM_TARIHI", text[s:e], 0.85, self.name, _norm_date(m)))
            elif strict:
                out.append(Span(s, e, "DOGUM_TARIHI", text[s:e], 0.55, self.name, _norm_date(m)))
        for m in _DATE2_RE.finditer(text):
            s, e = m.start(), m.end()
            if not (1 <= int(m["d"]) <= 31 and 1 <= int(m["m"]) <= 12):
                continue
            if _DOB_CTX.search(cf[max(0, s - 20) : s]):
                yy = int(m["y"])
                norm = f"{int(m['d']):02d}.{int(m['m']):02d}.{1900 + yy if yy > 30 else 2000 + yy}"
                out.append(Span(s, e, "DOGUM_TARIHI", text[s:e], 0.8, self.name, norm))
        g = data.geo()
        if "dog" not in cf and "d.y" not in cf and "d. y" not in cf and "birth" not in cf:
            return out  # doğum yeri bağlamı yoksa sözcük taraması gereksiz
        for m in _WORD.finditer(text):
            w = m.group()
            if not is_capitalized(w):
                continue
            k = fold_key(w)
            if not g.is_province_or_district(k):
                continue
            before = cf[max(0, m.start() - 30) : m.start()]
            after = cf[m.end() : m.end() + 20]
            if _BIRTHPLACE_BEFORE.search(before) or _BIRTHPLACE_AFTER.match(after):
                out.append(Span(m.start(), m.end(), "DOGUM_YERI", w, 0.8, self.name, k))
        return out


def _norm_date(m: re.Match[str]) -> str:
    if m["d1"]:
        return f"{int(m['d1']):02d}.{int(m['m1']):02d}.{m['y1']}"
    if m["d2"]:
        mi = ascii_fold(_AYLAR).split("|").index(m["m2"]) + 1
        return f"{int(m['d2']):02d}.{mi:02d}.{m['y2']}"
    return f"{m['d3']}.{m['m3']}.{m['y3']}"


# ------------------------------------------------------------------ deny_list
class DenyListRecognizer(Recognizer):
    """Yapılandırılmış düz ifadeler: katlanmış metinde sözcük sınırlı önek ağacı (tek regex)."""

    name = "deny_list"

    def __init__(self, cfg) -> None:  # type: ignore[no-untyped-def]
        from ..text_utils import fold_text, trie_pattern

        self.by_key: dict[str, str] = {}
        for d in cfg.deny_list:
            self.by_key[" ".join(fold_text(d.phrase).split())] = d.entity
        self.entities = tuple(sorted(set(self.by_key.values())))
        pat = trie_pattern(sorted(self.by_key, key=len, reverse=True))
        self.rx = re.compile(rf"(?<![0-9a-z])(?:{pat})(?![0-9a-z])") if self.by_key else None

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        if self.rx is None:
            return out
        for m in self.rx.finditer(ctx.casefolded):
            ent = self.by_key.get(" ".join(m.group().split()))
            if ent:
                out.append(Span(m.start(), m.end(), ent, text[m.start() : m.end()], 0.9, self.name, m.group()))
        return out


# ------------------------------------------------------------------ extra_regex
class ExtraRegexRecognizer(Recognizer):
    name = "extra_regex"

    def __init__(self, cfg) -> None:  # type: ignore[no-untyped-def]
        self.rules = []
        for x in cfg.extra_regex:
            flags = re.IGNORECASE if x.ignore_case else 0
            ctxp = re.compile(x.context) if x.context else None
            self.rules.append((x, re.compile(x.pattern, flags), ctxp))
        self.entities = tuple(x.entity for x in cfg.extra_regex)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = []
        for x, rx, ctxp in self.rules:
            for m in rx.finditer(text):
                if m.end() == m.start():
                    continue
                if ctxp is not None and not ctx.has_context(m.start(), m.end(), ctxp, window=x.context_window):
                    continue
                out.append(Span(m.start(), m.end(), x.entity, m.group(), x.score, self.name, m.group().upper()))
        return out
