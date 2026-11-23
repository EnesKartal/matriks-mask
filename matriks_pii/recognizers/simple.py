"""E-posta, IP/MAC ve araç plakası tanıyıcıları."""

from __future__ import annotations

import ipaddress
import re

from ..text_utils import tr_lower
from .base import AnalysisContext, Recognizer, Span, ctx_prefix_re

# ------------------------------------------------------------------ E-posta
_EMAIL_RE = re.compile(
    r"(?<![\w.+\-])([\w.+\-çğıöşüÇĞİÖŞÜ]+@[\w\-çğıöşüÇĞİÖŞÜ]+(?:\.[\w\-çğıöşüÇĞİÖŞÜ]+)*\.[A-Za-z]{2,})(?![\w])"
)


_OBF_AT = r"\s*[\[\(]\s*at\s*[\]\)]\s*"
_OBF_DOT = r"(?:\s*[\[\(]\s*(?:dot|nokta)\s*[\]\)]\s*|\.)"
# gizlenmiş e-posta: "ahmet [at] gmail.com", "kullanici (at) alanadi (nokta) com"
_EMAIL_OBF_RE = re.compile(
    rf"(?<![\w.+\-])(?P<local>[\w.+\-çğıöşüÇĞİÖŞÜ]{{1,64}}){_OBF_AT}"
    rf"(?P<domain>[\w\-çğıöşüÇĞİÖŞÜ]+(?:{_OBF_DOT}[\w\-]+)*{_OBF_DOT}[A-Za-z]{{2,}})(?![\w])",
    re.IGNORECASE,
)
_DOT_NORM = re.compile(_OBF_DOT, re.IGNORECASE)


class EmailRecognizer(Recognizer):
    name = "email"
    entities = ("EPOSTA",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = []
        for m in _EMAIL_RE.finditer(text):
            v = m.group(1)
            if v.startswith(".") or ".." in v:
                continue
            out.append(Span(m.start(1), m.end(1), "EPOSTA", v, 0.95, self.name, tr_lower(v)))
        if "at" in ctx.casefolded:
            for m in _EMAIL_OBF_RE.finditer(text):
                norm = tr_lower(m["local"]) + "@" + _DOT_NORM.sub(".", m["domain"]).lower()
                out.append(Span(m.start(), m.end(), "EPOSTA", m.group(), 0.8, self.name, norm))
        return out


# ------------------------------------------------------------------ IP / MAC
_IPV4_RE = re.compile(r"(?<![0-9.\w])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(?![0-9]|\.[0-9])")
_IPV6_RE = re.compile(r"(?<![0-9A-Fa-f:\w])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(?![0-9A-Fa-f:\w])")
_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:\-])((?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2})(?![0-9A-Fa-f:\-])")
_VERSION_CTX = ctx_prefix_re("sürüm", "versiyon", "version", "release", "güncelleme", "build", "v")


class IpRecognizer(Recognizer):
    name = "ip"
    entities = ("IP", "MAC")

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        for m in _IPV4_RE.finditer(text):
            v = m.group(1)
            s = m.start(1)
            if s > 0 and text[s - 1] in "vV":
                continue
            try:
                ipaddress.IPv4Address(v)
            except ValueError:
                continue
            if any(len(o) > 1 and o.startswith("0") for o in v.split(".")):
                continue
            pre = ctx.casefolded[max(0, s - 20) : s]
            if _VERSION_CTX.search(pre) and re.search(r"(surum[a-z]{0,4}|versiyon[a-z]{0,4}|version|release|build|\bv)\s*[:.]?\s*$", pre):
                continue
            post = ctx.casefolded[m.end(1) : m.end(1) + 15]
            if re.match(r"\s*[-_]?(surum|versiyon|version|release|build|guncelleme)", post):
                continue  # "10.2.1.4 sürümü"
            out.append(Span(s, m.end(1), "IP", v, 0.9, self.name, v))
        mac_spans = []
        for m in _MAC_RE.finditer(text):
            v = m.group(1)
            mac_spans.append((m.start(1), m.end(1)))
            out.append(Span(m.start(1), m.end(1), "MAC", v, 0.85, self.name, re.sub(r"[:\-]", "", v).lower()))
        for m in _IPV6_RE.finditer(text):
            v = m.group(1)
            if v.count(":") < 2 or any(a <= m.start(1) < b for a, b in mac_spans):
                continue
            if not re.search(r"[0-9A-Fa-f]", v):
                continue
            try:
                ip = ipaddress.IPv6Address(v)
            except ValueError:
                continue
            out.append(Span(m.start(1), m.end(1), "IP", v, 0.9, self.name, ip.compressed))
        return out


# ------------------------------------------------------------------ Plaka
_PLATE_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü/.,:])(?P<il>0[1-9]|[1-7][0-9]|8[01])(?P<s1>[\s\-]?)(?P<h>[A-PR-VYZ]{1,3})(?P<s2>[\s\-]?)"
    r"(?P<r>[0-9]{2,5})(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_PLATE_STOP = frozenset("TL BIN MIL USD EUR GBP ADET LOT KG GR CM MM KM ML DK SN MB GB KB HP TB AB".split()) - {"AB"}
_PLATE_LEN = {1: (4, 5), 2: (3, 4), 3: (2, 3)}
_PLATE_LABEL = re.compile(r"(?<![a-z])plaka(?:si|sı|li|lı)?\s*(?:no|numarasi)?\s*[:.]?\s*$")
_PLATE_CTX = ctx_prefix_re("plaka", "araç", "arac", "otomobil", "araba", "taşıt", "kamyon", "motosiklet", "ruhsat")


class PlateRecognizer(Recognizer):
    name = "plate"
    entities = ("PLAKA",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out = self._scan(text, text, ctx)
        if any(c.islower() for c in text) and "plaka" in ctx.casefolded:
            # "plaka: 34abc123": yalnız plaka etiketi önündeyse BÜYÜK harfe çevrilmiş kopyada (1:1) ara
            up = "".join(c.upper() if c.isascii() else c for c in text)
            seen = {(s.start, s.end) for s in out}
            for sp in self._scan(up, text, ctx):
                if (sp.start, sp.end) not in seen and _PLATE_LABEL.search(ctx.casefolded[max(0, sp.start - 15) : sp.start]):
                    out.append(sp)
        return out

    def _scan(self, text: str, orig: str, ctx: AnalysisContext) -> list[Span]:
        out = []
        for m in _PLATE_RE.finditer(text):
            h, r = m["h"], m["r"]
            if h in _PLATE_STOP:
                continue
            lo, hi = _PLATE_LEN[len(h)]
            labeled = _PLATE_LABEL.search(ctx.casefolded[max(0, m.start() - 15) : m.start()]) is not None
            if not lo <= len(r) <= hi and not (labeled and 2 <= len(r) <= 4):
                continue
            if ctx.in_exclusion(m.start(), m.end()):
                continue
            separated = bool(m["s1"]) and bool(m["s2"])
            if separated:
                score = 0.85
            else:
                if not ctx.has_context(m.start(), m.end(), _PLATE_CTX, window=40):
                    continue
                score = 0.7
            norm = m["il"] + h + r
            out.append(Span(m.start(), m.end(), "PLAKA", orig[m.start() : m.end()], score, self.name, norm))
        return out
