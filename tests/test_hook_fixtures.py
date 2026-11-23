"""Fixture tabanlı kanca senaryoları (`fixtures/hooks/*.yaml`).

Sözleşme (her kayıt):
  id, call_type (vars. acompletion), config (guardrail kwargs), request,
  expect_request  {nokta.yolu: değer}  — pre-call sonrası istek (JSON string alanı dict/list ile karşılaştırılabilir)
  expect_keys     [nokta.yolu]         — var olmalı;  absent_keys: [nokta.yolu] — olmamalı
  expect_none     true                 — pre-call None döner (istek değişmez)
  expect_error    {status, entity?}    — HTTPException
  llm_response    {content, tool_args, reasoning, n} (ModelResponse) | {raw: {...}} (dict yanıt)
  expect_client   {nokta.yolu: değer}  — post-call sonrası istemciye giden yanıt
  forbid          [değer]              — pre-call sonrası istek JSON'unda geçmemeli
  passthrough     true                 — pre-call None döner (dry_run vb.); expect_request/absent_keys istek üzerinde
  expect_config_error  true            — guardrail kurulumu ValueError; forbid_in_error: [değer] iletide geçmemeli
  pop_session_before_post  true        — pre-call sonrası oturum deposu temizlenir (TTL doldu / farklı süreç)
  expect_post_error {status, error}    — post-call HTTPException
  expect_client None dönüşü            — "yanıt değişmedi" demektir (orijinal yanıt üzerinde doğrulanır)
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import load_cases
from fastapi import HTTPException
from helpers import model_response

from matriks_pii.guardrail import TurkishPIIGuardrail

CASES = load_cases("hooks")


def _get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            cur = getattr(cur, part)
    return cur


def _has(obj: Any, path: str) -> bool:
    try:
        _get(obj, path)
        return True
    except (KeyError, IndexError, AttributeError, ValueError):
        return False


def _eq(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (dict, list)) and isinstance(actual, str):
        return bool(json.loads(actual) == expected)
    return bool(actual == expected)


def test_hook_fixture_count() -> None:
    assert len(CASES) >= 35
    assert len({c["id"] for _, c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", [c for _, c in CASES], ids=[c["id"] for _, c in CASES])
async def test_hook_case(case: dict[str, Any]) -> None:
    kw = {"default_on": True, "event_hook": ["pre_call", "post_call"], **(case.get("config") or {})}
    if case.get("expect_config_error"):
        with pytest.raises(ValueError) as cei:
            TurkishPIIGuardrail(guardrail_name="matriks-pii", **kw)
        for v in case.get("forbid_in_error", []):
            assert str(v) not in str(cei.value)
        return
    g = TurkishPIIGuardrail(guardrail_name="matriks-pii", **kw)
    data = json.loads(json.dumps(case["request"]))
    call_type = case.get("call_type", "acompletion")

    if "expect_error" in case:
        with pytest.raises(HTTPException) as ei:
            await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=data, call_type=call_type)
        exp = case["expect_error"]
        assert ei.value.status_code == exp["status"]
        if "entity" in exp:
            assert ei.value.detail["entity"] == exp["entity"]
        for v in case.get("forbid", []):
            assert v not in json.dumps(ei.value.detail, ensure_ascii=False)
            assert v not in json.dumps(data, ensure_ascii=False, default=str)
        return

    out = await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=data, call_type=call_type)
    if case.get("expect_none"):
        assert out is None
        assert data == case["request"]
        return
    if case.get("passthrough"):
        assert out is None
        out = data
    assert out is not None
    for path, exp in (case.get("expect_request") or {}).items():
        assert _eq(_get(out, path), exp), (path, _get(out, path))
    for path in case.get("expect_keys", []):
        assert _has(out, path), path
    for path in case.get("absent_keys", []):
        assert not _has(out, path), path
    dumped = json.dumps(out, ensure_ascii=False, default=str)
    for v in case.get("forbid", []):
        assert v not in dumped, v

    if "llm_response" in case:
        spec = case["llm_response"]
        resp = json.loads(json.dumps(spec["raw"])) if "raw" in spec else model_response(
            spec.get("content"), spec.get("tool_args"), spec.get("reasoning"), spec.get("n", 1))
        if case.get("pop_session_before_post"):
            g.store._d.clear()  # type: ignore[attr-defined]
        if "expect_post_error" in case:
            with pytest.raises(HTTPException) as pei:
                await g.async_post_call_success_hook(data=out, user_api_key_dict=None, response=resp)
            assert pei.value.status_code == case["expect_post_error"]["status"]
            assert pei.value.detail["error"] == case["expect_post_error"]["error"]
            return
        client = await g.async_post_call_success_hook(data=out, user_api_key_dict=None, response=resp)
        client = resp if client is None else client  # None = yanıt değişmedi
        for path, exp in (case.get("expect_client") or {}).items():
            assert _eq(_get(client, path), exp), (path, _get(client, path))
