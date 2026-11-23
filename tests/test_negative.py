"""Negatif set (595 yanlış pozitif tuzağı): hiçbir şey tespit edilmemeli (IGNORE aksiyonlu varlıklar hariç)."""

from __future__ import annotations

import pytest
from conftest import engine_for, load_cases

CASES = load_cases("negative")


def test_negative_count() -> None:
    assert len(CASES) == 595


@pytest.mark.parametrize("fname,case", CASES, ids=[c["id"] for _, c in CASES])
def test_negative(fname: str, case: dict) -> None:
    got = engine_for(case.get("config")).detected(case["text"])
    assert got == [], f"{case['id']} yanlış pozitif: {[(s.entity, s.text, s.score) for s in got]}"
