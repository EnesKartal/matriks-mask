"""Uçtan uca: `turn_off_message_logging: true` (savunma derinliği önerisi) ile gidiş-dönüş bozulmamalı."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_proxy_e2e import AUTH, HERE, PII_TEXT, _free, _no_secret, _sse_text, _wait

pytestmark = pytest.mark.e2e
ECHO_PORT, PROXY_PORT = 9912, 4011


@pytest.fixture(scope="module")
def nolog_stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if not (_free(ECHO_PORT) and _free(PROXY_PORT)):
        pytest.skip("e2e portları dolu")
    work = tmp_path_factory.mktemp("e2e_nolog")
    cfg = (HERE / "config.yaml").read_text(encoding="utf-8")
    cfg = cfg.replace("127.0.0.1:9911", f"127.0.0.1:{ECHO_PORT}").replace("os.environ/MATRIKS_PII_AUDIT_PATH", (work / "a.jsonl").as_posix())
    cfg = cfg.replace("litellm_settings:\n", "litellm_settings:\n  turn_off_message_logging: true\n")
    assert "turn_off_message_logging: true" in cfg
    (work / "config.yaml").write_text(cfg, encoding="utf-8")
    (work / "custom_callbacks.py").write_text((HERE / "custom_callbacks.py").read_text(encoding="utf-8"), encoding="utf-8")
    env = {**os.environ, "PYTHONUTF8": "1", "LEAK_LOG_PATH": str(work / "leak.jsonl")}
    log = open(work / "proxy.log", "w", encoding="utf-8")  # noqa: SIM115
    echo = subprocess.Popen([sys.executable, str(HERE / "echo_server.py"), str(ECHO_PORT)], env=env)
    proxy = subprocess.Popen(
        [sys.executable, "-m", "litellm.proxy.proxy_cli", "--config", str(work / "config.yaml"), "--port", str(PROXY_PORT)],
        cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        _wait(f"http://127.0.0.1:{ECHO_PORT}/v1/models")
        _wait(f"http://127.0.0.1:{PROXY_PORT}/health/liveliness")
        yield work
    finally:
        proxy.terminate()
        echo.terminate()
        proxy.wait(30)
        echo.wait(30)
        log.close()


def _chat(stream: bool) -> httpx.Response:
    body: dict[str, Any] = {"model": "echo", "messages": [{"role": "user", "content": PII_TEXT}], "stream": stream}
    return httpx.post(f"http://127.0.0.1:{PROXY_PORT}/v1/chat/completions", json=body,
                      headers={**AUTH, "X-Echo-Chunk-Size": "3"}, timeout=60)


def test_roundtrip_with_message_logging_off(nolog_stack: Path) -> None:
    r = _chat(False)
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == PII_TEXT
    assert _sse_text(_chat(True)) == PII_TEXT
    sent = httpx.get(f"http://127.0.0.1:{ECHO_PORT}/_received").json()
    _no_secret(json.dumps(sent, ensure_ascii=False))
    _no_secret((nolog_stack / "proxy.log").read_text(encoding="utf-8", errors="replace"))
