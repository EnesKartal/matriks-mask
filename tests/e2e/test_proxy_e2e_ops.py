"""Uçtan uca işletim senaryoları (`pytest -m e2e`): gölge mod, depo kesintisi (503), oturum tahliyesi (500), /metrics.

Ayrı bir proxy + echo yığını (config_ops.yaml) kullanır; varsayılan guardrail `dry_run: true` olduğundan bu yığında
sağlayıcıya ham değer gitmesi beklenen davranıştır (gölge mod).
"""

from __future__ import annotations

import base64
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_proxy_e2e import AUTH, HERE, PII_TEXT, T1, _free, _no_secret, _wait

pytestmark = pytest.mark.e2e
ECHO_PORT, PROXY_PORT = 9913, 4012
BASE = f"http://127.0.0.1:{PROXY_PORT}"


@pytest.fixture(scope="module")
def ops(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if not (_free(ECHO_PORT) and _free(PROXY_PORT)):
        pytest.skip("e2e portları dolu")
    work = tmp_path_factory.mktemp("e2e_ops")
    (work / "config.yaml").write_text((HERE / "config_ops.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (work / "custom_callbacks.py").write_text((HERE / "custom_callbacks.py").read_text(encoding="utf-8"), encoding="utf-8")
    env = {
        **os.environ, "PYTHONUTF8": "1", "LEAK_LOG_PATH": str(work / "leak.jsonl"),
        "MATRIKS_PII_SESSION_SECRET": "s" * 48,
        "MATRIKS_PII_STORE_KEY": base64.b64encode(b"k" * 32).decode(),
    }
    env.pop("PROMETHEUS_MULTIPROC_DIR", None)
    log = open(work / "proxy.log", "w", encoding="utf-8")  # noqa: SIM115
    echo = subprocess.Popen([sys.executable, str(HERE / "echo_server.py"), str(ECHO_PORT)], env=env)
    proxy = subprocess.Popen(
        [sys.executable, "-m", "litellm.proxy.proxy_cli", "--config", str(work / "config.yaml"), "--port", str(PROXY_PORT)],
        cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        _wait(f"http://127.0.0.1:{ECHO_PORT}/v1/models")
        _wait(f"{BASE}/health/liveliness")
        yield work
    finally:
        proxy.terminate()
        echo.terminate()
        proxy.wait(30)
        echo.wait(30)
        log.close()


def _chat(content: str, **extra: Any) -> httpx.Response:
    body = {"model": "echo", "messages": [{"role": "user", "content": content}], **extra}
    return httpx.post(f"{BASE}/v1/chat/completions", json=body, headers=AUTH, timeout=60)


def _received() -> list[dict[str, Any]]:
    return httpx.get(f"http://127.0.0.1:{ECHO_PORT}/_received").json()


def _reset() -> None:
    httpx.post(f"http://127.0.0.1:{ECHO_PORT}/_reset")


def _leak(work: Path) -> list[dict[str, Any]]:
    p = work / "leak.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_dry_run_passthrough_and_counts(ops: Path) -> None:
    _reset()
    before = len(_leak(ops))
    r = _chat(PII_TEXT)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == PII_TEXT
    assert T1 in json.dumps(_received(), ensure_ascii=False)  # gölge mod: istek değişmedi
    infos: list[dict[str, Any]] = []
    for _ in range(20):  # loglama arka planda
        time.sleep(0.5)
        recs = _leak(ops)[before:]
        infos = [i for rec in recs for i in (rec["standard_logging_object"] or {}).get("guardrail_information") or []]
        if any((i.get("guardrail_response") or {}).get("dry_run") for i in infos):
            break
    dry = [i["guardrail_response"] for i in infos if (i.get("guardrail_response") or {}).get("dry_run")]
    assert dry, infos
    assert dry[0]["would_mask"].get("TCKN") == 1 and dry[0]["would_mask"].get("KISI") == 1
    _no_secret(json.dumps(dry, ensure_ascii=False))  # sayımlar değersiz


def test_store_unavailable_503(ops: Path) -> None:
    _reset()
    r = _chat(PII_TEXT, guardrails=["matriks-pii-redisdown"])
    assert r.status_code == 503, r.text
    assert "matriks_pii_store_unavailable" in r.text
    _no_secret(r.text)
    assert _received() == []  # sağlayıcıya hiçbir şey gitmedi
    ok = _chat("Merhaba, piyasalar bugün nasıl?", guardrails=["matriks-pii-redisdown"])
    assert ok.status_code == 200 and ok.json()["choices"][0]["message"]["content"] == "Merhaba, piyasalar bugün nasıl?"


def test_session_missing_error_schema(ops: Path) -> None:
    _reset()
    with cf.ThreadPoolExecutor(2) as ex:
        slow = ex.submit(_chat, f"SLEEP: TCKN {T1}", guardrails=["matriks-pii-tiny"])
        time.sleep(0.8)  # ilk istek sağlayıcıda beklerken ikinci istek tek oturumluk depoyu doldurur
        fast = ex.submit(_chat, "TCKN 44771278268", guardrails=["matriks-pii-tiny"])
        r_fast, r_slow = fast.result(), slow.result()
    assert r_fast.status_code == 200 and r_fast.json()["choices"][0]["message"]["content"] == "TCKN 44771278268"
    assert r_slow.status_code == 500, r_slow.text
    assert "matriks_pii_session_missing" in r_slow.text
    assert T1 not in r_slow.text and "<TCKN_1>" not in r_slow.text  # ne ham değer ne yer tutucu


def test_metrics_endpoint_has_matriks_counters(ops: Path) -> None:
    pytest.importorskip("prometheus_client")
    _chat(PII_TEXT)
    r = httpx.get(f"{BASE}/metrics", headers=AUTH, timeout=30, follow_redirects=True)
    if r.status_code == 404:
        pytest.skip("bu LiteLLM sürümünde /metrics yok")
    assert r.status_code == 200
    body = r.text
    assert "matriks_pii_hook_seconds" in body and "matriks_pii_events_total" in body
    assert 'event="dry_run_would_mask"' in body
    _no_secret(body)
