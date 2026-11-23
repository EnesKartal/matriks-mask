"""Bağımsız kod incelemesinde bulunan sızıntı/doğruluk sorunlarının regresyon testleri."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException
from helpers import agen, model_response
from test_hooks import IBAN1, T1, T2, G, chat, pre

from matriks_pii.guardrail import SESSION_KEY


async def test_block_masks_request_before_raising() -> None:
    d = chat(f"Şifre: Gizli123! ve TCKN {T1}")
    d["proxy_server_request"] = {"body": {"messages": [{"role": "user", "content": f"Şifre: Gizli123! ve TCKN {T1}"}]}}
    with pytest.raises(HTTPException):
        await pre(G(entities={"SIFRE": "BLOCK"}), d)
    dumped = json.dumps(d, ensure_ascii=False)
    assert "Gizli123" not in dumped and T1 not in dumped  # hata yolu isteği loglar → ham değer kalmamalı


async def test_fail_closed_scrubs_request(monkeypatch: pytest.MonkeyPatch) -> None:
    g = G()

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(g, "_analyze_all", boom)
    d = chat(f"TCKN {T1}")
    with pytest.raises(HTTPException):
        await pre(g, d)
    assert T1 not in json.dumps(d)


async def test_client_cannot_skip_system_masking() -> None:
    d = {"model": "m", "metadata": {}, "skip_system_message_in_guardrail": True,
         "messages": [{"role": "system", "content": f"TCKN {T1}"}]}
    out = await pre(G(), d)
    assert out["messages"][0]["content"] == "TCKN <TCKN_1>"


async def test_json_numbers_keys_and_escaped_json() -> None:
    raw_num = json.dumps({"tckn": int(T1), "kart": 4111111111111111, "adet": 12})
    raw_key = json.dumps({"Ayşe Demir": {"tckn": T1}}, ensure_ascii=False)
    raw_esc = json.dumps({"musteri": "Ayşe Demir"})  # ensure_ascii=True → ş kaçışlı
    d = {"model": "m", "metadata": {}, "messages": [
        {"role": "tool", "tool_call_id": "1", "content": raw_esc},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "f", "arguments": raw_num}},
            {"id": "2", "type": "function", "function": {"name": "g", "arguments": raw_key}}]}]}
    out = await pre(G(), d)
    tool_obj = json.loads(out["messages"][0]["content"])
    assert tool_obj == {"musteri": "<KISI_1>"}
    dumped = json.dumps(out, ensure_ascii=False)
    assert T1 not in dumped and "4111111111111111" not in dumped and "Ayşe" not in dumped
    assert json.loads(out["messages"][1]["tool_calls"][0]["function"]["arguments"])["adet"] == 12


async def test_request_reasoning_content_and_thinking_untouched() -> None:
    thinking = {"type": "thinking", "thinking": f"TCKN {T1}", "signature": "imza"}
    d = {"model": "m", "messages": [{"role": "assistant", "content": [dict(thinking), {"type": "text", "text": f"TCKN {T1}"}],
                                     "reasoning_content": f"düşünce {T1}"}]}
    out = await pre(G(), d, "anthropic_messages")
    msg = out["messages"][0]
    assert msg["content"][0] == thinking  # imzalı blok değişmez (imza bozulmasın)
    assert msg["content"][1]["text"] == "TCKN <TCKN_1>" and msg["reasoning_content"] == "düşünce <TCKN_1>"


async def test_responses_extra_items_and_prompt_variables() -> None:
    d = {"model": "m", "litellm_metadata": {}, "prompt": {"id": "p", "variables": {"musteri": "Ahmet Yılmaz", "tckn": T1}},
         "input": [{"type": "reasoning", "summary": [{"type": "summary_text", "text": f"özet {T1}"}]},
                   {"type": "custom_tool_call_output", "call_id": "c", "output": f"çıktı {T1}"},
                   {"type": "mcp_call", "id": "m1", "arguments": json.dumps({"t": T1}), "output": f"mcp {T1}"}]}
    out = await pre(G(), d, "aresponses")
    dumped = json.dumps(out, ensure_ascii=False)
    assert T1 not in dumped and "Ahmet Yılmaz" not in dumped


async def test_anthropic_document_and_search_result() -> None:
    d = {"model": "c", "messages": [{"role": "user", "content": [
        {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": f"Belge TCKN {T1}"}},
        {"type": "search_result", "source": "s", "title": "Ahmet Yılmaz dosyası", "content": [{"type": "text", "text": f"IBAN {IBAN1}"}]}]}]}
    out = await pre(G(), d, "anthropic_messages")
    dumped = json.dumps(out, ensure_ascii=False)
    assert T1 not in dumped and IBAN1 not in dumped and "Ahmet Yılmaz" not in dumped


async def test_forged_session_id_ignored() -> None:
    g = G()
    d = {"model": "m", "input": f"TCKN {T1}", "metadata": {SESSION_KEY: {"matriks-pii": "matriks-pii:attacker"}}}
    await pre(g, d, "aresponses")
    sid = g._session_id(d)
    assert sid is not None and sid != "matriks-pii:attacker"
    d2 = chat("x")
    d2["metadata"][SESSION_KEY] = {"matriks-pii": "matriks-pii:attacker.deadbeefdeadbeefdeadbeef"}
    assert g._session_id(d2) is None


async def test_second_pre_call_reuses_session() -> None:
    g = G()
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    sid1 = g._session_id(d)
    d2 = dict(d)  # vector store yolu: sığ kopya, ortak metadata
    d2["messages"] = d["messages"] + [{"role": "user", "content": f"Bağlam: Ahmet Yılmaz, TCKN {T2}"}]
    await pre(g, d2)
    assert g._session_id(d) == sid1
    assert d2["messages"][1]["content"] == "Bağlam: <KISI_2>, TCKN <TCKN_2>"
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<KISI_1> <KISI_2> <TCKN_2>"))
    assert out.choices[0].message.content == f"Ayşe Demir Ahmet Yılmaz {T2}"


async def test_failure_hook_pops_session() -> None:
    g = G()
    d = chat(f"TCKN {T1}")
    await pre(g, d)
    sid = g._session_id(d)
    await g.async_post_call_failure_hook(d, RuntimeError("x"), None)
    assert await g.store.get(sid) is None


async def test_logging_uses_known_values() -> None:
    g = G()
    d = chat("Müşteri no: 4815162342 için durum?", litellm_call_id="call-1")
    await pre(g, d)
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None,
                                               response=model_response("<MUSTERI_NO_1> numaralı kayıt hazır."))
    assert out.choices[0].message.content == "4815162342 numaralı kayıt hazır."
    kw, res = g.logging_hook({"litellm_call_id": "call-1", "served_output_texts": ["4815162342 numaralı kayıt hazır."],
                              "standard_logging_object": {"response": {"text": "4815162342 numaralı kayıt hazır."}}},
                             out, "acompletion")
    assert "4815162342" not in json.dumps(kw, ensure_ascii=False, default=str)
    assert "4815162342" not in res.choices[0].message.content


async def test_stream_tool_args_valid_json() -> None:
    from litellm.types.utils import ChatCompletionDeltaToolCall, Delta, Function, ModelResponseStream, StreamingChoices

    g = G()
    d = chat("Adres: Caferağa Mah. Moda Cad. No:5 Kadıköy/İstanbul", stream=True)
    await pre(g, d)
    sess = await g.store.get(g._session_id(d))
    sess.map["<ADRES_1>"] = 'Caferağa Mah.\nModa Cad. "No:5"'
    args = '{"adres": "<ADRES_1>"}'
    chunks = [ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=None, tool_calls=[
        ChatCompletionDeltaToolCall(index=0, function=Function(arguments=args[k:k + 4]))]))]) for k in range(0, len(args), 4)]
    chunks.append(ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(), finish_reason="tool_calls")]))
    acc = ""
    async for c in g.async_post_call_streaming_iterator_hook(user_api_key_dict=None, response=agen(chunks), request_data=d):
        for tc in c.choices[0].delta.tool_calls or []:
            acc += tc.function.arguments or ""
    assert json.loads(acc) == {"adres": 'Caferağa Mah.\nModa Cad. "No:5"'}


async def test_responses_stream_events() -> None:
    g = G()
    d = {"model": "m", "input": f"Ben Ayşe Demir, TCKN {T1}", "stream": True}
    await pre(g, d, "aresponses")
    text = "Merhaba <KISI_1>, kimlik <TCKN_1>."
    evs: list[Any] = [{"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": text[k:k + 3]}
                      for k in range(0, len(text), 3)]
    evs.append({"type": "response.output_text.done", "output_index": 0, "content_index": 0, "text": text})
    evs.append({"type": "response.completed",
                "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}})
    out = [e async for e in g.async_post_call_streaming_iterator_hook(user_api_key_dict=None, response=agen(evs), request_data=d)]
    expected = f"Merhaba Ayşe Demir, kimlik {T1}."
    assert "".join(e["delta"] for e in out if e["type"] == "response.output_text.delta") == expected
    assert [e for e in out if e["type"] == "response.output_text.done"][0]["text"] == expected
    assert out[-1]["response"]["output"][0]["content"][0]["text"] == expected


async def test_anthropic_sse_bytes_stream() -> None:
    g = G()
    d = {"model": "c", "messages": [{"role": "user", "content": f"Ben Ayşe Demir, TCKN {T1}"}], "stream": True}
    await pre(g, d, "anthropic_messages")
    text = "Merhaba <KISI_1>, <TCKN_1>"
    raw = 'event: message_start\ndata: {"type":"message_start"}\n\n'
    raw += 'event: content_block_start\ndata: {"type":"content_block_start","index":0}\n\n'
    for k in range(0, len(text), 4):
        delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[k:k + 4]}}
        raw += "event: content_block_delta\ndata: " + json.dumps(delta) + "\n\n"
    raw += 'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
    pieces = [raw[k:k + 37].encode() for k in range(0, len(raw), 37)]  # olay ortasından bölünmüş baytlar
    got = b"".join([c async for c in g.async_post_call_streaming_iterator_hook(
        user_api_key_dict=None, response=agen(pieces), request_data=d)]).decode()
    acc = ""
    for ev in got.split("\n\n"):
        for ln in ev.split("\n"):
            if ln.startswith("data:"):
                o = json.loads(ln[5:])
                if o.get("type") == "content_block_delta":
                    acc += o["delta"]["text"]
    assert acc == f"Merhaba Ayşe Demir, {T1}"
    assert '"content_block_stop"' in got.strip().split("\n\n")[-1]


def test_final_strip_on_raw_text() -> None:
    from conftest import cfg_for

    from matriks_pii.revert import Reverter

    rev = Reverter({"<TCKN_1>": "17291716060"}, {"<TCKN_1>": "TCKN"}, cfg_for())
    assert rev.revert("adres <TCKN_1>", final=True) == "adres 17291716060"
    assert rev.revert("son <KIS", final=True) == "son "


# ---------------------------------------------------------------- ikinci inceleme turu
async def test_unsupported_block_masks_before_raising() -> None:
    d = {"model": "r", "query": f"TCKN {T1}", "metadata": {}}
    with pytest.raises(HTTPException):
        await pre(G(unsupported_call_types="block"), d, "arerank")
    assert T1 not in json.dumps(d)


async def test_signed_token_cannot_be_replayed_on_other_request() -> None:
    g = G()
    a = chat(f"Ben Ayşe Demir, TCKN {T1}", litellm_call_id="call-A")
    await pre(g, a)
    b = chat("Merhaba", litellm_call_id="call-B")
    b["metadata"][SESSION_KEY] = dict(a["metadata"][SESSION_KEY])  # A'nın jetonu B'ye kopyalandı
    assert g._session_id(b) is None
    # B'nin yanıtında A'nın değerleri geri yüklenmez: kopya jeton doğrulanamaz → fail-closed
    with pytest.raises(HTTPException) as ei:
        await g.async_post_call_success_hook(data=b, user_api_key_dict=None, response=model_response("<KISI_1> <TCKN_1>"))
    assert ei.value.detail["error"] == "matriks_pii_session_missing" and T1 not in str(ei.value.detail)


async def test_recent_values_not_kept_when_mask_logs_off() -> None:
    g = G(mask_logs=False)
    d = chat(f"TCKN {T1}", litellm_call_id="c1")
    await pre(g, d)
    await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<TCKN_1>"))
    assert len(g._recent) == 0


async def test_logging_twice_and_tuple_served_texts() -> None:
    g = G()
    d = chat("Müşteri no: 4815162342 için durum?", litellm_call_id="call-2")
    await pre(g, d)
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response("<MUSTERI_NO_1> hazır."))
    for _ in range(2):  # sync + async başarı işleyicileri
        kw, _res = g.logging_hook({"litellm_call_id": "call-2", "served_output_texts": ("4815162342 hazır.",)}, out, "acompletion")
        assert isinstance(kw["served_output_texts"], tuple)
        assert "4815162342" not in json.dumps(kw, ensure_ascii=False, default=str)


async def test_non_finite_json_numbers_do_not_crash() -> None:
    d = {"model": "m", "metadata": {}, "messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "f", "arguments": '{"a": Infinity, "b": NaN, "t": "' + T1 + '"}'}}]}]}
    out = await pre(G(fail_mode="open"), d)
    assert out is not None and T1 not in json.dumps(out)


async def test_masked_number_restored_as_number() -> None:
    g = G()
    d = {"model": "m", "metadata": {}, "messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "f", "arguments": json.dumps({"tckn": int(T1)})}}]}]}
    await pre(g, d)
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None,
                                               response=model_response(None, tool_args=[json.dumps({"tckn": "<TCKN_1>"})]))
    assert json.loads(out.choices[0].message.tool_calls[0].function.arguments) == {"tckn": int(T1)}


async def test_anthropic_sse_crlf() -> None:
    g = G()
    d = {"model": "c", "messages": [{"role": "user", "content": f"TCKN {T1}"}], "stream": True}
    await pre(g, d, "anthropic_messages")
    raw = ""
    for part in ("Kimlik <TC", "KN_1> tamam"):
        raw += "event: content_block_delta\r\ndata: " + json.dumps({"type": "content_block_delta", "index": 0,
                                                                    "delta": {"type": "text_delta", "text": part}}) + "\r\n\r\n"
    raw += 'event: content_block_stop\r\ndata: {"type":"content_block_stop","index":0}\r\n\r\n'
    pieces = [raw[k:k + 20].encode() for k in range(0, len(raw), 20)]
    outs = [c async for c in g.async_post_call_streaming_iterator_hook(user_api_key_dict=None, response=agen(pieces), request_data=d)]
    assert len(outs) > 1  # akış sonuna kadar tutulmuyor
    got = b"".join(outs).decode()
    assert T1 in got and "<TCKN_1>" not in got and "<TC" not in got


def test_suffix_not_confused_with_label() -> None:
    from conftest import cfg_for

    from matriks_pii.revert import Reverter

    rev = Reverter({"<KISI_1>": "Ali", "<KISI_2>": "Ayşe"}, {"<KISI_1>": "KISI", "<KISI_2>": "KISI"}, cfg_for())
    assert rev.revert("<KISI_2>'KISI_1'ye") == "Ayşe'Ali'ye"
