"""Eşzamanlılık ve akış kenar durumları: iş parçacığı güvenliği, eş zamanlı istek/akış izolasyonu, iki guardrail örneği,
n>1 akış, çoklu araç çağrısı, boş delta, HTML kaçışlı yer tutucu. Tüm değerler sentetiktir."""

from __future__ import annotations

import asyncio
import concurrent.futures
import random
from typing import Any

import pytest
from helpers import FakeRedis, agen, make_tckn, model_response, stream_chunks
from test_hooks import G, chat, pre
from test_prod_hardening import _redis_g

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import AnalysisCache, PIIEngine
from matriks_pii.guardrail import SESSION_KEY
from matriks_pii.recognizers.base import Span

NAMES = ["Ayşe Demir", "Mehmet Kaya", "Zeynep Şahin", "Ahmet Yılmaz", "Elif Çelik", "Burak Arslan"]


def _texts(n: int) -> list[str]:
    rng = random.Random(7)
    return [f"Müşteri {rng.choice(NAMES)} TCKN {make_tckn(str(rng.randint(100_000_000, 999_999_999)))} tel 0532 "
            f"{rng.randint(200, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)} not {i}" for i in range(n)]


def test_engine_thread_safety_matches_sequential() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"analysis_cache": {"max_entries": 64}}))
    texts = _texts(200)
    seq = [[(s.entity, s.start, s.end) for s in eng.analyze(t)] for t in texts]
    eng.cache.clear()
    with concurrent.futures.ThreadPoolExecutor(16) as ex:
        par = list(ex.map(lambda t: [(s.entity, s.start, s.end) for s in eng.analyze(t)], texts * 3))
    assert par == seq * 3


def test_analysis_cache_bounded_under_threads() -> None:
    c = AnalysisCache(max_entries=16, ttl_seconds=60, max_total_spans=40)
    sp = [Span(0, 1, "KISI", "a", 0.9, "t", "a")]

    def work(i: int) -> None:
        for k in range(200):
            c.put(f"{i}-{k}", sp * (k % 3 + 1))
            c.get(f"{i}-{k - 1}")

    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        list(ex.map(work, range(8)))
    assert len(c) <= 16 and c.total_spans <= 40
    assert c.total_spans == sum(len(v[1]) for v in c._d.values())


async def _roundtrip(g: Any, i: int, text: str) -> str:
    d = chat(text, litellm_call_id=f"call-{i}")
    await pre(g, d)
    masked = d["messages"][0]["content"]
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response(masked))
    return str(out.choices[0].message.content)


async def test_concurrent_requests_memory_no_crosstalk() -> None:
    g = G()
    texts = _texts(50)
    res = await asyncio.gather(*[_roundtrip(g, i, t) for i, t in enumerate(texts)])
    assert res == texts and len(g.store) == 0


async def test_concurrent_requests_redis_no_crosstalk(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    g = _redis_g(monkeypatch, fake)
    texts = _texts(50)
    res = await asyncio.gather(*[_roundtrip(g, i, t) for i, t in enumerate(texts)])
    assert res == texts and fake.d == {}


async def test_concurrent_streams_do_not_mix() -> None:
    g = G()
    texts = _texts(20)

    async def one(i: int, text: str) -> str:
        d = chat(text, stream=True, litellm_call_id=f"s-{i}")
        await pre(g, d)
        chunks = stream_chunks(d["messages"][0]["content"], size=3 + i % 5)
        out = ""
        async for item in g.async_post_call_streaming_iterator_hook(None, agen(chunks), d):
            await asyncio.sleep(0)
            for ch in item.choices:
                out += ch.delta.content or ""
        return out

    assert await asyncio.gather(*[one(i, t) for i, t in enumerate(texts)]) == texts


async def test_two_guardrail_instances_on_one_request() -> None:
    from matriks_pii.guardrail import TurkishPIIGuardrail

    a = TurkishPIIGuardrail(guardrail_name="matriks-pii", default_on=True, event_hook=["pre_call", "post_call"])
    b = TurkishPIIGuardrail(guardrail_name="matriks-pii-strict", default_on=True, event_hook=["pre_call", "post_call"],
                            profile="strict", hash_secret="0123456789abcdef0123456789abcdef")
    d = chat("Müşteri Ayşe Demir, TCKN 17291716060, Kürt kökenli.")
    await a.async_pre_call_hook(user_api_key_dict=None, cache=None, data=d, call_type="acompletion")
    await b.async_pre_call_hook(user_api_key_dict=None, cache=None, data=d, call_type="acompletion")
    assert set(d["metadata"][SESSION_KEY]) == {"matriks-pii", "matriks-pii-strict"}
    masked = d["messages"][-1]["content"]  # strict profil başa yer tutucu talimatı (system) ekler
    assert d["messages"][0]["role"] == "system"
    assert "Ayşe" not in masked and "Kürt" not in masked and "<OZEL_ETNIK_1>" in masked
    # yanıt ters sırada iki kancadan geçer (LiteLLM her guardrail'i ayrı çağırır)
    r1 = await b.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response(masked))
    r2 = await a.async_post_call_success_hook(data=d, user_api_key_dict=None, response=r1)
    assert r2.choices[0].message.content == "Müşteri Ayşe Demir, TCKN 17291716060, Kürt kökenli."


