"""İstek başına maskeleme oturumu: yer tutucu ↔ orijinal değer haritası."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections import Counter
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import TurkishPIIConfig
    from .recognizers.base import Span


def masked_display(entity: str, value: str, restore_last4: bool = True) -> str:
    """`restore: false` olan varlıklar için haritaya yazılan güvenli gösterim."""
    if entity in ("GIZLI_ANAHTAR", "SIFRE"):  # uzunluk da sızmasın
        return "****"
    if entity == "KART":
        digits = re.sub(r"\D", "", value)
        return ("**** **** **** " + digits[-4:]) if restore_last4 and len(digits) >= 4 else "****"
    if entity == "IBAN":
        compact = re.sub(r"[\s\-]", "", value)
        return compact[:4] + " **** **** **** " + compact[-4:]
    if entity == "TELEFON":
        digits = re.sub(r"\D", "", value)
        return "*** *** ** " + digits[-2:]
    return "*" * min(8, max(3, len(value)))


class MaskSession:
    """Harita yalnız bellekte (veya şifreli Redis'te) tutulur; asla loglanmaz/metadata'ya yazılmaz."""

    def __init__(self, cfg: TurkishPIIConfig) -> None:
        self.cfg = cfg
        self.map: dict[str, str] = {}  # placeholder -> geri yüklenecek değer
        self.entities: dict[str, str] = {}  # placeholder -> entity
        self.by_key: dict[tuple[str, str], str] = {}
        self.counts: Counter[str] = Counter()
        self.reserved: set[str] = set()
        self.entity_counts: Counter[str] = Counter()  # maskelenen span sayısı (oluşum)
        self.log_counts: Counter[str] = Counter()
        self.blocked: str | None = None
        self.wrapped: set[str] = set()  # istekte değer formatın parantezleri içindeydi ("<ayse@x.com>")
        self.numeric: set[str] = set()  # istekte JSON sayısı olan yer tutucular

    def __repr__(self) -> str:  # değer sızdırmaz
        return f"MaskSession(placeholders={len(self.map)})"

    # ------------------------------------------------------------------ rezervasyon
    def reserve_existing(self, texts: Iterable[str]) -> None:
        """Kullanıcı metninde zaten bulunan LABEL_n biçimli yer tutucular numaralandırmada atlanır."""
        from .revert import normalize_id, placeholder_scanner

        rx, lab_map = placeholder_scanner(self.cfg)
        from .text_utils import ascii_fold, tr_lower

        for t in texts:
            if not t:
                continue
            probe = ascii_fold(tr_lower(t))
            for m in rx.finditer(probe):
                label = lab_map.get(m["label"])
                if not label or m["n"] is None:  # numarasız genel biçim ("<TCKN_...>") bir yer tutucu ayırmaz
                    continue
                if not (m["open"] or m["close"]) and m["sep"] not in ("_", "\\_"):
                    continue  # "TCKN 17291716060" gibi düz metin yer tutucu değildir
                n = normalize_id(m["n"])
                self.reserved.add(self.cfg.format_placeholder(label, n))
                if n.isdigit():
                    self.counts[label] = max(self.counts[label], int(n))

    # ------------------------------------------------------------------ yer tutucu
    def _hmac_id(self, entity: str, normalized: str, length: int = 6) -> str:
        assert self.cfg.hash_secret
        d = hmac.new(self.cfg.hash_secret.encode(), f"{entity}|{normalized}".encode(), hashlib.sha256).digest()
        return base64.b32encode(d).decode().lower()[:length]

    def placeholder_for(self, span: Span, count: bool = True) -> str:
        """`count=False`: aynı değerin ikinci kopyası (proxy gövde kopyası, log maskeleme) — sayım/denetim izi şişmesin."""
        key = (span.entity, span.normalized)
        ph = self.by_key.get(key)
        if ph is None:
            label = self.cfg.label(span.entity)
            if self.cfg.placeholder_id == "hmac":
                ph = self.cfg.format_placeholder(label, self._hmac_id(span.entity, span.normalized))
            else:
                while True:
                    self.counts[label] += 1
                    ph = self.cfg.format_placeholder(label, self.counts[label])
                    if ph not in self.reserved:
                        break
            restore = self.cfg.restore(span.entity)
            value = span.text if restore else masked_display(span.entity, span.text, self.cfg.revert.restore_last4)
            if self.cfg.placeholder_id == "hmac":
                # 30 bitlik kimlikte (6 kr) iki farklı değer çakışırsa kimliği uzat; aksi hâlde yanlış değer geri yüklenir
                for length in (6, 8, 10, 12):
                    ph = self.cfg.format_placeholder(label, self._hmac_id(span.entity, span.normalized, length))
                    if (ph not in self.map or self.map[ph] == value) and ph not in self.reserved:
                        break
            self.map[ph] = value
            self.entities[ph] = span.entity
            self.by_key[key] = ph
        if count:
            self.entity_counts[span.entity] += 1
        return ph

    def count_log(self, spans: Iterable[Span]) -> None:
        for s in spans:
            self.log_counts[s.entity] += 1

    # ------------------------------------------------------------------ serileştirme (Redis)
    def to_dict(self) -> dict[str, Any]:
        return {
            "map": self.map,
            "entities": self.entities,
            "by_key": [[k[0], k[1], v] for k, v in self.by_key.items()],
            "counts": dict(self.counts),
            "reserved": sorted(self.reserved),
            "entity_counts": dict(self.entity_counts),
            "log_counts": dict(self.log_counts),
            "numeric": sorted(self.numeric),
            "wrapped": sorted(self.wrapped),
        }

    @classmethod
    def from_dict(cls, cfg: TurkishPIIConfig, d: dict[str, Any]) -> MaskSession:
        s = cls(cfg)
        s.map = dict(d.get("map", {}))
        s.entities = dict(d.get("entities", {}))
        s.by_key = {(a, b): v for a, b, v in d.get("by_key", [])}
        s.counts = Counter(d.get("counts", {}))
        s.reserved = set(d.get("reserved", []))
        s.entity_counts = Counter(d.get("entity_counts", {}))
        s.log_counts = Counter(d.get("log_counts", {}))
        s.numeric = set(d.get("numeric", []))
        s.wrapped = set(d.get("wrapped", []))  # eski oturumlarda yok
        return s
