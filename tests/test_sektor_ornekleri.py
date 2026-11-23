"""examples/sektor/*.yaml: her örnek config geçerli ve kendi ölçüm kümesinde (tests/fixtures/sektor) P = R = 1."""

from __future__ import annotations

from pathlib import Path

import pytest

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.selftest import _LITELLM_KEYS, check_guardrail, corpus_report, load_guardrails

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "examples" / "sektor").glob("*.yaml"))


def test_sector_files_exist() -> None:
    assert {f.stem for f in FILES} >= {"finans", "havayolu", "yurtdisi", "saglik", "sanayi", "eticaret", "telekom"}


@pytest.mark.parametrize("path", FILES, ids=[f.stem for f in FILES])
def test_sector_example(path: Path) -> None:
    (name, params), = load_guardrails(str(path))
    rep, _ = check_guardrail(name, params, quick=True)
    assert not rep.failed, [c for c in rep.checks if c.level == "FAIL"]
    cfg, _rest = TurkishPIIConfig.from_kwargs({k: v for k, v in params.items() if k not in _LITELLM_KEYS})
    corpus = ROOT / "tests" / "fixtures" / "sektor" / f"{path.stem}.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()
    assert sum('"entities": []' in ln for ln in lines) >= 2, "en az iki negatif örnek"
    res = corpus_report(PIIEngine(cfg), str(corpus))
    custom = {x.entity for x in cfg.extra_regex}
    assert custom <= set(res), f"ölçülmeyen kural: {custom - set(res)}"
    for ent, m in res.items():
        assert m["p"] == 1.0 and m["r"] == 1.0, (path.stem, ent, m)
