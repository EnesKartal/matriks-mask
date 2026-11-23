"""Test yardımcıları: sentetik değer üreticileri ve LiteLLM nesne kurucuları."""

from __future__ import annotations

import random
from typing import Any

from matriks_pii.recognizers.checksums import luhn_complete, make_iban, make_tckn, make_vkn

__all__ = ["luhn_complete", "make_iban", "make_tckn", "make_vkn", "model_response", "rand_tckn", "stream_chunks"]


def rand_tckn(rng: random.Random) -> str:
    return make_tckn(str(rng.randint(100_000_000, 999_999_999)))


def model_response(content: Any = None, tool_args: list[str] | None = None, reasoning: str | None = None, n: int = 1) -> Any:
    from litellm.types.utils import ChatCompletionMessageToolCall, Choices, Function, Message, ModelResponse

    choices = []
    for i in range(n):
        msg = Message(content=content if not isinstance(content, list) else content[i])
        if tool_args:
            msg.tool_calls = [
                ChatCompletionMessageToolCall(id=f"c{j}", type="function", function=Function(name="f", arguments=a))
                for j, a in enumerate(tool_args)
            ]
        if reasoning is not None:
            msg.reasoning_content = reasoning
        choices.append(Choices(index=i, message=msg, finish_reason="stop"))
    return ModelResponse(choices=choices)


def stream_chunks(text: str, size: int = 4, finish: bool = True) -> list[Any]:
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

    out = [ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=text[k : k + size]))]) for k in range(0, len(text), size)]
    if finish:
        out.append(ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=None), finish_reason="stop")]))
    return out


async def agen(items: list[Any]):
    for it in items:
        yield it


class FakeRedis:
    """redis.asyncio istemcisinin testte kullanılan alt kümesi; `down=True` iken her çağrı ConnectionError atar."""

    def __init__(self, with_getdel: bool = True) -> None:
        self.d: dict[str, bytes] = {}
        self.down = False
        self.calls: dict[str, int] = {}
        if not with_getdel:
            self.getdel = None  # type: ignore[assignment]

    def _hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1
        if self.down:
            raise ConnectionError("redis down")

    async def set(self, k: str, v: bytes, ex: int | None = None) -> None:
        self._hit("set")
        self.d[k] = v

    async def get(self, k: str) -> bytes | None:
        self._hit("get")
        return self.d.get(k)

    async def getdel(self, k: str) -> bytes | None:
        self._hit("getdel")
        return self.d.pop(k, None)

    async def expire(self, k: str, ttl: int) -> None:
        self._hit("expire")

    async def delete(self, k: str) -> None:
        self._hit("delete")
        self.d.pop(k, None)

    async def ping(self) -> bool:
        self._hit("ping")
        return True
