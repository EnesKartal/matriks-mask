"""Kademeli yayın provası (`pytest -m e2e`): operasyonel aşamalar gerçek proxy üzerinden, holdout-2 trafiğiyle.

Aşama 1 — gölge mod: 345 istek `dry_run` guardrail'inden geçer; istek sağlayıcıya DEĞİŞMEDEN gider, denetim izindeki
would_mask / would_block sayımları süreç içi beklentiyle birebir eşleşir (`scripts/rollout_report.py --expect`).
Aşama 2 — canary: isteklerin %5'i (her 20. istek) canlı guardrail'den geçer; sağlayıcıya ham değer gitmez, istemci
orijinal metni alır (KART ve GIZLI_ANAHTAR tasarım gereği maskeli döner), oturum kaybı ve hata 0, istek başına oranlar aynı alt kümenin gölge sayımına göre ±%15 içinde.

Bu, takvim süresi gerektiren üretim aşamalarının (5 iş günü gölge, 3 gün canary) yerine geçmez; aynı kapıların aynı
araçla ölçüldüğünü ve geçtiğini kanıtlar. Üretimde aynı rapor gerçek denetim iziyle koşturulur.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_proxy_e2e import AUTH, HERE, _free, _wait

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.guardrail import TurkishPIIGuardrail

pytestmark = pytest.mark.e2e
ECHO_PORT, PROXY_PORT = 9914, 4013
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import rollout_report as rr  # noqa: E402

ROWS = [json.loads(x) for x in (ROOT / "tests" / "fixtures" / "holdout" / "holdout2.jsonl").read_text(encoding="utf-8").splitlines()]
CFG = TurkishPIIConfig.build({})
CANARY = [i for i in range(len(ROWS)) if i % 20 == 0]


@pytest.fixture(scope="module")
def rollout(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    if not (_free(ECHO_PORT) and _free(PROXY_PORT)):
        pytest.skip("e2e portları dolu")
    work = tmp_path_factory.mktemp("e2e_rollout")
    (work / "config.yaml").write_text((HERE / "config_rollout.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    env = {**os.environ, "PYTHONUTF8": "1", "ROLLOUT_AUDIT_SHADOW": str(work / "shadow" / "audit.jsonl"),
           "ROLLOUT_AUDIT_CANARY": str(work / "canary" / "audit.jsonl")}
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


def _same(a: str, b: str) -> bool:
    """JSON içerikli mesaj istekte yaprak bazında maskelenip sıkı biçimde yeniden yazılır; anlamca karşılaştır."""
    if a == b:
        return True
    try:
        return bool(json.loads(a) == json.loads(b))
    except ValueError:
        return False


def _body(text: str) -> dict[str, Any]:
    return {"model": "echo", "messages": [{"role": "user", "content": text}]}


def _chat(client: httpx.Client, text: str, guardrail: str) -> httpx.Response:
    return client.post(f"http://127.0.0.1:{PROXY_PORT}/v1/chat/completions", json={**_body(text), "guardrails": [guardrail]},
                       headers=AUTH, timeout=60)


def _last_received(client: httpx.Client) -> str:
    return str(client.get(f"http://127.0.0.1:{ECHO_PORT}/_received").json()[-1]["messages"][-1]["content"])


async def _expected(tmp: Path, idx: list[int], dry: bool) -> dict[str, int]:
    """Aynı istekleri süreç içi guardrail'den geçirip denetim izinden sayım çıkarır (proxy'siz beklenti)."""
    g = TurkishPIIGuardrail(guardrail_name="exp", default_on=True, event_hook=["pre_call", "post_call"], dry_run=dry,
                            audit_log={"enabled": True, "path": str(tmp / "audit.jsonl")})
    for i in idx:
        try:
            await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data={**_body(ROWS[i]["text"]), "metadata": {}},
                                        call_type="acompletion")
        except Exception:  # BLOCK (400) — sayım yine denetim izine yazılır
            pass
    g.audit.close()
    return dict(rr.load([str(tmp / "audit.*.jsonl")]).counts)


async def test_shadow_then_canary_gates(rollout: Path, tmp_path: Path) -> None:
    with httpx.Client() as client:
        # ---------------- aşama 1: gölge mod — istek değişmeden gider
        for row in ROWS:
            r = _chat(client, row["text"], "matriks-pii-shadow")
            assert r.status_code == 200, (row["id"], r.status_code)
            assert _last_received(client) == row["text"], row["id"]
        # ---------------- aşama 2: canary — %5
        blocked_rows = 0
        for i in CANARY:
            row = ROWS[i]
            r = _chat(client, row["text"], "matriks-pii-canary")
            if r.status_code == 400:
                blocked_rows += 1
                assert "matriks_pii_blocked" in r.text
                continue
            assert r.status_code == 200, (row["id"], r.text)
            got = r.json()["choices"][0]["message"]["content"]
            assert "<" not in got.replace(row["text"], ""), row["id"]  # yer tutucu kalmadı
            for e in row["entities"]:  # geri yüklenen varlıklar aynen, restore: false olanlar (KART, GIZLI_ANAHTAR) maskeli
                assert (e["value"] in got) == CFG.restore(e["entity"]) or CFG.action(e["entity"]) == "LOG", (row["id"], e["entity"])
            if all(CFG.restore(e["entity"]) for e in row["entities"]):
                assert _same(got, row["text"]), row["id"]
            sent = _last_received(client)
            for e in row["entities"]:
                assert e["value"] not in sent, (row["id"], e["entity"])

    shadow_files = [str(rollout / "shadow" / "audit.*.jsonl")]
    canary_files = [str(rollout / "canary" / "audit.*.jsonl")]
    shadow, canary = rr.load(shadow_files), rr.load(canary_files)
    assert shadow.requests == len(ROWS) and shadow.dry_run == len(ROWS)
    assert canary.requests == len(CANARY) and canary.live == len(CANARY)

    (tmp_path / "s").mkdir()
    (tmp_path / "c").mkdir()
    (tmp_path / "r").mkdir()
    exp_shadow = await _expected(tmp_path / "s", list(range(len(ROWS))), dry=True)
    exp_canary = await _expected(tmp_path / "c", CANARY, dry=False)
    assert rr.evaluate(shadow, None, exp_shadow, 0.15, 0.01) == []
    assert rr.evaluate(canary, None, exp_canary, 0.15, 0.01) == []
    recs = [json.loads(ln) for pat in canary_files for f in glob.glob(pat) for ln in open(f, encoding="utf-8")]
    with_session = sum(1 for r in recs if r["event"] == "pre_call" and r.get("entities") and not r.get("blocked"))
    # PII'siz istekte oturum yazılmaz → post_call kaydı da yok; her maskeli istek geri çevrildi
    assert canary.session_missing == 0 and canary.failures == 0 and canary.post_calls == with_session > 0
    # ±%15 kapısı: canary, aynı alt kümenin gölge sayımıyla karşılaştırılır
    await _expected(tmp_path / "r", CANARY, dry=True)
    base_subset = rr.load([str(tmp_path / "r" / "audit.*.jsonl")])
    assert rr.evaluate(canary, base_subset, None, 0.15, 0.01) == []
    # CLI kapısı (operatörün üretimde koşturacağı komut)
    exp_file = tmp_path / "exp.json"
    exp_file.write_text(json.dumps(exp_shadow), encoding="utf-8")
    assert rr.main([*shadow_files, "--expect", str(exp_file)]) == 0
    assert rr.main([*canary_files, "--baseline", str(tmp_path / "r" / "audit.*.jsonl")]) == 0
    # denetim izinde değer yok
    blob = "".join(Path(f).read_text(encoding="utf-8") for pat in shadow_files + canary_files for f in glob.glob(pat))
    for row in ROWS:
        for e in row["entities"]:
            if len(e["value"]) >= 6:
                assert e["value"] not in blob, (row["id"], e["entity"])
