"""Gizli anahtar / erişim belirteci tespiti (`GIZLI_ANAHTAR`).

KVKK kişisel verisi değildir ama kullanıcılar API anahtarı, token, özel anahtar ve bağlantı dizesi parolasını LLM'e
yapıştırır; yurt dışındaki sağlayıcıya gitmesi güvenlik ihlalidir. Varsayılan: MASK + geri yüklenmez (yanıtta "****"),
strict profil: BLOCK. Desenler sağlayıcıların belgelenmiş önekleriyle sınırlıdır (yüksek kesinlik).
"""

from __future__ import annotations

import re

from .base import AnalysisContext, Recognizer, Span

_B = r"(?<![A-Za-z0-9_\-])"
_E = r"(?![A-Za-z0-9_\-])"

# (ad, desen, skor). Adlandırılmış "v" grubu varsa yalnız o kısım maskelenir. _TRIGGERS: desen ancak tetikleyici
# alt dizgi (küçük harfli metinde) varsa çalıştırılır — 2 KB metinde tüm tarama ~0.02 ms.
_TRIGGERS: dict[str, tuple[str, ...]] = {
    "openai": ("sk-",), "aws_access": ("akia", "asia", "agpa", "aida", "aroa", "aipa", "anpa", "anva"),
    "github": ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"), "slack": ("xox",), "google": ("aiza",),
    "stripe": ("sk_live", "sk_test", "rk_live", "rk_test"), "jwt": ("eyj",), "private_key": ("-----begin",),
    "conn_pass": ("://",), "bearer": ("bearer",),
    "generic": ("key", "token", "secret"),
}
_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("openai", re.compile(_B + r"sk-(?:proj-|svcacct-|ant-(?:api|admin)\d*-)?[A-Za-z0-9_\-]{20,}" + _E), 0.95),
    ("aws_access", re.compile(_B + r"(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}" + _E), 0.95),
    ("github", re.compile(_B + r"(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})" + _E), 0.95),
    ("slack", re.compile(_B + r"xox[baprs]-[0-9A-Za-z\-]{10,}" + _E), 0.95),
    ("google", re.compile(_B + r"AIza[0-9A-Za-z\-_]{35}" + _E), 0.95),
    ("stripe", re.compile(_B + r"(?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{20,}" + _E), 0.95),
    ("jwt", re.compile(_B + r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}" + _E), 0.95),
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----[\s\S]{0,8000}?"
            r"-----END (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"
        ),
        0.95,
    ),
    # bağlantı dizesi: "postgres://user:parola@host" → kullanıcı:parola@host (host da maskelenir; EPOSTA ile çakışmasın)
    ("conn_pass", re.compile(r"(?<=://)(?P<v>[^:/\s@]+:[^@\s/]{3,}@[^/\s:?#]+)"), 0.95),
    ("bearer", re.compile(r"(?i:bearer)\s+(?P<v>[A-Za-z0-9\-._~+/]{20,}=*)" + _E), 0.95),
    (
        "generic",
        re.compile(
            r"(?i:api[_\-]?key|secret[_\-]?key|access[_\-]?token|auth[_\-]?token|client[_\-]?secret|x-api-key)"
            r"\s*[:=]\s*[\"']?(?P<v>[A-Za-z0-9_\-]{16,})[\"']?"
        ),
        0.85,
    ),
)


class SecretRecognizer(Recognizer):
    name = "secrets"
    entities = ("GIZLI_ANAHTAR",)

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:
        out: list[Span] = []
        low = text.lower()
        for name, rx, score in _PATTERNS:
            if not any(t in low for t in _TRIGGERS[name]):
                continue
            for m in rx.finditer(text):
                if "v" in rx.groupindex:
                    s, e = m.start("v"), m.end("v")
                else:
                    s, e = m.start(), m.end()
                if e > s:
                    out.append(Span(s, e, "GIZLI_ANAHTAR", text[s:e], score, self.name, text[s:e]))
        return out
