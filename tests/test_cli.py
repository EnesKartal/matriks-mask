"""`matriks-pii` komut satırı (matriks_pii.cli)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from matriks_pii.cli import main

TEXT = "Ben Ayşe Demir, TCKN 17291716060, IBAN TR330006100519786457841326"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_mask_argument(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mask", TEXT]) == 0
    out = capsys.readouterr().out
    assert out == "Ben <KISI_1>, TCKN <TCKN_1>, IBAN <IBAN_1>\n"


def test_mask_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(TEXT + "\n"))
    assert main(["mask"]) == 0
    assert capsys.readouterr().out == "Ben <KISI_1>, TCKN <TCKN_1>, IBAN <IBAN_1>\n"


def test_mask_json_has_no_values(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mask", "--json", TEXT]) == 0
    raw = capsys.readouterr().out
    out = json.loads(raw)
    assert [e["entity"] for e in out["entities"]] == ["KISI", "TCKN", "IBAN"]
    assert "17291716060" not in raw and "Demir" not in raw and "TR3300" not in raw


def test_mask_block_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mask", "--profile", "strict", "anahtar: AKIAIOSFODNN7EXAMPLE"]) == 2
    cap = capsys.readouterr()
    assert cap.out == "" and "GIZLI_ANAHTAR" in cap.err and "AKIA" not in cap.err


def test_mask_with_litellm_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mask", "--config", str(EXAMPLES / "config.yaml"), TEXT]) == 0
    assert "<TCKN_1>" in capsys.readouterr().out


def test_mask_config_without_guardrail(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("model_list: []\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["mask", "--config", str(p), TEXT])


def test_mask_invalid_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        "guardrails:\n  - guardrail_name: g\n    litellm_params:\n"
        "      guardrail: matriks_pii.guardrail.TurkishPIIGuardrail\n      entities: {YOK_BOYLE: MASK}\n",
        encoding="utf-8",
    )
    assert main(["mask", "--config", str(p), TEXT]) == 1
    assert "yapılandırma hatası" in capsys.readouterr().err


def test_keys(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["keys"]) == 0
    out = capsys.readouterr().out
    assert "MATRIKS_PII_SESSION_SECRET=" in out and "MATRIKS_PII_STORE_KEY=" in out


def test_selftest_delegates(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["selftest", "--config", str(EXAMPLES / "config.yaml"), "--quick"]) == 0
    assert "SONUÇ: OK" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["bilinmeyen"], ["--help"]])
def test_usage(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        main(argv)


def test_mask_missing_config_no_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["mask", "--config", "yok-boyle.yaml", TEXT]) == 1
    assert "yapılandırma hatası" in capsys.readouterr().err


def test_mask_non_utf8_stdout() -> None:
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    r = subprocess.run([sys.executable, "-m", "matriks_pii.cli", "mask", "Ben Ayşe Demir geldi, komşusu Işıl"],
                       capture_output=True, env=env)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert "<KISI_1>" in r.stdout.decode("utf-8")
