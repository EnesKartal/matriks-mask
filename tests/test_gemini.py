"""Gemini native streamGenerateContent: ham SSE bayt çerçeveleri (`data: {...}\\n\\n`) üzerinde geri çevirme.

LiteLLM 1.106.5 bu rotada guardrail akış kancasına ham upstream baytlarını verir (çerçeve hizalaması kancadan sonra).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import cfg_for
from fastapi import HTTPException
from helpers import agen
from test_hooks import G, pre

from matriks_pii.revert import Reverter
from matriks_pii.streaming import StreamProcessor

MAP = {"<KISI_1>": "Ayşe Demir", "<TCKN_1>": "17291716060"}
ENTS = {"<KISI_1>": "KISI", "<TCKN_1>": "TCKN"}


def _frame(text: str | None = None, finish: str | None = None, index: int = 0, extra_parts: list[Any] | None = None,
           usage: bool = False, crlf: bool = False) -> bytes:
    cand: dict[str, Any] = {"content": {"role": "model", "parts": ([{"text": text}] if text is not None else []) + (extra_parts or [])},
                            "index": index}
    if finish:
        cand["finishReason"] = finish
    obj: dict[str, Any] = {"candidates": [cand]}
    if usage:
        obj["usageMetadata"] = {"promptTokenCount": 3, "candidatesTokenCount": 5}
    sep = "\r\n\r\n" if crlf else "\n\n"
    return ("data: " + json.dumps(obj, ensure_ascii=False) + sep).encode("utf-8")


def _proc(revert_obj: Any = None) -> StreamProcessor:
    return StreamProcessor(Reverter(MAP, ENTS, cfg_for()), 48, revert_obj=revert_obj)


def _texts(outs: list[Any]) -> dict[int, str]:
    raw = b"".join(o if isinstance(o, bytes) else o.encode() for o in outs).decode("utf-8")
    acc: dict[int, str] = {}
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith("data:"):
            for c in json.loads(line[5:]).get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    if "text" in p:
                        acc[c.get("index", 0)] = acc.get(c.get("index", 0), "") + p["text"]
    return acc


def _run(chunks: list[bytes], proc: StreamProcessor | None = None) -> list[Any]:
    proc = proc or _proc()
    outs: list[Any] = []
    for c in chunks:
        outs += proc.process(c)
    return outs + proc.final_items()


FULL = "Merhaba <KISI_1>'e, TCKN <TCKN_1> doğrulandı. Şükrü İş'te."
EXPECTED = "Merhaba Ayşe Demir'e, TCKN 17291716060 doğrulandı. Şükrü İş'te."


def _frames(text: str, size: int, crlf: bool = False) -> bytes:
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    return b"".join(_frame(p, finish="STOP" if k == len(pieces) - 1 else None, crlf=crlf) for k, p in enumerate(pieces))


@pytest.mark.parametrize("text_size", [1, 3, 7, 50])
@pytest.mark.parametrize("byte_size", [1, 2, 5, 13, 64, 10_000])
def test_gemini_sse_every_byte_split(text_size: int, byte_size: int) -> None:
    raw = _frames(FULL, text_size)
    outs = _run([raw[i : i + byte_size] for i in range(0, len(raw), byte_size)])
    assert _texts(outs) == {0: EXPECTED}
    assert b"KISI_1" not in b"".join(o for o in outs if isinstance(o, bytes))


def test_gemini_crlf_frames() -> None:
    raw = _frames(FULL, 4, crlf=True)
    assert _texts(_run([raw[i : i + 9] for i in range(0, len(raw), 9)])) == {0: EXPECTED}


def test_gemini_str_frames() -> None:
    raw = _frames(FULL, 5).decode("utf-8")
    proc = _proc()
    outs: list[Any] = []
    for i in range(0, len(raw), 11):
        outs += proc.process(raw[i : i + 11])
    outs += proc.final_items()
    assert all(isinstance(o, str) for o in outs) and _texts(outs) == {0: EXPECTED}


def test_gemini_no_finish_reason_final_items_flush() -> None:
    raw = _frame("Merhaba <KI") + _frame("SI_1>")  # akış finishReason gelmeden bitti
    outs = _run([raw])
    assert _texts(outs) == {0: "Merhaba Ayşe Demir"}


def test_gemini_usage_frame_passes() -> None:
    raw = _frame("x <TCKN_1>", finish="STOP") + b'data: {"usageMetadata":{"totalTokenCount":9}}\n\n'
    outs = _run([raw])
    assert b"usageMetadata" in b"".join(o for o in outs if isinstance(o, bytes))
    assert _texts(outs) == {0: "x 17291716060"}


def test_gemini_two_candidates_independent() -> None:
    raw = (_frame("A <KI", index=0) + _frame("B <TC", index=1) + _frame("SI_1>", index=0, finish="STOP")
           + _frame("KN_1>", index=1, finish="STOP"))
    assert _texts(_run([raw])) == {0: "A Ayşe Demir", 1: "B 17291716060"}


def test_gemini_function_call_args_reverted() -> None:
    g = G()

    revert_obj = g._revert_obj(Reverter(MAP, ENTS, g.cfg))
    raw = _frame(None, finish="STOP", extra_parts=[{"functionCall": {"name": "f", "args": {"tc": "<TCKN_1>"}}}])
    outs = _run([raw], _proc(revert_obj))
    body = b"".join(o for o in outs if isinstance(o, bytes)).decode()
    assert '"tc":"17291716060"' in body.replace(" ", "")


def test_gemini_drain_raw_keeps_order() -> None:
    proc = _proc()
    first = proc.process(_frame("abc <KISI_1> def <KI"))
    drained = proc.drain_raw()
    assert _texts(first + drained) == {0: "abc Ayşe Demir def <KI"}


def test_gemini_event_line_preserved() -> None:
    raw = b'event: message\ndata: ' + json.dumps({"candidates": [{"content": {"parts": [{"text": "<KISI_1>"}]},
                                                                  "finishReason": "STOP"}]}).encode() + b"\n\n"
    outs = _run([raw])
    body = b"".join(o for o in outs if isinstance(o, bytes)).decode()
    assert body.startswith("event: message\ndata: ") and "Ayşe Demir" in body


# ---------------------------------------------------------------- kanca düzeyinde uçtan uca
async def _hook(chunks: list[bytes], **cfg: Any) -> list[Any]:
    g = G(**cfg)
    data = {"model": "g", "metadata": {}, "contents": [{"role": "user", "parts": [{"text": "Ben Ayşe Demir, TCKN 17291716060"}]}]}
    data = await pre(g, data, "agenerate_content_stream")
    data["stream"] = True
    data["_litellm_raw_sse_stream"] = True
    return [i async for i in g.async_post_call_streaming_iterator_hook(None, agen(chunks), data)]


async def test_hook_gemini_stream_roundtrip() -> None:
    raw = _frames(FULL, 3)
    outs = await _hook([raw[i : i + 7] for i in range(0, len(raw), 7)])
    assert _texts(outs) == {0: EXPECTED}


async def test_hook_gemini_stream_session_missing_closed() -> None:
    g = G()
    data = {"model": "g", "metadata": {}, "contents": [{"role": "user", "parts": [{"text": "TCKN 17291716060"}]}]}
    data = await pre(g, data, "agenerate_content_stream")
    g.store._d.clear()
    with pytest.raises(HTTPException):
        async for _ in g.async_post_call_streaming_iterator_hook(None, agen([_frame("x")]), {**data, "stream": True}):
            pass


def test_gemini_truncated_placeholder_stripped_at_end() -> None:
    raw = _frame("Merhaba <KI") + _frame("SI_1")  # akış yarım yer tutucuyla bitti → kırpılır (truncated_placeholder: strip)
    assert _texts(_run([raw])) == {0: "Merhaba "}


# ---------------------------------------------------------------- SDK benzeri nesneler (öznitelik erişimi, tuple parts)
async def test_gemini_attribute_objects_with_tuple_parts() -> None:
    from types import SimpleNamespace as NS

    g = G()
    content = NS(role="user", parts=(NS(text="Ben Ayşe Demir, TCKN 17291716060"),))
    data: dict[str, Any] = {"model": "g", "metadata": {}, "contents": [content]}
    data = await pre(g, data, "agenerate_content")
    parts = data["contents"][0].parts
    assert isinstance(parts, list) and parts[0].text == "Ben <KISI_1>, TCKN <TCKN_1>"
    resp = NS(candidates=[NS(content=NS(role="model", parts=[NS(text="Merhaba <KISI_1>, <TCKN_1>")]), index=0)])
    out = await g.async_post_call_success_hook(data=data, user_api_key_dict=None, response=resp)
    out = resp if out is None else out
    assert out.candidates[0].content.parts[0].text == "Merhaba Ayşe Demir, 17291716060"


async def test_gemini_sdk_types_roundtrip() -> None:
    types = pytest.importorskip("google.genai.types")
    g = G()
    data: dict[str, Any] = {"model": "g", "metadata": {},
                            "contents": [types.Content(role="user", parts=[types.Part(text="Ben Ayşe Demir, TCKN 17291716060")])]}
    data = await pre(g, data, "agenerate_content")
    assert data["contents"][0].parts[0].text == "Ben <KISI_1>, TCKN <TCKN_1>"
    resp = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=[types.Part(text="Merhaba <KISI_1>")]), index=0)])
    out = await g.async_post_call_success_hook(data=data, user_api_key_dict=None, response=resp)
    out = resp if out is None else out
    assert out.candidates[0].content.parts[0].text == "Merhaba Ayşe Demir"
