"""Ham SSE bayt akışında çok baytlı UTF-8 karakter bölünmesi ve CRLF sınırları.

LiteLLM 1.106.5 `/v1/messages` (ve Gemini native) akışında guardrail'e ham upstream baytlarını verir; parça sınırı bir
Türkçe harfin (ş, İ, ğ — 2 bayt) ortasına düşebilir. Bu testler her bölme boyutunda ve ofsetinde birleşik çıktının tam
geri çevirmeye eşit olduğunu ve yer tutucunun istemciye çıkmadığını doğrular.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import cfg_for
from fastapi import HTTPException
from helpers import agen

from matriks_pii.revert import Reverter
from matriks_pii.streaming import StreamProcessor

TEXT = "Şükrü için <KISI_1> ile görüştüm, İş çıkışı <KISI_1>'e söyle; ğüşiöç <KISI_1>"
EXPECTED = "Şükrü için Ayşe Demir ile görüştüm, İş çıkışı Ayşe Demir'e söyle; ğüşiöç Ayşe Demir"


def _sse(text: str, crlf: bool = False) -> bytes:
    ev1 = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    s = (
        f"event: content_block_delta\ndata: {json.dumps(ev1, ensure_ascii=False)}\n\n"
        'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
    )
    if crlf:
        s = s.replace("\n", "\r\n")
    return s.encode("utf-8")


def _proc() -> StreamProcessor:
    rev = Reverter({"<KISI_1>": "Ayşe Demir"}, {"<KISI_1>": "KISI"}, cfg_for())
    return StreamProcessor(rev, 48)


def _text_of(outs: list[Any]) -> str:
    joined = b"".join(o if isinstance(o, bytes) else o.encode("utf-8") for o in outs).decode("utf-8")
    out = ""
    for line in joined.replace("\r\n", "\n").split("\n"):
        if line.startswith("data:"):
            d = json.loads(line[5:])
            if d.get("type") == "content_block_delta":
                out += d["delta"].get("text", "")
    return out


def _run(chunks: list[bytes]) -> list[Any]:
    proc = _proc()
    outs: list[Any] = []
    for c in chunks:
        outs += proc.process(c)
    outs += proc.final_items()
    return outs


@pytest.mark.parametrize("size", range(1, 65))
def test_anthropic_sse_every_chunk_size(size: int) -> None:
    raw = _sse(TEXT)
    outs = _run([raw[i : i + size] for i in range(0, len(raw), size)])
    assert _text_of(outs) == EXPECTED
    assert "KISI_1" not in b"".join(o if isinstance(o, bytes) else o.encode() for o in outs).decode("utf-8")


def test_anthropic_sse_every_two_way_split() -> None:
    raw = _sse(TEXT)
    for k in range(1, len(raw)):
        outs = _run([raw[:k], raw[k:]])
        assert _text_of(outs) == EXPECTED, k


@pytest.mark.parametrize("size", [1, 2, 3, 7, 50])
def test_crlf_sse_every_chunk_size(size: int) -> None:
    raw = _sse(TEXT, crlf=True)
    outs = _run([raw[i : i + size] for i in range(0, len(raw), size)])
    assert _text_of(outs) == EXPECTED


def test_crlf_split_across_chunks_emits_event_before_end() -> None:
    raw = _sse("merhaba <KISI_1>", crlf=True)
    cut = raw.index(b"\r\n\r\n") + 1  # "\r" | "\n\r\n" sınırı
    proc = _proc()
    first = proc.process(raw[:cut]) + proc.process(raw[cut : cut + 2]) + proc.process(raw[cut + 2 :])
    assert first, "olay akış sonu beklenmeden yayılmalı"
    assert _text_of(first + proc.final_items()) == "merhaba Ayşe Demir"


def test_str_chunks_unchanged_behaviour() -> None:
    raw = _sse(TEXT).decode("utf-8")
    proc = _proc()
    outs: list[Any] = []
    for i in range(0, len(raw), 3):
        outs += proc.process(raw[i : i + 3])
    outs += proc.final_items()
    assert all(isinstance(o, str) for o in outs)
    assert _text_of(outs) == EXPECTED


def test_invalid_utf8_raises_in_processor() -> None:
    proc = _proc()
    with pytest.raises(UnicodeDecodeError):
        proc.process(b"event: x\ndata: \xff\xfe\n\n")


def test_drain_raw_keeps_buffered_text_order() -> None:
    raw = _sse("abc <KISI_1> def <KI")  # tamponda yarım yer tutucu kalır
    proc = _proc()
    first = proc.process(raw[: raw.index(b"event: content_block_stop")])
    drained = proc.drain_raw()
    txt = _text_of(first + drained)
    assert txt == "abc Ayşe Demir def <KI"


# ---------------------------------------------------------------- kanca düzeyi
async def _hook_stream(cfg: dict[str, Any], chunks: list[bytes]) -> list[Any]:
    from test_hooks import G, pre

    g = G(**cfg)
    data = await pre(g, {"model": "c", "messages": [{"role": "user", "content": "Ben Ayşe Demir."}]}, "anthropic_messages")
    data["stream"] = True
    out: list[Any] = []
    async for item in g.async_post_call_streaming_iterator_hook(None, agen(chunks), data):
        out.append(item)
    return out


async def test_hook_invalid_utf8_closed_raises() -> None:
    raw = _sse("x <KISI_1>")
    with pytest.raises(HTTPException) as ei:
        await _hook_stream({}, [raw[:10], b"\xff\xfe", raw[10:]])
    assert ei.value.status_code == 500


async def test_hook_invalid_utf8_open_passes_raw() -> None:
    raw = _sse("x <KISI_1>")
    out = await _hook_stream({"revert_fail_mode": "open"}, [raw[:10], b"\xff\xfe", raw[10:]])
    assert b"".join(o for o in out if isinstance(o, bytes))  # akış kesilmeden devam etti


async def test_hook_turkish_split_three_bytes_no_leak() -> None:
    raw = _sse(TEXT)
    out = await _hook_stream({}, [raw[i : i + 3] for i in range(0, len(raw), 3)])
    assert _text_of(out) == EXPECTED
