"""Oturum deposu: bellek (TTL + LRU) veya şifreli Redis."""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .config import TurkishPIIConfig
    from .session import MaskSession


class StoreUnavailable(RuntimeError):
    """Oturum deposuna erişilemiyor (zaman aşımı, bağlantı hatası, devre açık). İleti değer içermez."""


class SessionStore(Protocol):
    async def put(self, sid: str, session: MaskSession) -> None: ...
    async def get(self, sid: str) -> MaskSession | None: ...
    async def pop(self, sid: str) -> MaskSession | None: ...
    async def ping(self) -> bool: ...


class MemorySessionStore:
    def __init__(self, ttl_seconds: int, max_sessions: int) -> None:
        self.ttl = ttl_seconds
        self.max = max_sessions
        self._d: OrderedDict[str, tuple[float, MaskSession]] = OrderedDict()
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def __len__(self) -> int:
        return len(self._d)

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        dead = [k for k, (ts, _) in self._d.items() if now - ts > self.ttl]
        for k in dead:
            self._d.pop(k, None)

    async def put(self, sid: str, session: MaskSession) -> None:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            self._d[sid] = (now, session)
            self._d.move_to_end(sid)
            while len(self._d) > self.max:
                self._d.popitem(last=False)

    async def get(self, sid: str) -> MaskSession | None:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            v = self._d.get(sid)
            if v is None:
                return None
            ts, s = v
            if now - ts > self.ttl:
                self._d.pop(sid, None)
                return None
            self._d[sid] = (now, s)  # TTL yenile
            self._d.move_to_end(sid)
            return s

    async def pop(self, sid: str) -> MaskSession | None:
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            v = self._d.pop(sid, None)
        if v is None or now - v[0] > self.ttl:
            return None
        return v[1]

    async def ping(self) -> bool:
        return True


_FAIL_LIMIT = 3
_OPEN_SECONDS = 10.0


class RedisSessionStore:
    """Değer AES-GCM ile şifrelenir; anahtar session_store.encryption_key veya MATRIKS_PII_STORE_KEY (32 bayt, base64)."""

    def __init__(self, cfg: TurkishPIIConfig, namespace: str, client: Any = None) -> None:
        self.cfg = cfg
        self.ns = namespace
        self.ttl = cfg.session_store.ttl_seconds
        key_b64 = cfg.session_store.encryption_key or os.environ.get("MATRIKS_PII_STORE_KEY")
        if not key_b64:
            raise ValueError("redis session_store için MATRIKS_PII_STORE_KEY (32 bayt base64) zorunlu")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(_decode_key(key_b64, "MATRIKS_PII_STORE_KEY"))
        prev_b64 = cfg.session_store.encryption_key_previous or os.environ.get("MATRIKS_PII_STORE_KEY_PREVIOUS")
        # anahtar rotasyonu: eski anahtarla şifrelenmiş oturumlar TTL boyunca çözülebilir; yazma hep güncel anahtarla
        self._aead_prev = AESGCM(_decode_key(prev_b64, "MATRIKS_PII_STORE_KEY_PREVIOUS")) if prev_b64 else None
        if client is None:
            import redis.asyncio as redis

            t = cfg.session_store.redis_timeout_seconds
            opts: dict[str, Any] = {"socket_timeout": t, "socket_connect_timeout": t, "retry_on_timeout": False,
                                    "health_check_interval": 30}
            url = cfg.session_store.redis_url
            if url:
                client = redis.from_url(url, **opts)
            else:
                client = redis.Redis(
                    host=os.environ.get("REDIS_HOST", "localhost"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    password=os.environ.get("REDIS_PASSWORD") or None,
                    **opts,
                )
        self.r = client
        self._fail = 0
        self._open_until = 0.0

    def _k(self, sid: str) -> str:
        return f"matriks_pii:{self.ns}:{sid}"

    def _enc(self, session: MaskSession) -> bytes:
        nonce = os.urandom(12)
        pt = json.dumps(session.to_dict(), ensure_ascii=False).encode("utf-8")
        return nonce + self._aead.encrypt(nonce, pt, self.ns.encode())

    def _dec(self, blob: bytes) -> MaskSession | None:
        """Çözülemeyen blob (anahtar rotasyonu, bozulma) istisna değil `None` → kanca 'oturum yok' yoluna gider."""
        from cryptography.exceptions import InvalidTag

        from .session import MaskSession

        try:
            try:
                pt = self._aead.decrypt(blob[:12], blob[12:], self.ns.encode())
            except InvalidTag:
                if self._aead_prev is None:
                    raise
                pt = self._aead_prev.decrypt(blob[:12], blob[12:], self.ns.encode())
            return MaskSession.from_dict(self.cfg, json.loads(pt.decode("utf-8")))
        except Exception as e:
            logging.getLogger("matriks_pii").error("matriks_pii: oturum çözülemedi (%s); oturum yok sayılıyor", type(e).__name__)
            return None

    # ------------------------------------------------------------------ devre kesici
    async def _call(self, fn: Any, *args: Any, **kw: Any) -> Any:
        """Redis çağrısı: art arda `_FAIL_LIMIT` hatada devre `_OPEN_SECONDS` açılır (gidiş-dönüş yapmadan hızlı hata)."""
        if time.monotonic() < self._open_until:
            raise StoreUnavailable("circuit_open")
        try:
            res = await fn(*args, **kw)
        except Exception as e:
            self._fail += 1
            if self._fail >= _FAIL_LIMIT:
                self._open_until = time.monotonic() + _OPEN_SECONDS
            raise StoreUnavailable(type(e).__name__) from None
        self._fail = 0
        return res

    async def put(self, sid: str, session: MaskSession) -> None:
        await self._call(self.r.set, self._k(sid), self._enc(session), ex=self.ttl)

    async def get(self, sid: str) -> MaskSession | None:
        blob = await self._call(self.r.get, self._k(sid))
        if blob is None:
            return None
        if self.cfg.session_store.refresh_ttl:
            await self._call(self.r.expire, self._k(sid), self.ttl)
        return self._dec(blob)

    async def pop(self, sid: str) -> MaskSession | None:
        k = self._k(sid)
        getdel = getattr(self.r, "getdel", None)
        if callable(getdel):  # Redis >= 6.2: tek atomik gidiş-dönüş
            blob = await self._call(getdel, k)
        else:
            blob = await self._call(self.r.get, k)
            await self._call(self.r.delete, k)
        return self._dec(blob) if blob is not None else None

    async def ping(self) -> bool:
        return bool(await self._call(self.r.ping))


def _decode_key(key_b64: str, name: str) -> bytes:
    try:
        key = base64.b64decode(key_b64, validate=True)
    except ValueError:
        raise ValueError(f"{name} geçerli base64 olmalı") from None
    if len(key) != 32:
        raise ValueError(f"{name} 32 bayt olmalı")
    return key


def build_store(cfg: TurkishPIIConfig, namespace: str) -> SessionStore:
    if cfg.session_store.backend == "redis":
        return RedisSessionStore(cfg, namespace)
    return MemorySessionStore(cfg.session_store.ttl_seconds, cfg.session_store.max_sessions)


