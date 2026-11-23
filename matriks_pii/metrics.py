"""Değersiz işletim metrikleri (Prometheus, opsiyonel: `pip install "matriks-pii[metrics]"`).

* Etiketler yalnız guardrail adı, varlık türü, aksiyon, kanca, durum, olay adı ve skor kovası taşır — hiçbir değer yok.
* `prometheus_client` yoksa veya `MATRIKS_PII_METRICS=0` ise tüm çağrılar no-op'tur.
* LiteLLM çoklu worker modunda `PROMETHEUS_MULTIPROC_DIR` kullanır; burada yalnız Counter/Histogram ve `livesum` modlu
  Gauge kullanılır (çoklu süreçte güvenli). `REGISTRY` iç yapısına dokunulmaz: tekil nesneler modül düzeyinde tutulur.
* `/metrics` uç noktası LiteLLM'de `litellm_settings.callbacks: ["prometheus"]` ile açılır.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

_LOCK = threading.Lock()
_CREATED: dict[str, Any] = {}
_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

_prom: Any
try:  # pragma: no cover - kurulu olup olmamasına göre
    import prometheus_client as _prom
except ImportError:  # pragma: no cover
    _prom = None


def enabled() -> bool:
    return _prom is not None and os.environ.get("MATRIKS_PII_METRICS", "1") != "0"


def _metric(kind: str, name: str, doc: str, labels: tuple[str, ...], **kw: Any) -> Any:
    m = _CREATED.get(name)
    if m is not None:
        return m
    with _LOCK:
        m = _CREATED.get(name)
        if m is None:
            cls = getattr(_prom, kind)
            try:
                m = cls(name, doc, labels, **kw)
            except ValueError:  # aynı ad başka bir yolla kaydedilmiş (yeniden import) → kayıttan bul
                m = _prom.REGISTRY._names_to_collectors.get(name)  # type: ignore[union-attr]
                if m is None:
                    raise
            _CREATED[name] = m
    return m


def _g(guardrail: str | None) -> str:
    return guardrail or "matriks-pii"


def inc_event(guardrail: str | None, event: str, n: int = 1) -> None:
    """Olay sayacı (session_missing, store_unavailable, ner_failed, blocked, unresolved_placeholder, ...)."""
    if not enabled() or n <= 0:
        return
    try:
        _metric("Counter", "matriks_pii_events_total", "matriks-pii olayları", ("guardrail", "event")).labels(
            _g(guardrail), event).inc(n)
    except Exception:  # metrik hatası isteği asla bozmaz
        pass


def inc_entities(guardrail: str | None, counts: Mapping[str, int], action_of: Callable[[str], str]) -> None:
    """Varlık türü ve aksiyon başına tespit sayısı."""
    if not enabled():
        return
    try:
        c = _metric("Counter", "matriks_pii_entities_total", "matriks-pii varlık tespitleri", ("guardrail", "entity", "action"))
        for ent, n in counts.items():
            if n > 0:
                c.labels(_g(guardrail), ent, action_of(ent)).inc(n)
    except Exception:
        pass


def inc_score_buckets(guardrail: str | None, buckets: Mapping[str, Mapping[str, int]]) -> None:
    """Varlık başına skor kovası (yanlış pozitif kayması izleme)."""
    if not enabled():
        return
    try:
        c = _metric("Counter", "matriks_pii_scores_total", "matriks-pii skor kovaları", ("guardrail", "entity", "score_bucket"))
        for ent, b in buckets.items():
            for bucket, n in b.items():
                c.labels(_g(guardrail), ent, bucket).inc(n)
    except Exception:
        pass


def observe_hook(guardrail: str | None, hook: str, status: str, seconds: float) -> None:
    """Kanca süresi (histogram) ve sonucu (sayaç)."""
    if not enabled():
        return
    try:
        _metric("Histogram", "matriks_pii_hook_seconds", "matriks-pii kanca süresi", ("guardrail", "hook"),
                buckets=_BUCKETS).labels(_g(guardrail), hook).observe(max(0.0, seconds))
        _metric("Counter", "matriks_pii_hook_total", "matriks-pii kanca çağrıları", ("guardrail", "hook", "status")).labels(
            _g(guardrail), hook, status).inc()
    except Exception:
        pass


def set_gauge(name: str, guardrail: str | None, value: float) -> None:
    """Anlık değer (sessions_open, cache_entries). Çoklu süreçte süreçlerin toplamı (livesum)."""
    if not enabled():
        return
    try:
        _metric("Gauge", f"matriks_pii_{name}", f"matriks-pii {name}", ("guardrail",),
                multiprocess_mode="livesum").labels(_g(guardrail)).set(value)
    except Exception:
        pass
