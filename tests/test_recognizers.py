"""Pozitif/karışık tespit fixture'ları (tests/fixtures/detect/*.yaml)."""

from __future__ import annotations

from collections import Counter

import pytest
from conftest import engine_for, load_cases

from matriks_pii.session import MaskSession

CASES = load_cases("detect")


@pytest.mark.parametrize("fname,case", CASES, ids=[c["id"] for _, c in CASES])
def test_detect(fname: str, case: dict) -> None:
    eng = engine_for(case.get("config"))
    got = eng.detected(case["text"])
    got_c = Counter((s.entity, s.text) for s in got)
    exp_c = Counter((e["entity"], e["value"]) for e in case["expect"])
    assert got_c == exp_c, f"{case['id']}: beklenen {dict(exp_c)} bulunan {dict(got_c)}"
    for ent in case.get("not_expect", []):
        assert all(s.entity != ent for s in got), f"{case['id']}: {ent} çıkmamalıydı"
    if "masked" in case:
        session = MaskSession(eng.cfg)
        session.reserve_existing([case["text"]])
        to_mask, _, _ = eng.actionable(eng.analyze(case["text"]))
        assert eng.mask(case["text"], to_mask, session) == case["masked"]
