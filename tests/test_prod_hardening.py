"""Üretim sertleştirme testleri.

Tüm değerler sentetiktir.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import pytest
from fastapi import HTTPException
from helpers import FakeRedis, agen, model_response, stream_chunks
from test_hooks import T1, G, chat, no_secret, pre

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.guardrail import SESSION_KEY
from matriks_pii.store import RedisSessionStore


def _redis_g(monkeypatch: pytest.MonkeyPatch, fake: FakeRedis, **kw: Any) -> Any:
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    g = G(session_secret="s" * 40, **kw)
    g.store = RedisSessionStore(g.cfg, "matriks-pii", client=fake)
    return g


# ================================================================== oturum bulunamazsa
async def test_post_call_session_missing_closed_raises() -> None:
    g = G()
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    g.store._d.clear()  # TTL doldu / farklı süreç
    with pytest.raises(HTTPException) as ei:
        await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<KISI_1> <TCKN_1>"))
    assert ei.value.status_code == 500
    assert ei.value.detail == {"error": "matriks_pii_session_missing", "guardrail": "matriks-pii"}
    assert "<KISI_1>" not in str(ei.value.detail)


async def test_post_call_session_missing_open_passthrough() -> None:
    g = G(revert_fail_mode="open")
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    g.store._d.clear()
    assert await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>")) is None


async def test_post_call_no_token_passthrough() -> None:
    g = G()
    d = chat("Merhaba, bugün hava güzel.")
    await pre(g, d)
    assert SESSION_KEY not in d["metadata"]  # maskelenecek bir şey yok → jeton yazılmaz
    assert await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("ok")) is None


async def test_stream_session_missing_closed_raises_before_first_chunk() -> None:
    g = G()
    d = chat(f"TCKN {T1}", stream=True)
    await pre(g, d)
    g.store._d.clear()
    got: list[Any] = []
    with pytest.raises(HTTPException) as ei:
        async for item in g.async_post_call_streaming_iterator_hook(None, agen(stream_chunks("x <TCKN_1>")), d):
            got.append(item)
    assert got == [] and ei.value.detail["error"] == "matriks_pii_session_missing"


async def test_stream_session_missing_open_passthrough() -> None:
    g = G(revert_fail_mode="open")
    d = chat(f"TCKN {T1}", stream=True)
    await pre(g, d)
    g.store._d.clear()
    chunks = stream_chunks("x <TCKN_1>")
    got = [i async for i in g.async_post_call_streaming_iterator_hook(None, agen(chunks), d)]
    assert got == chunks


async def test_session_missing_counted_in_audit(tmp_path: Any) -> None:
    g = G(audit_log={"enabled": True, "path": str(tmp_path / "a.jsonl")}, revert_fail_mode="open")
    d = chat(f"TCKN {T1}")
    await pre(g, d)
    g.store._d.clear()
    await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>"))
    recs = [json.loads(ln) for p in tmp_path.glob("a*.jsonl") for ln in p.read_text(encoding="utf-8").splitlines()]
    assert any(r.get("session_missing") is True and r["event"] == "post_call" for r in recs)
    assert g.audit.counters["session_missing"] == 1
    no_secret(recs)


async def test_no_pii_request_does_not_touch_store(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    g = _redis_g(monkeypatch, fake)
    d = chat("Merhaba, THYAO 300 TL'den işlem gördü.")
    await pre(g, d)
    assert fake.calls.get("set", 0) == 0 and SESSION_KEY not in d["metadata"]


async def test_store_down_no_pii_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    fake.down = True
    g = _redis_g(monkeypatch, fake)
    d = chat("Merhaba, nasılsın?")
    out = await pre(g, d)
    assert out["messages"][0]["content"] == "Merhaba, nasılsın?"


async def test_store_down_with_pii_503_value_free(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    fake.down = True
    g = _redis_g(monkeypatch, fake)
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    with pytest.raises(HTTPException) as ei:
        await pre(g, d)
    assert ei.value.status_code == 503
    assert ei.value.detail == {"error": "matriks_pii_store_unavailable", "guardrail": "matriks-pii"}
    no_secret(d["messages"])  # hata yolunda loglanacak istek ham veri taşımaz


async def test_store_down_fail_open_returns_masked_data(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    fake.down = True
    g = _redis_g(monkeypatch, fake, fail_mode="open")
    d = chat(f"TCKN {T1}")
    out = await pre(g, d)
    assert out["messages"][0]["content"] == "TCKN <TCKN_1>"


async def test_post_call_store_down_closed_503(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    g = _redis_g(monkeypatch, fake)
    d = chat(f"TCKN {T1}")
    await pre(g, d)
    fake.down = True
    with pytest.raises(HTTPException) as ei:
        await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>"))
    assert ei.value.status_code == 503


async def test_post_call_pop_failure_does_not_break_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    g = _redis_g(monkeypatch, fake)
    d = chat(f"TCKN {T1}")
    await pre(g, d)

    async def boom(sid: str) -> None:
        raise ConnectionError("x")

    g.store.pop = boom  # type: ignore[method-assign]
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>"))
    assert out.choices[0].message.content == T1


# ================================================================== apply_guardrail
def _infos(rd: dict[str, Any]) -> list[dict[str, Any]]:
    return list(rd.get("metadata", {}).get("standard_logging_guardrail_information") or [])


async def test_apply_guardrail_records_own_value_free_info() -> None:
    g = G()
    rd: dict[str, Any] = {"metadata": {}}
    out = await g.apply_guardrail(inputs={"texts": [f"Ben Ayşe Demir, TCKN {T1}"]}, request_data=rd, input_type="request")
    assert out["texts"] == ["Ben <KISI_1>, TCKN <TCKN_1>"]
    back = await g.apply_guardrail(inputs={"texts": out["texts"]}, request_data=rd, input_type="response")
    assert back["texts"] == [f"Ben Ayşe Demir, TCKN {T1}"]
    infos = _infos(rd)
    assert len(infos) == 2
    assert all(i["guardrail_provider"] == "matriks_pii" for i in infos)
    assert infos[0]["guardrail_response"]["entities"] == {"KISI": 1, "TCKN": 1}
    no_secret(rd)


async def test_apply_guardrail_block_records_entity_only() -> None:
    g = G(entities={"SIFRE": "BLOCK"})
    rd: dict[str, Any] = {"metadata": {}}
    with pytest.raises(HTTPException) as ei:
        await g.apply_guardrail(inputs={"texts": ["Şifre: Gizli123!"]}, request_data=rd, input_type="request")
    assert ei.value.status_code == 400 and ei.value.detail["entity"] == "SIFRE"
    infos = _infos(rd)
    assert len(infos) == 1 and infos[0]["guardrail_response"]["blocked"] == "SIFRE"
    assert "Gizli123" not in json.dumps(rd, ensure_ascii=False, default=str)


async def test_apply_guardrail_exception_value_free_500() -> None:
    g = G()

    def boom(text: str) -> Any:
        raise RuntimeError(f"iç hata: {text}")

    g.engine.analyze = boom  # type: ignore[method-assign]
    rd: dict[str, Any] = {"metadata": {}}
    with pytest.raises(HTTPException) as ei:
        await g.apply_guardrail(inputs={"texts": [f"TCKN {T1}"]}, request_data=rd, input_type="request")
    assert ei.value.status_code == 500 and T1 not in str(ei.value.detail)
    assert T1 not in json.dumps(rd, ensure_ascii=False, default=str)


async def test_apply_guardrail_response_fail_open_returns_inputs() -> None:
    g = G(revert_fail_mode="open")
    rd: dict[str, Any] = {"metadata": {}}
    out = await g.apply_guardrail(inputs={"texts": [f"TCKN {T1}"]}, request_data=rd, input_type="request")

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("x")

    g._reverter = boom  # type: ignore[method-assign]
    inp = {"texts": out["texts"]}
    assert await g.apply_guardrail(inputs=inp, request_data=rd, input_type="response") is inp


async def test_apply_guardrail_response_session_missing_closed() -> None:
    g = G()
    rd: dict[str, Any] = {"metadata": {}}
    out = await g.apply_guardrail(inputs={"texts": [f"TCKN {T1}"]}, request_data=rd, input_type="request")
    g.store._d.clear()
    with pytest.raises(HTTPException) as ei:
        await g.apply_guardrail(inputs={"texts": out["texts"]}, request_data=rd, input_type="response")
    assert ei.value.detail["error"] == "matriks_pii_session_missing"


async def test_apply_guardrail_no_pii_no_session() -> None:
    g = G()
    rd: dict[str, Any] = {"metadata": {}}
    out = await g.apply_guardrail(inputs={"texts": ["Merhaba"]}, request_data=rd, input_type="request")
    assert out["texts"] == ["Merhaba"] and SESSION_KEY not in rd["metadata"]
    assert len(g.store) == 0


# ================================================================== desteklenmeyen çağrı
async def test_unsupported_call_exception_fail_closed_scrubs() -> None:
    g = G()

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("x")

    g._analyze_refs = boom  # type: ignore[method-assign]
    d = {"model": "m", "metadata": {}, "prompt": f"Ben Ayşe Demir, TCKN {T1}"}
    with pytest.raises(HTTPException) as ei:
        await pre(g, d, "image_generation")
    assert ei.value.status_code == 500 and ei.value.detail["error"] == "matriks_pii_guardrail_failure"
    assert T1 not in d["prompt"] and "Ayşe" not in d["prompt"]


async def test_unsupported_call_exception_fail_open() -> None:
    g = G(fail_mode="open")

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("x")

    g._analyze_refs = boom  # type: ignore[method-assign]
    d = {"model": "m", "metadata": {}, "prompt": f"TCKN {T1}"}
    assert await pre(g, d, "image_generation") is None
    assert d["prompt"] == f"TCKN {T1}"


async def test_unsupported_call_logs_value_free_info() -> None:
    g = G()
    d = {"model": "m", "metadata": {}, "query": f"TCKN {T1}", "documents": ["Ayşe Demir"]}
    out = await pre(g, d, "rerank")
    assert out["query"] == "TCKN <TCKN_1>"
    infos = d["metadata"]["standard_logging_guardrail_information"]
    assert infos and infos[-1]["guardrail_response"]["unsupported_call"] is True
    no_secret(d)



# ================================================================== sır rotasyonu
async def test_token_signed_with_previous_secret_verifies() -> None:
    old, new = "o" * 40, "n" * 40
    g_old = G(session_secret=old)
    d = chat(f"TCKN {T1}")
    await pre(g_old, d)
    g_rot = G(session_secret=new, session_secret_previous=old)
    g_rot.store = g_old.store  # ortak depo
    out = await g_rot.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>"))
    assert out.choices[0].message.content == T1


async def test_previous_secret_removed_then_session_missing() -> None:
    old, new = "o" * 40, "n" * 40
    g_old = G(session_secret=old)
    d = chat(f"TCKN {T1}")
    await pre(g_old, d)
    g_new = G(session_secret=new)
    g_new.store = g_old.store
    with pytest.raises(HTTPException) as ei:
        await g_new.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>"))
    assert ei.value.detail["error"] == "matriks_pii_session_missing"


def test_previous_secret_min_length() -> None:
    with pytest.raises(ValueError, match="previous"):
        G(session_secret="n" * 40, session_secret_previous="kisa")


def test_version_hash_excludes_rotation_secrets_and_redis_url() -> None:
    from matriks_pii.config import TurkishPIIConfig

    a = TurkishPIIConfig.build({"session_secret": "a" * 40, "session_secret_previous": "b" * 40,
                                "session_store": {"redis_url": "redis://:p1@h/0", "encryption_key_previous": "x"}})
    b = TurkishPIIConfig.build({"session_secret": "c" * 40, "session_secret_previous": "d" * 40,
                                "session_store": {"redis_url": "redis://:p2@h/0", "encryption_key_previous": "y"}})
    assert a.version_hash == b.version_hash



# ================================================================== boyut sınırı ve executor
async def test_text_too_large_413_scrubbed() -> None:
    g = G(max_text_chars=2000)
    d = chat(f"Ben Ayşe Demir, TCKN {T1}. " + "x" * 3000)
    with pytest.raises(HTTPException) as ei:
        await pre(g, d)
    assert ei.value.status_code == 413
    assert ei.value.detail == {"error": "matriks_pii_text_too_large", "limit": 2000, "guardrail": "matriks-pii"}
    no_secret(d["messages"])


async def test_text_too_large_413_even_fail_open() -> None:
    g = G(max_text_chars=2000, fail_mode="open")
    d = chat(f"TCKN {T1} " + "x" * 3000)
    with pytest.raises(HTTPException) as ei:
        await pre(g, d)
    assert ei.value.status_code == 413 and T1 not in json.dumps(d, ensure_ascii=False, default=str)


async def test_request_too_large_413() -> None:
    g = G(max_text_chars=1100, max_request_chars=10_000)
    d = {"model": "m", "metadata": {}, "messages": [{"role": "user", "content": f"TCKN {T1} " + "y" * 1000}] * 20}
    with pytest.raises(HTTPException) as ei:
        await pre(g, d)
    assert ei.value.status_code == 413 and ei.value.detail["limit"] == 10_000


async def test_unsupported_call_too_large_413() -> None:
    g = G(max_text_chars=1100)
    d = {"model": "m", "metadata": {}, "prompt": f"TCKN {T1} " + "z" * 2000}
    with pytest.raises(HTTPException) as ei:
        await pre(g, d, "image_generation")
    assert ei.value.status_code == 413 and T1 not in d["prompt"]


async def test_dedicated_executor_used() -> None:
    import threading

    g = G(executor_threshold_chars=10)
    names: list[str] = []
    orig = g._analyze_refs

    def spy(refs: Any, texts: Any) -> Any:
        names.append(threading.current_thread().name)
        return orig(refs, texts)

    g._analyze_refs = spy  # type: ignore[method-assign]
    await pre(g, chat(f"Ben Ayşe Demir, TCKN {T1}"))
    assert names and names[0].startswith("matriks-pii")


async def test_logging_hook_runs_in_dedicated_executor() -> None:
    import threading

    g = G()
    names: list[str] = []
    orig = g.logging_hook

    def spy(kwargs: Any, result: Any, call_type: str) -> Any:
        names.append(threading.current_thread().name)
        return orig(kwargs, result, call_type)

    g.logging_hook = spy  # type: ignore[method-assign]
    await g.async_logging_hook({"messages": [{"role": "user", "content": "x"}]}, None, "acompletion")
    assert names[0].startswith("matriks-pii")



# ================================================================== önbellek sınırları
def test_cache_skips_large_text() -> None:
    from matriks_pii.config import TurkishPIIConfig
    from matriks_pii.engine import MAX_CACHED_TEXT_CHARS, PIIEngine

    eng = PIIEngine(TurkishPIIConfig.build({}))
    eng.analyze(f"TCKN {T1} " + "a " * (MAX_CACHED_TEXT_CHARS // 2 + 10))
    assert len(eng.cache) == 0
    eng.analyze(f"TCKN {T1}")
    assert len(eng.cache) == 1


def test_cache_total_spans_bound() -> None:
    from matriks_pii.engine import AnalysisCache
    from matriks_pii.recognizers.base import Span

    c = AnalysisCache(max_entries=100, ttl_seconds=60, max_total_spans=5)
    sp = [Span(0, 1, "KISI", "a", 0.9, "t", "a")] * 2
    for k in "abcd":
        c.put(k, list(sp))
    assert c.total_spans <= 5 and len(c) == 2 and c.get("a") is None and c.get("d") is not None
    c.put("big", [sp[0]] * 6)  # tek başına sınırı aşan liste önbelleğe girmez
    assert c.get("big") is None
    c.clear()
    assert c.total_spans == 0 and len(c) == 0


def test_cache_ttl_expiry_and_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    from matriks_pii import engine as eng_mod
    from matriks_pii.engine import AnalysisCache

    now = [100.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: now[0])
    c = AnalysisCache(max_entries=2, ttl_seconds=10)
    c.put("a", [])
    c.put("b", [])
    c.put("c", [])
    assert c.get("a") is None and c.get("c") == []
    now[0] += 11
    assert c.get("c") is None and len(c) == 1  # "b" süpürülmedi ama get'te düşer
    assert c.get("b") is None


def test_cache_disabled_zero_entries() -> None:
    from matriks_pii.config import TurkishPIIConfig
    from matriks_pii.engine import PIIEngine

    eng = PIIEngine(TurkishPIIConfig.build({"analysis_cache": {"max_entries": 0}}))
    a = eng.analyze(f"TCKN {T1}")
    assert eng.analyze(f"TCKN {T1}") is not a and len(eng.cache) == 0


def test_exclusion_zones_sorted_and_correct() -> None:
    from conftest import cfg_for

    from matriks_pii.recognizers.base import AnalysisContext

    ctx = AnalysisContext.build(cfg_for(), "x" * 200)
    for s, e in [(100, 120), (10, 30), (50, 60)]:
        ctx.add_exclusion(s, e)
    assert ctx.exclusion_zones == [(10, 30), (50, 60), (100, 120)]
    assert ctx.in_exclusion(25, 40) and ctx.in_exclusion(55, 56) and ctx.in_exclusion(0, 11)
    assert not ctx.in_exclusion(30, 50) and not ctx.in_exclusion(60, 100) and not ctx.in_exclusion(120, 200)


def test_many_invalid_iban_candidates_linear() -> None:
    import time

    from matriks_pii.config import TurkishPIIConfig
    from matriks_pii.engine import PIIEngine

    eng = PIIEngine(TurkishPIIConfig.build({"analysis_cache": {"max_entries": 0}}))
    text = " ".join(f"DE89 3704 0044 0532 0130 {i:02d}" for i in range(2000))
    t0 = time.perf_counter()
    eng.analyze(text)
    assert time.perf_counter() - t0 < 5



# ================================================================== denetim izi ve hata logu hijyeni
def test_audit_rotation_handle_reopen(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime as dt

    from matriks_pii import audit as audit_mod
    from matriks_pii.audit import AuditLog

    days = iter(["20261028", "20261028", "20261029"])

    class FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
            d = next(days, "20261029")
            return dt.datetime(int(d[:4]), int(d[4:6]), int(d[6:]), tzinfo=tz)

    monkeypatch.setattr(audit_mod._dt, "datetime", FakeDT)
    a = AuditLog(True, str(tmp_path / "audit.jsonl"), "h")
    a.write({"x": 1})
    a.write({"x": 2})
    a.close()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["audit.20261028.jsonl", "audit.20261029.jsonl"]


async def test_audit_write_error_rate_limited(tmp_path: Any, caplog: pytest.LogCaptureFixture) -> None:
    g = G(audit_log={"enabled": True, "path": str(tmp_path / "a.jsonl")})

    def boom(rec: Any) -> None:
        raise OSError("disk dolu")

    g.audit.write = boom  # type: ignore[method-assign]
    for _ in range(5):
        await pre(g, chat(f"TCKN {T1}"))
    errs = [r for r in caplog.records if "audit yazılamadı" in r.getMessage()]
    assert len(errs) == 1 and g.audit.counters["write_failed"] == 5


async def test_audit_score_buckets_and_guardrail_value_free(tmp_path: Any) -> None:
    g = G(audit_log={"enabled": True, "path": str(tmp_path / "a.jsonl")})
    await pre(g, chat(f"Ben Ayşe Demir, TCKN {T1}"))
    g.audit.close()
    recs = [json.loads(ln) for p in tmp_path.glob("a*.jsonl") for ln in p.read_text(encoding="utf-8").splitlines()]
    pre_rec = [r for r in recs if r["event"] == "pre_call"][0]
    assert pre_rec["guardrail"] == "matriks-pii"
    assert pre_rec["score_buckets"]["TCKN"] == {"0.9": 1} and "KISI" in pre_rec["score_buckets"]
    no_secret(recs)


async def test_debug_traceback_only_outside_production(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from matriks_pii import guardrail as gmod

    monkeypatch.setenv("MATRIKS_PII_DEBUG_TRACEBACK", "1")
    monkeypatch.setenv("LITELLM_MODE", "PRODUCTION")
    assert gmod._debug_traceback_enabled() is False
    monkeypatch.setenv("LITELLM_MODE", "DEV")
    assert gmod._debug_traceback_enabled() is True
    monkeypatch.delenv("MATRIKS_PII_DEBUG_TRACEBACK")
    assert gmod._debug_traceback_enabled() is False


async def test_error_log_has_type_only(caplog: pytest.LogCaptureFixture) -> None:
    g = G(fail_mode="open")

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError(f"ham değer {T1}")

    g._analyze_refs = boom  # type: ignore[method-assign]
    await pre(g, chat(f"TCKN {T1}"))
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in msgs and T1 not in msgs


async def test_cancelled_pre_call_leaves_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    class Slow(FakeRedis):
        async def set(self, k: str, v: bytes, ex: int | None = None) -> None:
            await asyncio.sleep(5)
            await super().set(k, v, ex)

    fake = Slow()
    g = _redis_g(monkeypatch, fake)
    task = asyncio.create_task(pre(g, chat(f"TCKN {T1}")))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake.d == {}


# ================================================================== hmac çakışması, sıfır dolgu, sürüm
def test_hmac_collision_extends_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import cfg_for

    from matriks_pii.engine import PIIEngine
    from matriks_pii.revert import Reverter
    from matriks_pii.session import MaskSession

    cfg = cfg_for({"placeholder_id": "hmac", "hash_secret": "h" * 40})
    real = MaskSession._hmac_id

    def colliding(self: Any, entity: str, normalized: str, length: int = 6) -> str:
        return "aaaaaa" if length == 6 else real(self, entity, normalized, length)

    monkeypatch.setattr(MaskSession, "_hmac_id", colliding)
    s = MaskSession(cfg)
    masked, *_ = PIIEngine(cfg).mask_text("Ayşe Demir ve Mehmet Kaya geldi", s)
    phs = list(s.map)
    assert len(phs) == 2 and phs[0] == "<KISI_aaaaaa>" and len(phs[1]) == len("<KISI_>") + 8
    assert Reverter(s.map, s.entities, cfg).revert(masked) == "Ayşe Demir ve Mehmet Kaya geldi"


def test_zero_padded_placeholder_reverts() -> None:
    from conftest import cfg_for

    from matriks_pii.revert import Reverter

    rev = Reverter({"<KISI_1>": "Ayşe Demir", "<TCKN_12>": T1}, {"<KISI_1>": "KISI", "<TCKN_12>": "TCKN"}, cfg_for())
    assert rev.revert("<KISI_01>'e ve <TCKN_012>") == f"Ayşe Demir'e ve {T1}"


def test_zero_padded_reserved_literal() -> None:
    from conftest import cfg_for

    from matriks_pii.session import MaskSession

    s = MaskSession(cfg_for())
    s.reserve_existing(["önceki <KISI_02> yanıtı"])
    assert "<KISI_2>" in s.reserved and s.counts["KISI"] == 2


def test_version_from_metadata() -> None:
    import matriks_pii

    assert matriks_pii.__version__ and matriks_pii.__version__ != "0.0.0"


# ================================================================== dry_run (gölge mod)
async def test_dry_run_request_unchanged_and_counts() -> None:
    g = G(dry_run=True)
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    before = json.dumps(d["messages"], ensure_ascii=False)
    assert await pre(g, d) is None
    assert json.dumps(d["messages"], ensure_ascii=False) == before
    assert SESSION_KEY not in d["metadata"] and len(g.store) == 0
    info = d["metadata"]["standard_logging_guardrail_information"][-1]["guardrail_response"]
    assert info["dry_run"] is True and info["would_mask"] == {"KISI": 1, "TCKN": 1}
    assert "Ayşe" not in json.dumps(info, ensure_ascii=False)


async def test_dry_run_block_not_enforced() -> None:
    g = G(dry_run=True, entities={"SIFRE": "BLOCK"})
    d = chat("Şifre: Gizli123! kaydet")
    assert await pre(g, d) is None
    info = d["metadata"]["standard_logging_guardrail_information"][-1]["guardrail_response"]
    assert info["would_block"] == "SIFRE" and "Gizli123" not in json.dumps(info, ensure_ascii=False)


async def test_dry_run_response_passthrough() -> None:
    g = G(dry_run=True)
    d = chat(f"TCKN {T1}")
    await pre(g, d)
    assert await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>")) is None


async def test_dry_run_counts_special_category_log() -> None:
    g = G(dry_run=True)
    d = chat("Müşterimiz Ayşe Demir CHP üyesi.")
    await pre(g, d)
    info = d["metadata"]["standard_logging_guardrail_information"][-1]["guardrail_response"]
    assert info["logged"] == {"OZEL_SIYASI": 1}


async def test_dry_run_audit_record(tmp_path: Any) -> None:
    g = G(dry_run=True, audit_log={"enabled": True, "path": str(tmp_path / "a.jsonl")})
    await pre(g, chat(f"TCKN {T1}"))
    g.audit.close()
    recs = [json.loads(ln) for p in tmp_path.glob("a*.jsonl") for ln in p.read_text(encoding="utf-8").splitlines()]
    assert recs[0]["dry_run"] is True and recs[0]["would_mask"] == {"TCKN": 1}
    no_secret(recs)


async def test_dry_run_apply_guardrail_returns_inputs() -> None:
    g = G(dry_run=True)
    inp = {"texts": [f"TCKN {T1}"]}
    assert await g.apply_guardrail(inputs=inp, request_data={"metadata": {}}, input_type="request") is inp


# ================================================================== İP-19 yanıt JSON biçimi korunur
async def test_response_json_content_keeps_formatting() -> None:
    g = G()
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    llm = '{\n  "ad": "<KISI_1>",\n  "tc": "<TCKN_1>"\n}'
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response(llm))
    assert out.choices[0].message.content == '{\n  "ad": "Ayşe Demir",\n  "tc": "' + T1 + '"\n}'


async def test_response_json_content_escapes_quotes() -> None:
    g = G()
    d = chat("Ben Ayşe Demir.")
    await pre(g, d)
    s = g.store._d[next(iter(g.store._d))][1]
    s.map["<KISI_1>"] = 'Ay"şe'  # tırnak içeren değer (sentetik)
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response('{"ad": "<KISI_1>"}'))
    content = out.choices[0].message.content
    assert json.loads(content) == {"ad": 'Ay"şe'} and content == '{"ad": "Ay\\"şe"}'


async def test_response_json_flag_off_restores_old_behaviour() -> None:
    g = G(response_json_preserve_format=False)
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None,
                                               response=model_response('{\n  "ad": "<KISI_1>"\n}'))
    assert out.choices[0].message.content == '{"ad":"Ayşe Demir"}'


async def test_response_non_json_brace_text_untouched_shape() -> None:
    g = G()
    d = chat("Ben Ayşe Demir.")
    await pre(g, d)
    llm = "{ bu JSON değil <KISI_1> }"
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response(llm))
    assert out.choices[0].message.content == "{ bu JSON değil Ayşe Demir }"


# ================================================================== İP-21 allow_list / deny_list
def test_allow_list_covers_span() -> None:
    from conftest import engine_for

    eng = engine_for({"allow_list": ["Can Bey", "Ahmet Yılmaz"]})
    assert eng.detected("Can Bey aradı.") == []
    assert [(s.entity, s.text) for s in eng.detected("Sayın AHMET YILMAZ geldi, TCKN " + T1)] == [("TCKN", T1)]
    # izin ifadesi span'i tamamen kapsamıyorsa (daha uzun ad) maskelenir
    assert [s.text for s in eng.detected("Ahmet Yılmaz Demir aradı.")] == ["Ahmet Yılmaz Demir"]


def test_allow_list_never_exempts_protected_entities() -> None:
    from conftest import engine_for

    eng = engine_for({"allow_list": ["kart numarası"]})
    assert [s.entity for s in eng.detected("kart numarası 4111 1111 1111 1111")] == ["KART"]


@pytest.mark.parametrize("bad", ["17291716060", "TR33 0006 1005 1978", "sk-abc", "x"])
def test_allow_list_rejects_id_like_entries(bad: str) -> None:
    from matriks_pii.config import TurkishPIIConfig

    with pytest.raises(ValueError):
        TurkishPIIConfig.build({"allow_list": [bad]})


def test_deny_list_masks_phrase_custom_entity() -> None:
    from conftest import engine_for

    eng = engine_for({"deny_list": [{"phrase": "Proje Kartal", "entity": "PROJE"}]})
    got = [(s.entity, s.text) for s in eng.detected("PROJE KARTAL ve proje kartal toplantısı; projekartal değil")]
    assert got == [("PROJE", "PROJE KARTAL"), ("PROJE", "proje kartal")]
    assert eng.cfg.action("PROJE") == "MASK" and eng.cfg.label("PROJE") == "PROJE"


async def test_deny_list_roundtrip_revert() -> None:
    g = G(deny_list=[{"phrase": "Proje Kartal", "entity": "PROJE"}])
    d = chat("Proje Kartal bütçesi onaylandı.")
    out = await pre(g, d)
    assert out["messages"][0]["content"] == "<PROJE_1> bütçesi onaylandı."
    back = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<PROJE_1>'ın bütçesi"))
    assert back.choices[0].message.content == "Proje Kartal'ın bütçesi"


def test_deny_list_entity_validation() -> None:
    from matriks_pii.config import TurkishPIIConfig

    with pytest.raises(ValueError):
        TurkishPIIConfig.build({"deny_list": [{"phrase": "x y", "entity": "proje adı"}]})
    cfg = TurkishPIIConfig.build({"deny_list": [{"phrase": "Gizli Sistem", "entity": "IC_SISTEM", "action": "BLOCK"}]})
    assert cfg.action("IC_SISTEM") == "BLOCK"


async def test_lone_surrogate_does_not_break_detection() -> None:
    """Tek başına UTF-16 vekil karakter (bozuk emoji) analiz ve maskelemeyi bozmaz."""
    text = "Ben Ayşe Demir \ud83d TCKN 17291716060"
    eng = PIIEngine(TurkishPIIConfig.build({}))
    assert sorted((s.entity, s.text) for s in eng.detected(text)) == [("KISI", "Ayşe Demir"), ("TCKN", "17291716060")]
    d = chat(text)
    await pre(G(), d)
    assert d["messages"][0]["content"] == "Ben <KISI_1> \ud83d TCKN <TCKN_1>"


async def test_proxy_body_copy_not_double_counted() -> None:
    """Proxy'nin gövde kopyası (proxy_server_request.body) da maskelenir ama sayım/denetim izi iki kez artmaz."""
    g = G()
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    d["proxy_server_request"] = {"body": json.loads(json.dumps({"messages": d["messages"]}))}
    await pre(g, d)
    assert d["proxy_server_request"]["body"]["messages"][0]["content"] == "Ben <KISI_1>, TCKN <TCKN_1>"
    sid = g._session_id(d)
    assert sid is not None
    session = await g.store.get(sid)
    assert dict(session.entity_counts) == {"KISI": 1, "TCKN": 1}


async def test_dry_run_never_blocks_on_too_large_or_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gölge mod (default_on: true ile tüm trafikte) hiçbir isteği 413/500 ile durdurmamalı; istek değişmez."""
    g = G(dry_run=True, max_text_chars=1024)
    d = chat(f"TCKN {T1} " + "x" * 2000)
    before = json.loads(json.dumps(d))
    assert await pre(g, d) is None and d["messages"] == before["messages"]
    g2 = G(dry_run=True)

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("analiz hatası")

    monkeypatch.setattr(g2.engine, "analyze", boom)
    monkeypatch.setattr(g2.engine, "analyze_with_prefix", boom)
    d2 = chat(f"TCKN {T1}")
    before2 = json.loads(json.dumps(d2))
    assert await pre(g2, d2) is None and d2["messages"] == before2["messages"]
