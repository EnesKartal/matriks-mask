"""Dış veri setleriyle regresyon eşikleri. `pytest -m external`.

Veri yoksa atlanır: `python scripts/external_bench.py --download` ile indirilir (scripts/_raw/external/).
Eşikler bu sürümün ölçümünün biraz altındadır; düşüş bir kural değişikliğinin genel doğruluğu bozduğunu gösterir.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import external_bench as xb  # noqa: E402

from matriks_pii.config import TurkishPIIConfig  # noqa: E402
from matriks_pii.engine import PIIEngine  # noqa: E402

pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(not all((xb.EXT / n).exists() for n in xb.SOURCES), reason="dış veri seti indirilmemiş"),
]


def _total(st: dict[str, Counter]) -> tuple[float, float, float]:
    tot: Counter = Counter()
    for s in st.values():
        tot.update(s)
    return xb._prf(tot)


def test_masking_benchmark_strict() -> None:
    st, _, exact, n = xb.masking_bench(PIIEngine(TurkishPIIConfig.build({"profile": "strict"})))
    p, r, f2 = _total(st)
    assert p >= 0.96 and r >= 0.94 and f2 >= 0.95, (p, r, f2)
    assert exact >= 0.85 * n


def test_masking_benchmark_balanced_precision() -> None:
    st, _, _, _ = xb.masking_bench(PIIEngine(TurkishPIIConfig.build({"profile": "balanced"})))
    p, _, _ = _total(st)
    assert p >= 0.97, p


def test_werea_strict() -> None:
    st, _ = xb.werea(PIIEngine(TurkishPIIConfig.build({"profile": "strict"})))
    p, r, _ = _total(st)
    assert p >= 0.99 and r >= 0.60, (p, r)
    # deterministik türlerde (checksum'lı) kaçırma olmamalı
    for ent in ("TCKN", "IBAN", "EPOSTA"):
        if ent in st:
            assert st[ent]["fn"] == 0, (ent, st[ent])
