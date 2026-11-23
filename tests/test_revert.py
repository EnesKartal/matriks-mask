"""Geri çevirme fixture'ları (tests/fixtures/revert/*.yaml)."""

from __future__ import annotations

import re

import pytest
from conftest import cfg_for, load_cases

from matriks_pii.revert import Reverter

CASES = load_cases("revert")


def _entities(case: dict) -> dict[str, str]:
    ents = dict(case.get("entities") or {})
    for ph in case["map"]:
        if ph not in ents:
            m = re.search(r"([A-Z][A-Z_]*[A-Z])[_\-]", ph)
            ents[ph] = m.group(1) if m else "KISI"
    return ents


@pytest.mark.parametrize("fname,case", CASES, ids=[c["id"] for _, c in CASES])
def test_revert(fname: str, case: dict) -> None:
    cfg = cfg_for(case.get("config"))
    rev = Reverter(dict(case["map"]), _entities(case), cfg)
    assert rev.revert(case["llm_output"], final=bool(case.get("final"))) == case["expect"]


def test_revert_does_not_rereplace_restored_value() -> None:
    cfg = cfg_for()
    rev = Reverter({"<KISI_1>": "<KISI_2>", "<KISI_2>": "Mehmet"}, {"<KISI_1>": "KISI", "<KISI_2>": "KISI"}, cfg)
    assert rev.revert("<KISI_1>") == "<KISI_2>"


def test_revert_stats() -> None:
    cfg = cfg_for()
    rev = Reverter({"<KISI_1>": "Ayşe"}, {"<KISI_1>": "KISI"}, cfg)
    rev.revert("<KISI_1> ve <KISI_7>")
    assert rev.stats.replaced == 1 and rev.stats.unresolved == 1


def test_reserved_placeholder_kept_even_with_strip() -> None:
    cfg = cfg_for({"unresolved_placeholder": "strip"})
    rev = Reverter({"<KISI_2>": "Ayşe"}, {"<KISI_2>": "KISI"}, cfg, reserved={"<KISI_1>"})
    assert rev.revert("<KISI_1> ve <KISI_2>") == "<KISI_1> ve Ayşe"
