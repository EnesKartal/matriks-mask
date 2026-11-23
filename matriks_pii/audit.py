"""Değersiz (yalnız sayım/meta) JSONL denetim izi. Hiçbir PII değeri yazılmaz."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import threading
from collections import Counter
from typing import IO, Any


class AuditLog:
    """Günlük döndürülen JSONL dosyası. Dosya tutamacı açık tutulur; gün değişince yeniden açılır."""

    def __init__(self, enabled: bool, path: str | None, config_hash: str) -> None:
        self.enabled = bool(enabled and path)
        self.path = path
        self.config_hash = config_hash
        self.counters: Counter[str] = Counter()
        self._lock = threading.Lock()
        self._fh: IO[str] | None = None
        self._fh_name: str | None = None

    def count(self, name: str, n: int = 1) -> None:
        self.counters[name] += n

    def _file(self) -> str:
        assert self.path
        day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
        root, ext = os.path.splitext(self.path)
        return f"{root}.{day}{ext or '.jsonl'}"

    def _handle(self) -> IO[str]:
        name = self._file()
        if self._fh is None or self._fh_name != name or self._fh.closed:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
            os.makedirs(os.path.dirname(os.path.abspath(name)), exist_ok=True)
            self._fh = open(name, "a", encoding="utf-8")  # noqa: SIM115 — bilinçli olarak açık tutulur
            self._fh_name = name
        return self._fh

    def write(self, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), "guardrail_version": _version(), "config_hash": self.config_hash}
        rec.update(record)
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            try:
                fh = self._handle()
                fh.write(line + "\n")
                fh.flush()
            except Exception:
                self._fh = None  # bir sonraki yazımda yeniden açmayı dene
                raise

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


def api_key_hash(token: str | None) -> str | None:
    if not token:
        return None
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def score_buckets(spans: Any) -> dict[str, dict[str, int]]:
    """Varlık başına 0.1'lik skor kovası sayımı (değer yok) — yanlış pozitif kayması izleme için."""
    out: dict[str, Counter[str]] = {}
    for s in spans or []:
        b = f"{min(0.9, int(s.score * 10) / 10):.1f}"
        out.setdefault(s.entity, Counter())[b] += 1
    return {e: dict(c) for e, c in out.items()}


def _version() -> str:
    from . import __version__

    return __version__
