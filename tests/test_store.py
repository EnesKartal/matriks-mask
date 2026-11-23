"""Oturum deposu birim testleri: bellek TTL/LRU, Redis devre kesici, şifreleme. Tüm değerler sentetiktir."""

from __future__ import annotations

import base64
import os
from typing import Any

import pytest
from conftest import cfg_for
from helpers import FakeRedis

from matriks_pii import store as store_mod
from matriks_pii.config import TurkishPIIConfig
from matriks_pii.session import MaskSession
from matriks_pii.store import MemorySessionStore, RedisSessionStore, StoreUnavailable


def _sess(value: str = "Ayşe Demir") -> MaskSession:
    s = MaskSession(cfg_for())
    s.map["<KISI_1>"] = value
    s.entities["<KISI_1>"] = "KISI"
    return s


def _redis(monkeypatch: pytest.MonkeyPatch, fake: Any, **cfg: Any) -> RedisSessionStore:
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    return RedisSessionStore(cfg_for(cfg), "ns", client=fake)


# ---------------------------------------------------------------- bellek
async def test_memory_store_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(store_mod.time, "monotonic", lambda: now[0])
    st = MemorySessionStore(ttl_seconds=60, max_sessions=10)
    await st.put("a", _sess())
    now[0] += 59
    assert await st.get("a") is not None  # get TTL'i yeniler
    now[0] += 61
    assert await st.get("a") is None


async def test_memory_store_pop_after_ttl_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(store_mod.time, "monotonic", lambda: now[0])
    st = MemorySessionStore(ttl_seconds=60, max_sessions=10)
    await st.put("a", _sess())
    now[0] += 61
    assert await st.pop("a") is None


async def test_memory_store_max_sessions_eviction() -> None:
    st = MemorySessionStore(ttl_seconds=600, max_sessions=3)
    for k in "abcd":
        await st.put(k, _sess(k))
    assert len(st) == 3 and await st.get("a") is None and await st.get("d") is not None


async def test_memory_store_sweep_on_get_and_pop(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(store_mod.time, "monotonic", lambda: now[0])
    st = MemorySessionStore(ttl_seconds=60, max_sessions=100)
    for k in "abc":
        await st.put(k, _sess())
    now[0] += 120  # süpürme aralığı (60 s) ve TTL geçti
    await st.get("zzz")
    assert len(st) == 0


async def test_memory_ping() -> None:
    assert await MemorySessionStore(60, 10).ping() is True


# ---------------------------------------------------------------- redis
async def test_redis_roundtrip_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    st = _redis(monkeypatch, fake)
    await st.put("x", _sess())
    assert all("Ayşe".encode() not in v for v in fake.d.values())
    got = await st.get("x")
    assert got is not None and got.map == {"<KISI_1>": "Ayşe Demir"}
    assert await st.ping() is True


async def test_circuit_breaker_opens_after_3_failures_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(store_mod.time, "monotonic", lambda: now[0])
    fake = FakeRedis()
    st = _redis(monkeypatch, fake)
    fake.down = True
    for _ in range(3):
        with pytest.raises(StoreUnavailable):
            await st.get("x")
    n_calls = fake.calls["get"]
    with pytest.raises(StoreUnavailable, match="circuit_open"):
        await st.get("x")
    assert fake.calls["get"] == n_calls  # devre açıkken Redis'e gidilmez
    fake.down = False
    now[0] += 11
    assert await st.get("x") is None  # devre kapandı
    assert st._fail == 0


async def test_store_unavailable_message_is_value_free(monkeypatch: pytest.MonkeyPatch) -> None:
    class Leaky(FakeRedis):
        async def set(self, k: str, v: bytes, ex: int | None = None) -> None:
            raise RuntimeError("redis://:parola123@host hata Ayşe Demir")

    st = _redis(monkeypatch, Leaky())
    with pytest.raises(StoreUnavailable) as ei:
        await st.put("x", _sess())
    assert "parola123" not in str(ei.value) and "Ayşe" not in str(ei.value)


async def test_redis_key_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = cfg_for()
    monkeypatch.delenv("MATRIKS_PII_STORE_KEY", raising=False)
    with pytest.raises(ValueError, match="zorunlu"):
        RedisSessionStore(cfg, "ns", client=FakeRedis())
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", "***")
    with pytest.raises(ValueError, match="base64"):
        RedisSessionStore(cfg, "ns", client=FakeRedis())
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(b"x" * 31).decode())
    with pytest.raises(ValueError, match="32 bayt"):
        RedisSessionStore(cfg, "ns", client=FakeRedis())


# ---------------------------------------------------------------- sertleştirme ve rotasyon
def test_redis_timeout_kwargs_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    import redis.asyncio as redis

    seen: dict[str, Any] = {}

    def fake_from_url(url: str, **kw: Any) -> FakeRedis:
        seen.update(kw)
        return FakeRedis()

    monkeypatch.setattr(redis, "from_url", fake_from_url)
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    RedisSessionStore(cfg_for({"session_store": {"redis_url": "redis://h:1/0", "redis_timeout_seconds": 0.5}}), "ns")
    assert seen["socket_timeout"] == 0.5 and seen["socket_connect_timeout"] == 0.5
    assert seen["retry_on_timeout"] is False


async def test_redis_corrupt_blob_returns_none_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    st = _redis(monkeypatch, fake)
    fake.d[st._k("x")] = b"0" * 40
    assert await st.get("x") is None
    fake.d[st._k("y")] = b"kisa"
    assert await st.pop("y") is None


async def test_redis_previous_key_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    old = base64.b64encode(os.urandom(32)).decode()
    new = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", old)
    st_old = RedisSessionStore(cfg_for(), "ns", client=fake)
    await st_old.put("x", _sess())
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", new)
    st_new_only = RedisSessionStore(cfg_for(), "ns", client=fake)
    assert await st_new_only.get("x") is None  # eski anahtar yokken çözülemez → oturum yok
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY_PREVIOUS", old)
    st_rot = RedisSessionStore(cfg_for(), "ns", client=fake)
    got = await st_rot.get("x")
    assert got is not None and got.map["<KISI_1>"] == "Ayşe Demir"
    await st_rot.put("z", _sess("Mehmet"))  # yazma güncel anahtarla
    assert await st_new_only.get("z") is not None


async def test_redis_pop_uses_getdel_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    st = _redis(monkeypatch, fake)
    await st.put("x", _sess())
    assert (await st.pop("x")) is not None
    assert fake.calls.get("getdel") == 1 and "delete" not in fake.calls and fake.d == {}


async def test_redis_pop_fallback_get_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis(with_getdel=False)
    st = _redis(monkeypatch, fake)
    await st.put("x", _sess())
    assert (await st.pop("x")) is not None
    assert fake.calls.get("delete") == 1 and fake.d == {}


async def test_redis_refresh_ttl_off_skips_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    st = _redis(monkeypatch, fake, session_store={"refresh_ttl": False})
    await st.put("x", _sess())
    await st.get("x")
    assert "expire" not in fake.calls


def test_require_tls_rejects_plain_url() -> None:
    with pytest.raises(ValueError, match="rediss"):
        TurkishPIIConfig.build({"session_store": {"require_tls": True, "redis_url": "redis://h:6379/0"}})
    TurkishPIIConfig.build({"session_store": {"require_tls": True, "redis_url": "rediss://h:6380/0"}})


def test_previous_key_must_be_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("MATRIKS_PII_STORE_KEY_PREVIOUS", "QUJD")
    with pytest.raises(ValueError, match="PREVIOUS 32 bayt"):
        RedisSessionStore(cfg_for(), "ns", client=FakeRedis())
