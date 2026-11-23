"""Gerçek Redis ile depo testleri (`pytest -m redis_live`; MATRIKS_PII_REDIS_URL yoksa atlanır). CI'da redis servisiyle çalışır."""

from __future__ import annotations

import asyncio
import base64
import os

import pytest
from conftest import cfg_for

from matriks_pii.session import MaskSession
from matriks_pii.store import RedisSessionStore, StoreUnavailable

pytestmark = pytest.mark.redis_live
URL = os.environ.get("MATRIKS_PII_REDIS_URL")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> RedisSessionStore:
    if not URL:
        pytest.skip("MATRIKS_PII_REDIS_URL tanımlı değil")
    pytest.importorskip("redis")
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    return RedisSessionStore(cfg_for({"session_store": {"backend": "memory", "redis_url": URL, "ttl_seconds": 60}}), "live")


def _sess() -> MaskSession:
    s = MaskSession(cfg_for())
    s.map["<KISI_1>"] = "Ayşe Demir"
    s.entities["<KISI_1>"] = "KISI"
    return s


async def test_live_roundtrip_and_getdel(store: RedisSessionStore) -> None:
    assert await store.ping()
    await store.put("a", _sess())
    raw = await store.r.get(store._k("a"))
    assert b"Ay" not in raw  # şifreli
    got = await store.pop("a")
    assert got is not None and got.map["<KISI_1>"] == "Ayşe Demir"
    assert await store.r.get(store._k("a")) is None


async def test_live_ttl_set(store: RedisSessionStore) -> None:
    await store.put("t", _sess())
    ttl = await store.r.ttl(store._k("t"))
    assert 0 < ttl <= 60
    await store.pop("t")


async def test_live_concurrent(store: RedisSessionStore) -> None:
    await asyncio.gather(*[store.put(f"c{i}", _sess()) for i in range(50)])
    res = await asyncio.gather(*[store.pop(f"c{i}") for i in range(50)])
    assert all(r is not None for r in res)


async def test_live_unreachable_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("redis")
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    st = RedisSessionStore(cfg_for({"session_store": {"redis_url": "redis://127.0.0.1:1/0", "redis_timeout_seconds": 0.2}}), "x")
    with pytest.raises(StoreUnavailable):
        await st.put("a", _sess())
