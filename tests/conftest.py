from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "tests"))

from matriks_pii.config import TurkishPIIConfig  # noqa: E402
from matriks_pii.engine import PIIEngine  # noqa: E402


def load_cases(sub: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for f in sorted((FIX / sub).glob("*.yaml")):
        for c in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
            out.append((f.stem, c))
    return out


@lru_cache(maxsize=64)
def _engine(override_json: str) -> PIIEngine:
    return PIIEngine(TurkishPIIConfig.build(json.loads(override_json)))


def engine_for(override: dict[str, Any] | None = None) -> PIIEngine:
    return _engine(json.dumps(override or {}, sort_keys=True, ensure_ascii=False))


def cfg_for(override: dict[str, Any] | None = None) -> TurkishPIIConfig:
    return engine_for(override).cfg


@pytest.fixture
def engine() -> PIIEngine:
    return engine_for()
