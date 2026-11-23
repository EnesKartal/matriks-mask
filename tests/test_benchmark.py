"""Performans eşikleri. Varsayılan çalıştırmada seçilmez: `pytest -m benchmark`.

CI makineleri için 3× tolerans uygulanır (TOL).
"""

from __future__ import annotations

import os
import statistics
import time

import pytest
from conftest import engine_for

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.revert import Reverter, StreamingReverter

pytestmark = pytest.mark.benchmark
TOL = float(os.environ.get("MATRIKS_PII_BENCH_TOL", "3"))

PARA = (
    "Sayın Ahmet Yılmaz, 17291716060 TC kimlik numaralı müşterimizin TR330006100519786457841326 IBAN'ına "
    "THYAO hissesinden 1.250 lot alım emri 312,50 TL'den gerçekleşti. İletişim: 0532 234 56 78, ayse@ornek.com. "
    "Adres: Atatürk Mah. Gül Sok. No:5 Kadıköy/İstanbul. XU100 endeksi 9.875,43 puandan kapandı; "
)


def _text(n: int) -> str:
    return (PARA * (n // len(PARA) + 1))[:n]


def _percentiles(fn, runs: int) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return statistics.median(ts), ts[int(len(ts) * 0.99) - 1]


def _fresh() -> PIIEngine:
    return PIIEngine(TurkishPIIConfig.build({"analysis_cache": {"max_entries": 0}}))


def test_2kb_latency() -> None:
    eng = _fresh()
    t = _text(2048)
    eng.analyze(t)
    p50, p99 = _percentiles(lambda: eng.analyze(t), 200)
    print(f"2KB p50={p50:.2f}ms p99={p99:.2f}ms")
    assert p50 < 3 * TOL and p99 < 10 * TOL


def test_50kb_latency() -> None:
    eng = _fresh()
    t = _text(50_000)
    p50, p99 = _percentiles(lambda: eng.analyze(t), 20)
    print(f"50KB p50={p50:.1f}ms p99={p99:.1f}ms")
    assert p99 < 150 * TOL


def test_cache_effect_50_turns() -> None:
    eng = engine_for()
    turns = [_text(400) + str(i) for i in range(50)]
    for t in turns:
        eng.analyze(t)
    t0 = time.perf_counter()
    for t in turns:
        eng.analyze(t)
    assert (time.perf_counter() - t0) * 1000 < 5 * TOL


def test_streaming_per_chunk() -> None:
    cfg = TurkishPIIConfig.build()
    mp = {"<KISI_1>": "Ayşe", "<TCKN_1>": "17291716060"}
    text = ("Merhaba <KISI_1>, kimlik <TCKN_1> doğrulandı. " * 200)
    sr = StreamingReverter(Reverter(mp, {"<KISI_1>": "KISI", "<TCKN_1>": "TCKN"}, cfg), 48)
    chunks = [text[k : k + 5] for k in range(0, len(text), 5)]
    t0 = time.perf_counter()
    for c in chunks:
        sr.feed(c)
    sr.flush()
    per = (time.perf_counter() - t0) * 1000 / len(chunks)
    print(f"stream per-chunk={per:.4f}ms")
    assert per < 0.2 * TOL


@pytest.mark.parametrize("text", ["1" * 100_000, "<" * 10_000, "a" * 200_000 + "@", ("Ahmet " * 20_000)])
def test_pathological_inputs(text: str) -> None:
    eng = _fresh()
    t0 = time.perf_counter()
    eng.analyze(text)
    assert (time.perf_counter() - t0) < 2 * TOL