# ---------------------------------------------------------------- akış kenar durumları (kanca düzeyi)
def _chunk(content: str | None = None, index: int = 0, finish: str | None = None, tool: tuple[int, str] | None = None,
           choices: list[Any] | None = None) -> Any:
    from litellm.types.utils import ChatCompletionDeltaToolCall, Delta, Function, ModelResponseStream, StreamingChoices

    if choices is not None:
        return ModelResponseStream(choices=choices)
    delta = Delta(content=content)
    if tool is not None:
        delta.tool_calls = [ChatCompletionDeltaToolCall(index=tool[0], function=Function(arguments=tool[1]))]
    return ModelResponseStream(choices=[StreamingChoices(index=index, delta=delta, finish_reason=finish)])


async def _stream(g: Any, d: dict[str, Any], chunks: list[Any]) -> list[Any]:
    return [i async for i in g.async_post_call_streaming_iterator_hook(None, agen(chunks), d)]


async def test_stream_n2_choices_through_hook() -> None:
    g = G()
    d = chat("Ben Ayşe Demir, TCKN 17291716060", stream=True)
    await pre(g, d)
    chunks = [_chunk("A <KI", 0), _chunk("B <TC", 1), _chunk("SI_1>", 0), _chunk("KN_1>", 1),
              _chunk(None, 0, "stop"), _chunk(None, 1, "stop")]
    out: dict[int, str] = {}
    for item in await _stream(g, d, chunks):
        for ch in item.choices:
            out[ch.index] = out.get(ch.index, "") + (ch.delta.content or "")
    assert out == {0: "A Ayşe Demir", 1: "B 17291716060"}


async def test_stream_tool_calls_index_1_and_2() -> None:
    import json

    g = G()
    d = chat("TCKN 17291716060 ve Ayşe Demir", stream=True)
    await pre(g, d)
    chunks = [_chunk(tool=(1, '{"t":"<TC')), _chunk(tool=(2, '{"a":"<KI')), _chunk(tool=(1, 'KN_1>"}')),
              _chunk(tool=(2, 'SI_1>"}')), _chunk(None, 0, "tool_calls")]
    args: dict[int, str] = {}
    for item in await _stream(g, d, chunks):
        for ch in item.choices:
            for tc in ch.delta.tool_calls or []:
                args[tc.index] = args.get(tc.index, "") + (tc.function.arguments or "")
    assert json.loads(args[1]) == {"t": "17291716060"} and json.loads(args[2]) == {"a": "Ayşe Demir"}


async def test_stream_delta_content_none_then_finish() -> None:
    g = G()
    d = chat("TCKN 17291716060", stream=True)
    await pre(g, d)
    chunks = [_chunk("x <TCKN_"), _chunk(None), _chunk("1>"), _chunk(None, 0, "stop")]
    text = "".join(ch.delta.content or "" for item in await _stream(g, d, chunks) for ch in item.choices)
    assert text == "x 17291716060"


async def test_stream_500_empty_deltas_no_growth() -> None:
    g = G()
    d = chat("TCKN 17291716060", stream=True)
    await pre(g, d)
    chunks = [_chunk("")] * 500 + [_chunk("<TCKN_1>"), _chunk(None, 0, "stop")]
    items = await _stream(g, d, chunks)
    assert "".join(ch.delta.content or "" for it in items for ch in it.choices) == "17291716060"


async def test_stream_html_escaped_placeholder_through_hook() -> None:
    g = G()
    d = chat("Ben Ayşe Demir", stream=True)
    await pre(g, d)
    chunks = stream_chunks("Merhaba &lt;KISI_1&gt;!", size=2)
    text = "".join(ch.delta.content or "" for it in await _stream(g, d, chunks) for ch in it.choices)
    assert text == "Merhaba Ayşe Demir!"


async def test_stream_chunk_with_empty_choices_passes() -> None:
    g = G()
    d = chat("TCKN 17291716060", stream=True)
    await pre(g, d)
    usage_only = _chunk(choices=[])
    items = await _stream(g, d, [_chunk("<TCKN_1"), usage_only, _chunk(">"), _chunk(None, 0, "stop")])
    assert usage_only in items
    assert "".join(ch.delta.content or "" for it in items for ch in it.choices) == "17291716060"


async def test_stream_usage_only_chunk_order_with_trailing_flush() -> None:
    g = G()
    d = chat("TCKN 17291716060", stream=True)
    await pre(g, d)
    usage_only = _chunk(choices=[])
    # finish_reason gelmeden akış biter: tamponda kalan metin usage parçasından ÖNCE yayılmalı
    items = await _stream(g, d, [_chunk("Kimlik <TCK"), _chunk("N_1> tamam"), usage_only])
    assert items[-1] is usage_only
    assert "".join(ch.delta.content or "" for it in items[:-1] for ch in it.choices) == "Kimlik 17291716060 tamam"


async def test_stream_chunk_with_choices_none() -> None:
    g = G()
    d = chat("TCKN 17291716060", stream=True)
    await pre(g, d)
    odd = _chunk("x")
    odd.choices = None  # bazı sağlayıcı uyarlayıcıları usage/heartbeat parçasında choices=None gönderir
    items = await _stream(g, d, [_chunk("<TCKN_1"), odd, _chunk(">"), _chunk(None, 0, "stop")])
    assert odd in items
    assert "".join(ch.delta.content or "" for it in items if it.choices for ch in it.choices) == "17291716060"
