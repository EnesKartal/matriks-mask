"""`python -m matriks_pii.selftest` kurulum doğrulama aracı."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from helpers import FakeRedis

from matriks_pii import selftest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIKS_PII_HASH_SECRET", "0123456789abcdef0123456789abcdef0123")
    monkeypatch.delenv("MATRIKS_PII_DEBUG_TRACEBACK", raising=False)


def _write(tmp_path: Path, lp: dict[str, Any], name: str = "matriks-pii") -> str:
    import yaml

    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"guardrails": [{"guardrail_name": name, "litellm_params": {
        "guardrail": "matriks_pii.guardrail.TurkishPIIGuardrail", **lp}}]}), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("cfg", ["config.yaml", "config.strict.yaml", "config.placeholder_formats.yaml"])
def test_ok_on_examples_config(cfg: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert selftest.main(["--config", str(ROOT / "examples" / cfg)]) == 0
    assert "SONUÇ: OK" in capsys.readouterr().out


def test_fails_on_missing_post_call(tmp_path: Path) -> None:
    assert selftest.main(["--config", _write(tmp_path, {"mode": "pre_call", "default_on": True})]) == 1


def test_fails_on_bad_config_value_free(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, {"mode": ["pre_call", "post_call"], "hash_secret": 123456789, "placeholder_id": "hmac"})
    assert selftest.main(["--config", p]) == 1
    assert "123456789" not in capsys.readouterr().out


def test_fails_when_no_guardrail(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("guardrails: []\n", encoding="utf-8")
    assert selftest.main(["--config", str(p)]) == 1


def test_debug_traceback_env_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIKS_PII_DEBUG_TRACEBACK", "1")
    assert selftest.main(["--config", _write(tmp_path, {"mode": ["pre_call", "post_call"]})]) == 1


def test_warns_stream_scope_and_dry_run(tmp_path: Path) -> None:
    rep, _ = selftest.check_guardrail("x", {"mode": ["pre_call", "post_call"], "stream_scope": "non_streaming",
                                             "dry_run": True})
    levels = {c.name: c.level for c in rep.checks}
    assert levels["stream_scope"] == "WARN" and levels["dry_run"] == "WARN" and not rep.failed


def test_redis_roundtrip_with_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import redis.asyncio as redis

    monkeypatch.setenv("MATRIKS_PII_STORE_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("MATRIKS_PII_SESSION_SECRET", "s" * 40)
    fake = FakeRedis()
    monkeypatch.setattr(redis, "from_url", lambda url, **kw: fake)
    rep, _ = selftest.check_guardrail("x", {"mode": ["pre_call", "post_call"],
                                             "session_store": {"backend": "redis", "redis_url": "redis://h/0"}})
    st = [c for c in rep.checks if c.name == "session_store"][0]
    assert st.level == "OK" and "redis" in st.message and fake.d == {}
    fake.down = True
    rep2, _ = selftest.check_guardrail("x", {"mode": ["pre_call", "post_call"],
                                              "session_store": {"backend": "redis", "redis_url": "redis://h/0"}})
    assert [c for c in rep2.checks if c.name == "session_store"][0].level == "FAIL"


def test_probe_output_value_free_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, {"mode": ["pre_call", "post_call"]})
    selftest.main(["--config", p, "--probe", "Ben Ayşe Demir, TCKN 17291716060"])
    out = capsys.readouterr().out
    assert "entity=TCKN" in out and "17291716060" not in out and "Ayşe" not in out
    selftest.main(["--config", p, "--probe", "TCKN 17291716060", "--show-values"])
    assert "17291716060" in capsys.readouterr().out


def test_json_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, {"mode": ["pre_call", "post_call"], "default_on": True})
    assert selftest.main(["--config", p, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True and doc["guardrails"][0]["guardrail"] == "matriks-pii"
    assert {"level", "name", "message"} <= set(doc["guardrails"][0]["checks"][0])


def test_quick_under_2s(tmp_path: Path) -> None:
    p = _write(tmp_path, {"mode": ["pre_call", "post_call"]})
    t0 = time.perf_counter()
    assert selftest.main(["--config", p, "--quick"]) == 0
    assert time.perf_counter() - t0 < 2


def test_corpus_mode_reports_f2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, {"mode": ["pre_call", "post_call"]})
    assert selftest.main(["--config", p, "--json", "--corpus", str(ROOT / "tests/fixtures/holdout/holdout.jsonl")]) == 0
    corpus = json.loads(capsys.readouterr().out)["guardrails"][0]["corpus"]
    assert corpus["TCKN"]["f2"] == 1.0 and corpus["KISI"]["f2"] >= 0.95


def test_guardrail_filter(tmp_path: Path) -> None:
    p = _write(tmp_path, {"mode": ["pre_call", "post_call"]}, name="a")
    assert selftest.main(["--config", p, "--guardrail", "yok"]) == 1
    assert selftest.main(["--config", p, "--guardrail", "a", "--quick"]) == 0
