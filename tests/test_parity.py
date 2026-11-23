"""Biçimler arası eşdeğerlik matrisi: Chat / Completions / Responses / Anthropic / Gemini ×
metin, çok parçalı + görsel, araç argümanı (istek/yanıt), reasoning, sistem talimatı, metadata kovası, akış (metin, araç
argümanı, usage), çoklu aday, çözülemeyen yer tutucu (keep/strip), oturum kaybı (500), boyut sınırı (413).

Kanca fixture çalıştırıcısı akışı desteklemediği için matris YAML yerine burada parametrik yazıldı. Uygulanamayan
hücreler `NA` sözlüğünde gerekçesiyle durur ve README "Desteklenen çağrılar" tablosuyla uyumludur.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException
from helpers import agen, model_response

from matriks_pii.guardrail import SESSION_KEY, TurkishPIIGuardrail

T1 = "17291716060"
NAME = "Ayşe Demir"
USER = f"Ben {NAME}, TCKN {T1}."
SYS = "Asistanın adı Ahmet Yılmaz."
RESP = "Merhaba <KISI_1>'e, kimlik <TCKN_1> doğrulandı."
RESP_OK = f"Merhaba {NAME}'e, kimlik {T1} doğrulandı."
IMG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
FORMATS = ["chat", "completions", "responses", "anthropic", "gemini"]
FEATURES = ["text", "multipart_image", "tool_args_request", "tool_args_response", "reasoning", "system",
            "metadata_bucket", "stream_text", "stream_tool_args", "stream_usage", "multi_choice", "unresolved_keep",
            "unresolved_strip", "session_missing", "too_large"]
NA: dict[tuple[str, str], str] = {
    **{("completions", f): "text completion isteğinde yalnız `prompt` vardır" for f in
       ("multipart_image", "tool_args_request", "tool_args_response", "reasoning", "system", "stream_tool_args")},
    ("anthropic", "reasoning"): "imzalı thinking blokları bilinçli olarak değiştirilmez (README Bilinen sınırlar)",
    ("gemini", "reasoning"): "imzalı düşünce parçaları değiştirilmez; Gemini yanıtında ayrı reasoning alanı yoktur",
    ("responses", "stream_usage"): "Responses akışında usage `response.completed` içinde gelir (stream_text kapsar)",
}


def G(**kw: Any) -> TurkishPIIGuardrail:
    kw.setdefault("default_on", True)
    kw.setdefault("event_hook", ["pre_call", "post_call"])
    return TurkishPIIGuardrail(guardrail_name="matriks-pii", **kw)


def _sse_json(blob: bytes) -> list[dict[str, Any]]:
    out = []
    for ev in blob.decode().replace("\r\n", "\n").split("\n\n"):
        for ln in ev.split("\n"):
            if ln.startswith("data:") and ln[5:].strip() not in ("", "[DONE]"):
                out.append(json.loads(ln[5:]))
    return out


# ---------------------------------------------------------------- biçim uyarlayıcıları
class Fmt:
    call_type = ""
    stream_call_type = ""
    bucket = "metadata"

    def request(self, feature: str) -> dict[str, Any]: raise NotImplementedError
    def masked_texts(self, data: dict[str, Any]) -> str: return json.dumps(data, ensure_ascii=False)
    def response(self, text: str, feature: str) -> Any: raise NotImplementedError
    def client_texts(self, resp: Any, feature: str) -> list[str]: raise NotImplementedError
    def stream(self, text: str, feature: str) -> list[Any]: raise NotImplementedError
    def stream_texts(self, items: list[Any], feature: str) -> str: raise NotImplementedError


class Chat(Fmt):
    call_type = stream_call_type = "acompletion"

    def request(self, feature: str) -> dict[str, Any]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": SYS}] if feature == "system" else []
        if feature == "multipart_image":
            msgs.append({"role": "user", "content": [{"type": "text", "text": USER},
                                                     {"type": "image_url", "image_url": {"url": IMG}}]})
        else:
            msgs.append({"role": "user", "content": USER})
        if feature == "tool_args_request":
            msgs.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "f", "arguments": json.dumps({"ad": NAME})}}]})
        return {"model": "m", "messages": msgs, "metadata": {}}

    def response(self, text: str, feature: str) -> Any:
        if feature == "tool_args_response":
            return model_response(None, tool_args=[json.dumps({"tc": "<TCKN_1>", "ad": "<KISI_1>"})])
        if feature == "reasoning":
            return model_response(text, reasoning="Kullanıcı <KISI_1>, kimlik <TCKN_1>.")
        if feature == "multi_choice":
            return model_response([text, "İkinci: <TCKN_1>"], n=2)
        return model_response(text)

    def client_texts(self, resp: Any, feature: str) -> list[str]:
        m = resp.choices[0].message
        if feature == "tool_args_response":
            return [m.tool_calls[0].function.arguments]
        if feature == "reasoning":
            return [m.content, m.reasoning_content]
        return [c.message.content for c in resp.choices]

    def stream(self, text: str, feature: str) -> list[Any]:
        from litellm.types.utils import (
            ChatCompletionDeltaToolCall,
            Delta,
            Function,
            ModelResponseStream,
            StreamingChoices,
        )

        if feature == "stream_tool_args":
            args = json.dumps({"tc": "<TCKN_1>", "not": 'a "b"'})
            return [ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=None, tool_calls=[
                ChatCompletionDeltaToolCall(index=0, function=Function(arguments=args[k:k + 3]))]))])
                for k in range(0, len(args), 3)] + [
                ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=None), finish_reason="tool_calls")])]
        out = [ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=text[k:k + 3]))])
               for k in range(0, len(text), 3)]
        out.append(ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=None), finish_reason="stop")]))
        if feature == "stream_usage":
            out.append(ModelResponseStream(choices=[]))
        return out

    def stream_texts(self, items: list[Any], feature: str) -> str:
        acc = ""
        for it in items:
            for ch in it.choices or []:
                if feature == "stream_tool_args":
                    acc += "".join(tc.function.arguments or "" for tc in ch.delta.tool_calls or [])
                else:
                    acc += ch.delta.content or ""
        return acc


class Completions(Fmt):
    call_type = stream_call_type = "atext_completion"

    def request(self, feature: str) -> dict[str, Any]:
        return {"model": "m", "prompt": USER, "metadata": {}}

    def response(self, text: str, feature: str) -> Any:
        from litellm.types.utils import TextChoices, TextCompletionResponse

        texts = [text, "İkinci: <TCKN_1>"] if feature == "multi_choice" else [text]
        return TextCompletionResponse(choices=[TextChoices(index=i, text=t, finish_reason="stop") for i, t in enumerate(texts)])

    def client_texts(self, resp: Any, feature: str) -> list[str]:
        return [c.text for c in resp.choices]

    def stream(self, text: str, feature: str) -> list[Any]:
        from litellm.types.utils import TextChoices, TextCompletionResponse

        out: list[Any] = [TextCompletionResponse(choices=[TextChoices(index=0, text=text[k:k + 3])]) for k in range(0, len(text), 3)]
        out.append(TextCompletionResponse(choices=[TextChoices(index=0, text="", finish_reason="stop")]))
        if feature == "stream_usage":
            out.append(TextCompletionResponse(choices=[]))
        return out

    def stream_texts(self, items: list[Any], feature: str) -> str:
        return "".join(ch.text or "" for it in items for ch in it.choices or [])


class Responses(Fmt):
    call_type = stream_call_type = "aresponses"
    bucket = "litellm_metadata"

    def request(self, feature: str) -> dict[str, Any]:
        content: Any = USER
        if feature == "multipart_image":
            content = [{"type": "input_text", "text": USER}, {"type": "input_image", "image_url": IMG}]
        items: list[dict[str, Any]] = [{"role": "user", "content": content}]
        if feature == "tool_args_request":
            items.append({"type": "function_call", "call_id": "c1", "name": "f", "arguments": json.dumps({"ad": NAME})})
        d: dict[str, Any] = {"model": "m", "input": items}
        if feature == "system":
            d["instructions"] = SYS
        return d

    def response(self, text: str, feature: str) -> Any:
        out: list[dict[str, Any]] = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]
        if feature == "tool_args_response":
            out = [{"type": "function_call", "name": "f", "call_id": "c1",
                    "arguments": json.dumps({"tc": "<TCKN_1>", "ad": "<KISI_1>"})}]
        elif feature == "reasoning":
            out.insert(0, {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Kullanıcı <KISI_1>, kimlik <TCKN_1>."}]})
        elif feature == "multi_choice":
            out.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "İkinci: <TCKN_1>"}]})
        return {"id": "r", "object": "response", "output": out}

    def client_texts(self, resp: Any, feature: str) -> list[str]:
        res = []
        for it in resp["output"]:
            if it["type"] == "message":
                res += [c["text"] for c in it["content"]]
            elif it["type"] == "function_call":
                res.append(it["arguments"])
            elif it["type"] == "reasoning":
                res += [s["text"] for s in it["summary"]]
        if feature == "reasoning":
            res = res[::-1]  # [içerik, reasoning] sırası
        return res

    def stream(self, text: str, feature: str) -> list[Any]:
        if feature == "stream_tool_args":
            args = json.dumps({"tc": "<TCKN_1>", "not": 'a "b"'})
            evs = [{"type": "response.function_call_arguments.delta", "output_index": 0, "delta": args[k:k + 3]}
                   for k in range(0, len(args), 3)]
            evs.append({"type": "response.function_call_arguments.done", "output_index": 0, "arguments": args})
            return evs
        evs = [{"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": text[k:k + 3]}
               for k in range(0, len(text), 3)]
        evs.append({"type": "response.output_text.done", "output_index": 0, "content_index": 0, "text": text})
        return evs

    def stream_texts(self, items: list[Any], feature: str) -> str:
        kind = "response.function_call_arguments.delta" if feature == "stream_tool_args" else "response.output_text.delta"
        return "".join(e["delta"] for e in items if e["type"] == kind)


class Anthropic(Fmt):
    call_type = stream_call_type = "anthropic_messages"
    bucket = "litellm_metadata"

    def request(self, feature: str) -> dict[str, Any]:
        content: Any = USER
        if feature == "multipart_image":
            content = [{"type": "text", "text": USER},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": IMG[22:]}}]
        msgs: list[dict[str, Any]] = [{"role": "user", "content": content}]
        if feature == "tool_args_request":
            msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "f", "input": {"ad": NAME}}]})
        d: dict[str, Any] = {"model": "c", "messages": msgs, "max_tokens": 10}
        if feature == "system":
            d["system"] = SYS
        return d

    def response(self, text: str, feature: str) -> Any:
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if feature == "tool_args_response":
            content = [{"type": "tool_use", "id": "t1", "name": "f", "input": {"tc": "<TCKN_1>", "ad": "<KISI_1>"}}]
        elif feature == "multi_choice":
            content.append({"type": "text", "text": "İkinci: <TCKN_1>"})
        return {"id": "msg", "type": "message", "role": "assistant", "content": content}

    def client_texts(self, resp: Any, feature: str) -> list[str]:
        return [b["text"] if b["type"] == "text" else json.dumps(b["input"], ensure_ascii=False) for b in resp["content"]]

    def stream(self, text: str, feature: str) -> list[Any]:
        raw = 'event: message_start\ndata: {"type":"message_start"}\n\n'
        if feature == "stream_tool_args":
            args = json.dumps({"tc": "<TCKN_1>", "not": 'a "b"'})
            for k in range(0, len(args), 3):
                d = {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": args[k:k + 3]}}
                raw += "event: content_block_delta\ndata: " + json.dumps(d) + "\n\n"
        else:
            for k in range(0, len(text), 3):
                d = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[k:k + 3]}}
                raw += "event: content_block_delta\ndata: " + json.dumps(d, ensure_ascii=False) + "\n\n"
        raw += 'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
        if feature == "stream_usage":
            raw += 'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":5}}\n\n'
        b = raw.encode()
        return [b[k:k + 23] for k in range(0, len(b), 23)]

    def stream_texts(self, items: list[Any], feature: str) -> str:
        acc = ""
        for o in _sse_json(b"".join(items)):
            if o.get("type") == "content_block_delta":
                acc += o["delta"].get("partial_json" if feature == "stream_tool_args" else "text", "")
        return acc


class Gemini(Fmt):
    call_type = "agenerate_content"
    stream_call_type = "agenerate_content_stream"

    def request(self, feature: str) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": USER}]
        if feature == "multipart_image":
            parts.append({"inlineData": {"mimeType": "image/png", "data": IMG[22:]}})
        contents: list[dict[str, Any]] = [{"role": "user", "parts": parts}]
        if feature == "tool_args_request":
            contents.append({"role": "model", "parts": [{"functionCall": {"name": "f", "args": {"ad": NAME}}}]})
        d: dict[str, Any] = {"model": "g", "contents": contents, "metadata": {}}
        if feature == "system":
            d["systemInstruction"] = {"parts": [{"text": SYS}]}
        return d

    def response(self, text: str, feature: str) -> Any:
        parts: list[dict[str, Any]] = [{"text": text}]
        if feature == "tool_args_response":
            parts = [{"functionCall": {"name": "f", "args": {"tc": "<TCKN_1>", "ad": "<KISI_1>"}}}]
        cands = [{"content": {"role": "model", "parts": parts}, "index": 0, "finishReason": "STOP"}]
        if feature == "multi_choice":
            cands.append({"content": {"role": "model", "parts": [{"text": "İkinci: <TCKN_1>"}]}, "index": 1, "finishReason": "STOP"})
        return {"candidates": cands}

    def client_texts(self, resp: Any, feature: str) -> list[str]:
        return [p["text"] if "text" in p else json.dumps(p["functionCall"]["args"], ensure_ascii=False)
                for c in resp["candidates"] for p in c["content"]["parts"]]

    def stream(self, text: str, feature: str) -> list[Any]:
        frames = []
        if feature == "stream_tool_args":
            frames.append({"candidates": [{"content": {"role": "model", "parts": [
                {"functionCall": {"name": "f", "args": {"tc": "<TCKN_1>", "not": 'a "b"'}}}]}, "index": 0, "finishReason": "STOP"}]})
        else:
            pieces = [text[k:k + 3] for k in range(0, len(text), 3)]
            for i, p in enumerate(pieces):
                c: dict[str, Any] = {"content": {"role": "model", "parts": [{"text": p}]}, "index": 0}
                if i == len(pieces) - 1:
                    c["finishReason"] = "STOP"
                frames.append({"candidates": [c]})
        if feature == "stream_usage":
            frames.append({"usageMetadata": {"totalTokenCount": 3}})
        raw = "".join("data: " + json.dumps(f, ensure_ascii=False) + "\n\n" for f in frames).encode()
        return [raw[k:k + 19] for k in range(0, len(raw), 19)]

    def stream_texts(self, items: list[Any], feature: str) -> str:
        acc = ""
        for o in _sse_json(b"".join(items)):
            for c in o.get("candidates", []):
                for p in c["content"]["parts"]:
                    acc += p.get("text", "") if feature != "stream_tool_args" else json.dumps(p.get("functionCall", {}).get("args", {}))
        return acc


ADAPTERS: dict[str, Fmt] = {"chat": Chat(), "completions": Completions(), "responses": Responses(),
                            "anthropic": Anthropic(), "gemini": Gemini()}


async def _pre(g: TurkishPIIGuardrail, a: Fmt, feature: str, stream: bool = False) -> dict[str, Any]:
    data = a.request(feature)
    if stream:
        data["stream"] = True
    ct = a.stream_call_type if stream else a.call_type
    out = await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=data, call_type=ct)
    return out if out is not None else data


async def _post(g: TurkishPIIGuardrail, data: dict[str, Any], resp: Any) -> Any:
    out = await g.async_post_call_success_hook(data=data, user_api_key_dict=None, response=resp)
    return resp if out is None else out


async def _stream(g: TurkishPIIGuardrail, data: dict[str, Any], items: list[Any]) -> list[Any]:
    if any(isinstance(i, bytes) for i in items):
        data["_litellm_raw_sse_stream"] = True
    return [x async for x in g.async_post_call_streaming_iterator_hook(None, agen(items), data)]


@pytest.mark.parametrize("feature", FEATURES)
@pytest.mark.parametrize("fmt", FORMATS)
async def test_parity(fmt: str, feature: str) -> None:
    if (fmt, feature) in NA:
        pytest.skip(NA[(fmt, feature)])
    a = ADAPTERS[fmt]
    g = G(**({"unresolved_placeholder": "strip"} if feature == "unresolved_strip" else
             {"max_text_chars": 1024} if feature == "too_large" else {}))

    if feature == "too_large":
        data = a.request("text")
        big = USER + " " + "x" * 1100
        blob = json.dumps(data, ensure_ascii=False).replace(USER, big)
        data = json.loads(blob)
        with pytest.raises(HTTPException) as ei:
            await g.async_pre_call_hook(user_api_key_dict=None, cache=None, data=data, call_type=a.call_type)
        assert ei.value.status_code == 413
        assert T1 not in json.dumps(ei.value.detail) and T1 not in json.dumps(data, ensure_ascii=False, default=str)
        return

    stream = feature.startswith("stream_")
    data = await _pre(g, a, "text" if stream else feature, stream=stream)
    sent = json.dumps(data, ensure_ascii=False, default=str)
    assert T1 not in sent and NAME not in sent, sent
    if feature == "system":
        assert "Ahmet Yılmaz" not in sent and "<KISI_" in sent
    if feature == "tool_args_request":
        assert sent.count(NAME) == 0
    if feature == "multipart_image":
        assert IMG[22:] in sent  # görsel verisine dokunulmaz
    if feature == "metadata_bucket":
        assert "matriks-pii" in data[a.bucket][SESSION_KEY]
        return

    if stream:
        items = await _stream(g, data, a.stream(RESP, feature))
        got = a.stream_texts(items, feature)
        if feature == "stream_tool_args":
            assert json.loads(got) == {"tc": T1, "not": 'a "b"'}
        else:
            assert got == RESP_OK
        if feature == "stream_usage":
            last = items[-1]
            if isinstance(last, bytes):
                assert b"usage" in b"".join(items).split(b"\n\n")[-2] or b"usage" in last
            else:
                assert not last.choices
        return

    if feature == "session_missing":
        g.store._d.clear()  # type: ignore[attr-defined]
        with pytest.raises(HTTPException) as ei:
            await _post(g, data, a.response(RESP, "text"))
        assert ei.value.status_code == 500 and ei.value.detail["error"] == "matriks_pii_session_missing"
        return

    if feature in ("unresolved_keep", "unresolved_strip"):
        client = await _post(g, data, a.response("Merhaba <KISI_1> ve <KISI_9>.", "text"))
        exp = f"Merhaba {NAME} ve <KISI_9>." if feature == "unresolved_keep" else f"Merhaba {NAME} ve ."
        assert a.client_texts(client, feature)[0] == exp
        return

    client = await _post(g, data, a.response(RESP, feature))
    texts = a.client_texts(client, feature)
    if feature == "tool_args_response":
        assert json.loads(texts[0]) == {"tc": T1, "ad": NAME}
    elif feature == "reasoning":
        assert texts == [RESP_OK, f"Kullanıcı {NAME}, kimlik {T1}."]
    elif feature == "multi_choice":
        assert texts == [RESP_OK, f"İkinci: {T1}"]
    elif feature == "system":  # sistem talimatı önce numaralanır: Ahmet Yılmaz = <KISI_1>
        assert texts[0] == f"Merhaba Ahmet Yılmaz'a, kimlik {T1} doğrulandı."
    else:
        assert texts[0] == RESP_OK
