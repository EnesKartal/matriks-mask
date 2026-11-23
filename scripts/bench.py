"""Performans ölçümü: metin boyutuna göre p50/p99 ve akış başına gecikme.

    python scripts/bench.py [--runs 200] [--markdown]
    python scripts/bench.py --presidio http://localhost:5002   # (opsiyonel) Presidio analyzer ile karşılaştırma
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii.config import TurkishPIIConfig  # noqa: E402
from matriks_pii.engine import PIIEngine  # noqa: E402
from matriks_pii.revert import Reverter, StreamingReverter  # noqa: E402

PARA = (
    "Sayın Ahmet Yılmaz, 17291716060 TC kimlik numaralı müşterimizin TR330006100519786457841326 IBAN'ına "
    "THYAO hissesinden 1.250 lot alım emri 312,50 TL'den gerçekleşti. İletişim: 0532 234 56 78, ayse@ornek.com. "
    "Adres: Atatürk Mah. Gül Sok. No:5 Kadıköy/İstanbul. XU100 endeksi 9.875,43 puandan kapandı; "
)


def pct(ts: list[float]) -> tuple[float, float]:
    ts = sorted(ts)
    return statistics.median(ts), ts[max(0, int(len(ts) * 0.99) - 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--presidio")
    a = ap.parse_args()
    eng = PIIEngine(TurkishPIIConfig.build({"analysis_cache": {"max_entries": 0}}))
    rows = []
    for size in (256, 2048, 10_000, 50_000):
        text = (PARA * (size // len(PARA) + 1))[:size]
        eng.analyze(text)
        runs = a.runs if size <= 10_000 else max(10, a.runs // 10)
        ts = []
        for _ in range(runs):
            t0 = time.perf_counter()
            eng.analyze(text)
            ts.append((time.perf_counter() - t0) * 1000)
        p50, p99 = pct(ts)
        rows.append((f"{size} karakter", p50, p99))
    cfg = eng.cfg
    mp = {"<KISI_1>": "Ayşe", "<TCKN_1>": "17291716060"}
    text = "Merhaba <KISI_1>, kimlik <TCKN_1> doğrulandı. " * 200
    sr = StreamingReverter(Reverter(mp, {"<KISI_1>": "KISI", "<TCKN_1>": "TCKN"}, cfg), 48)
    chunks = [text[k : k + 5] for k in range(0, len(text), 5)]
    t0 = time.perf_counter()
    for c in chunks:
        sr.feed(c)
    sr.flush()
    per = (time.perf_counter() - t0) * 1000 / len(chunks)
    if a.markdown:
        print("| Girdi | p50 (ms) | p99 (ms) |\n|---|---|---|")
        for n, p50, p99 in rows:
            print(f"| {n} | {p50:.2f} | {p99:.2f} |")
        print(f"| akış parçası (5 kr) | {per:.4f} | — |")
    else:
        for n, p50, p99 in rows:
            print(f"{n:<16} p50={p50:8.2f} ms   p99={p99:8.2f} ms")
        print(f"akış parçası     {per:.4f} ms/parça")
    if a.presidio:
        import httpx

        t2k = (PARA * 20)[:2048]
        ts = []
        for _ in range(50):
            t0 = time.perf_counter()
            httpx.post(f"{a.presidio}/analyze", json={"text": t2k, "language": "tr"}, timeout=30)
            ts.append((time.perf_counter() - t0) * 1000)
        p50, p99 = pct(ts)
        print(f"Presidio 2KB p50={p50:.2f} ms p99={p99:.2f} ms (HTTP dahil)")


if __name__ == "__main__":
    main()
