"""Akış geri çevirme: her bölme stratejisinde birleşim == tam metin geri çevirisi."""

from __future__ import annotations

import re

import pytest
from conftest import cfg_for, load_cases

from matriks_pii.revert import Reverter, StreamingReverter
from matriks_pii.streaming import StreamProcessor

CASES = load_cases("streaming")


def _ents(mp: dict[str, str]) -> dict[str, str]:
    return {k: re.search(r"([A-Z][A-Z_]*[A-Z])_", k).group(1) for k in mp}  # type: ignore[union-attr]


def _splits(text: str) -> list[list[str]]:
    n = len(text)
    out: list[list[str]] = []
    for i in range(1, n):  # (a) her indekste iki parça
        out.append([text[:i], text[i:]])
    out.append(list(text))  # (b) her karakter ayrı
    for size in (3, 7, 16):  # (c) sabit boyut
        out.append([text[k : k + size] for k in range(0, n, size)])
    return out or [[text]]


@pytest.mark.parametrize("fname,case", CASES, ids=[c["id"] for _, c in CASES])
def test_stream_split_invariant(fname: str, case: dict) -> None:
    cfg = cfg_for()
    full = case["full_output"]
    expected = Reverter(case["map"], _ents(case["map"]), cfg).revert(full, final=True)
    for parts in _splits(full):
        sr = StreamingReverter(Reverter(case["map"], _ents(case["map"]), cfg), cfg.streaming.holdback_max_chars)
        got = "".join(sr.feed(p) for p in parts) + sr.flush()
        assert got == expected, f"bölme {parts!r}"


# ---------------------------------------------------------------- ModelResponseStream düzeyi
def _chunks(text: str, size: int, finish: bool, field: str = "content"):
    from litellm.types.utils import ChatCompletionDeltaToolCall, Delta, Function, ModelResponseStream, StreamingChoices

    out = []
    for k in range(0, len(text), size):
        piece = text[k : k + size]
        if field == "content":
            d = Delta(content=piece)
        elif field == "reasoning":
            d = Delta(content=None)
            d.reasoning_content = piece
        else:
            d = Delta(content=None, tool_calls=[ChatCompletionDeltaToolCall(index=0, function=Function(arguments=piece))])
        out.append(ModelResponseStream(choices=[StreamingChoices(index=0, delta=d)]))
    if finish:
        out.append(ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=None), finish_reason="stop")]))
    return out


def _collect(items, field: str = "content") -> str:
    acc = ""
    for it in items:
        for ch in it.choices:
            if field == "content":
                acc += ch.delta.content or ""
            elif field == "reasoning":
                acc += getattr(ch.delta, "reasoning_content", None) or ""
            else:
                for tc in ch.delta.tool_calls or []:
                    acc += tc.function.arguments or ""
    return acc


MAP = {"<KISI_1>": "Ayşe Demir", "<TCKN_1>": "17291716060"}


@pytest.mark.parametrize("size", [1, 2, 3, 5, 8, 13])
@pytest.mark.parametrize("finish", [True, False])
@pytest.mark.parametrize("field", ["content", "reasoning", "tool"])
def test_stream_processor(size: int, finish: bool, field: str) -> None:
    cfg = cfg_for()
    text = 'Merhaba <KISI_1>\'e, {"tckn": "<TCKN_1>"} tamam <KIS' if field != "tool" else '{"ad": "<KISI_1>", "tckn": "<TCKN_1>"}'
    proc = StreamProcessor(Reverter(MAP, _ents(MAP), cfg), cfg.streaming.holdback_max_chars)
    src = _chunks(text, size, finish, field)
    originals = [c.model_copy(deep=True) for c in src]
    out = [o for c in src for o in proc.process(c)]
    last = None
    out.extend(proc.final_items())
    if last is not None:
        out.append(last)
    expected = Reverter(MAP, _ents(MAP), cfg).revert(text, final=True)
    assert _collect(out, field) == expected
    # orijinal parçalar değiştirilmemiş olmalı (loglama referansla çalışır)
    for a, b in zip(src, originals, strict=True):
        assert a.model_dump() == b.model_dump()


def test_two_choices_independent() -> None:
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

    cfg = cfg_for()
    proc = StreamProcessor(Reverter(MAP, _ents(MAP), cfg), 48)
    a, b = "A: <KISI_1>", "B: <TCKN_1>"
    items = []
    for k in range(0, 12, 2):
        items.append(
            ModelResponseStream(
                choices=[StreamingChoices(index=0, delta=Delta(content=a[k : k + 2] or None)),
                         StreamingChoices(index=1, delta=Delta(content=b[k : k + 2] or None))]
            )
        )
    items.append(ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(), finish_reason="stop"),
                                              StreamingChoices(index=1, delta=Delta(), finish_reason="stop")]))
    outs = [o for i in items for o in proc.process(i)]
    c0 = "".join((o.choices[0].delta.content or "") for o in outs)
    c1 = "".join((o.choices[1].delta.content or "") for o in outs)
    assert c0 == "A: Ayşe Demir" and c1 == "B: 17291716060"


def test_lone_lt_released_after_holdback() -> None:
    cfg = cfg_for()
    sr = StreamingReverter(Reverter(MAP, _ents(MAP), cfg), 48)
    out = sr.feed("a < b ")
    out += sr.feed("x" * 60)
    assert out.startswith("a < b")  # tampon sınırı aşılınca serbest bırakılır


# ---------------------------------------------------------------- /completions akışı (choices[i].text)
def _tc_chunks(text: str, size: int, finish: bool) -> list[object]:
    from litellm.types.utils import TextChoices, TextCompletionResponse

    out: list[object] = [TextCompletionResponse(choices=[TextChoices(index=0, text=text[k : k + size])])
                         for k in range(0, len(text), size)]
    if finish:
        out.append(TextCompletionResponse(choices=[TextChoices(index=0, text="", finish_reason="stop")]))
    return out


@pytest.mark.parametrize("size", [1, 2, 3, 7])
@pytest.mark.parametrize("finish", [True, False])
def test_text_completion_stream_reverted(size: int, finish: bool) -> None:
    cfg = cfg_for()
    proc = StreamProcessor(Reverter(MAP, _ents(MAP), cfg), cfg.streaming.holdback_max_chars)
    text = "Merhaba <KISI_1>'e, kimlik <TCKN_1> kayıtlı."
    src = _tc_chunks(text, size, finish)
    before = [c.model_dump() for c in src]  # type: ignore[attr-defined]
    out = [o for c in src for o in proc.process(c)] + proc.final_items()
    got = "".join(ch.text or "" for o in out for ch in o.choices)
    assert got == "Merhaba Ayşe Demir'e, kimlik 17291716060 kayıtlı."
    assert [c.model_dump() for c in src] == before  # type: ignore[attr-defined]


def test_text_completion_stream_drain_raw_keeps_text() -> None:
    cfg = cfg_for()
    proc = StreamProcessor(Reverter(MAP, _ents(MAP), cfg), cfg.streaming.holdback_max_chars)
    first = [o for c in _tc_chunks("abc <KISI_1> def <KI", 4, False) for o in proc.process(c)]
    drained = proc.drain_raw()
    assert "".join(ch.text or "" for o in first + drained for ch in o.choices) == "abc Ayşe Demir def <KI"
