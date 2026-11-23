"""scripts/rollout_report.py — kademeli yayın kapı raporu (denetim izi üzerinden)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rollout_report as rr  # noqa: E402


def _write(p: Path, recs: list[dict[str, Any]]) -> str:
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return str(p)


def _pre(dry: bool, ents: dict[str, int], **kw: Any) -> dict[str, Any]:
    r: dict[str, Any] = {"event": "pre_call", "status": "success", "guardrail": "matriks-pii", "duration_ms": 2.0,
                         "api_key_hash": "k1", "logged": {}}
    r.update({"dry_run": True, "would_mask": ents, "entities": {}} if dry else {"entities": ents})
    r.update(kw)
    return r


def test_shadow_counts_and_expectation(tmp_path: Path) -> None:
    f = _write(tmp_path / "a.jsonl", [_pre(True, {"KISI": 1, "TCKN": 1}), _pre(True, {"KISI": 2}),
                                      _pre(True, {}, would_block="SIFRE")])
    p = rr.load([f])
    assert (p.requests, p.dry_run, p.live) == (3, 3, 0)
    assert p.counts == {"KISI": 3, "TCKN": 1} and p.blocked == {"SIFRE": 1}
    assert rr.evaluate(p, None, {"KISI": 3, "TCKN": 1}, 0.15, 0.01) == []
    assert rr.evaluate(p, None, {"KISI": 4, "TCKN": 1}, 0.15, 0.01) == ["KISI: beklenen 4, görülen 3"]


def test_canary_vs_shadow_rate_change(tmp_path: Path) -> None:
    base = rr.load([_write(tmp_path / "s.jsonl", [_pre(True, {"KISI": 1})] * 100)])
    ok = rr.load([_write(tmp_path / "c1.jsonl", [_pre(False, {"KISI": 1})] * 90 + [_pre(False, {})] * 10)])
    assert rr.evaluate(ok, base, None, 0.15, 0.01) == []  # %10 düşüş
    drift = rr.load([_write(tmp_path / "c2.jsonl", [_pre(False, {"KISI": 1})] * 70 + [_pre(False, {})] * 30)])
    assert any("KISI" in v and "değişim" in v for v in rr.evaluate(drift, base, None, 0.15, 0.01))


def test_failures_and_session_missing_gate(tmp_path: Path) -> None:
    recs = [_pre(False, {"KISI": 1})] * 50
    recs += [{"event": "post_call", "status": "success"}] * 98
    recs += [{"event": "post_call", "status": "guardrail_failed_to_respond", "session_missing": True}] * 2
    recs += [{"event": "pre_call", "status": "guardrail_failed_to_respond", "entities": {}}]
    p = rr.load([_write(tmp_path / "x.jsonl", recs)])
    assert (p.post_calls, p.session_missing, p.failures) == (100, 2, 1)
    bad = rr.evaluate(p, None, None, 0.15, 0.01)
    assert any("guardrail hatası" in b for b in bad) and any("oturum kaybı" in b for b in bad)


def test_guardrail_filter_and_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = _write(tmp_path / "a.jsonl", [_pre(True, {"KISI": 1}), _pre(True, {"KISI": 5}, guardrail="diger")])
    assert rr.load([f], "matriks-pii").counts == {"KISI": 1}
    exp = tmp_path / "e.json"
    exp.write_text(json.dumps({"KISI": 1}), encoding="utf-8")
    assert rr.main([f, "--guardrail", "matriks-pii", "--expect", str(exp)]) == 0
    assert "SONUÇ: GEÇTİ" in capsys.readouterr().out
    assert rr.main([f, "--expect", str(exp), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["violations"] == ["KISI: beklenen 1, görülen 6"]


def test_empty_audit_fails(tmp_path: Path) -> None:
    assert rr.evaluate(rr.load([_write(tmp_path / "e.jsonl", [])]), None, None, 0.15, 0.01) == ["denetim izinde pre_call kaydı yok"]
