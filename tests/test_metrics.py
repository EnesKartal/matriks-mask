"""Prometheus metrikleri: değersiz etiketler, çoklu kayıt güvenliği, kapatılabilirlik."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from helpers import model_response
from test_hooks import T1, G, chat, pre

from matriks_pii import metrics

prom = pytest.importorskip("prometheus_client")


def _val(name: str, **labels: str) -> float:
    v = prom.REGISTRY.get_sample_value(name, labels)
    return v or 0.0


def _all_label_values() -> list[str]:
    out = []
    for fam in prom.REGISTRY.collect():
        if fam.name.startswith("matriks_pii"):
            for s in fam.samples:
                out.extend(s.labels.values())
    return out


async def test_counters_increment_value_free() -> None:
    before = _val("matriks_pii_entities_total", guardrail="matriks-pii", entity="TCKN", action="MASK")
    hooks_before = _val("matriks_pii_hook_total", guardrail="matriks-pii", hook="pre_call", status="guardrail_intervened")
    g = G()
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1> <KISI_9>"))
    assert _val("matriks_pii_entities_total", guardrail="matriks-pii", entity="TCKN", action="MASK") == before + 1
    assert _val("matriks_pii_hook_total", guardrail="matriks-pii", hook="pre_call",
                status="guardrail_intervened") == hooks_before + 1
    assert _val("matriks_pii_events_total", guardrail="matriks-pii", event="unresolved_placeholder") >= 1
    labels = _all_label_values()
    assert T1 not in labels and "Ayşe Demir" not in labels


async def test_blocked_event_counted() -> None:
    before = _val("matriks_pii_events_total", guardrail="matriks-pii", event="blocked")
    with pytest.raises(HTTPException):
        await pre(G(entities={"SIFRE": "BLOCK"}), chat("Şifre: Gizli123! kaydet"))
    assert _val("matriks_pii_events_total", guardrail="matriks-pii", event="blocked") == before + 1


async def test_metrics_disabled_by_config() -> None:
    before = _val("matriks_pii_entities_total", guardrail="kapali", entity="TCKN", action="MASK")
    g = G(metrics_enabled=False)
    g.guardrail_name = "kapali"
    await pre(g, chat(f"TCKN {T1}"))
    assert _val("matriks_pii_entities_total", guardrail="kapali", entity="TCKN", action="MASK") == before


def test_no_duplicate_registration_two_guardrails() -> None:
    G()
    G()
    metrics.inc_event("a", "x")
    metrics._CREATED.clear()  # modül yeniden yüklenmiş gibi: kayıtlı metrik yeniden bulunur, hata yok
    metrics.inc_event("a", "x")
    assert _val("matriks_pii_events_total", guardrail="a", event="x") == 2


def test_gauge_livesum_mode() -> None:
    metrics.set_gauge("sessions_open", "g1", 3)
    assert _val("matriks_pii_sessions_open", guardrail="g1") == 3
    assert metrics._CREATED["matriks_pii_sessions_open"]._multiprocess_mode == "livesum"


def test_noop_without_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "_prom", None)
    assert metrics.enabled() is False
    metrics.inc_event("g", "e")
    metrics.inc_entities("g", {"TCKN": 1}, lambda e: "MASK")
    metrics.observe_hook("g", "pre_call", "success", 0.1)
    metrics.set_gauge("x", "g", 1)


def test_env_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIKS_PII_METRICS", "0")
    assert metrics.enabled() is False
