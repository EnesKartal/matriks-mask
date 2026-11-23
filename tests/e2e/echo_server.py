"""OpenAI uyumlu yankı (echo) sunucusu — e2e testleri için.

Sözleşme:
* POST /v1/chat/completions: son user mesajını aynen döner.
  - stream=true → `X-Echo-Chunk-Size` (varsayılan 5) boyutunda SSE `chat.completion.chunk`, sonda finish_reason=stop + [DONE].
  - Mesaj `TOOL:` ile başlıyorsa: tool_calls=[{function:{name:"echo", arguments: json.dumps({"text": kalan})}}].
  - Mesaj `SLEEP:` ile başlıyorsa yanıt 2 sn gecikir (oturum tahliyesi senaryosu).
* POST /v1/completions: `prompt` metnini `choices[0].text` olarak döner (stream: 5'er karakter).
* POST /models/{model}:generateContent ve :streamGenerateContent (Gemini native; ?alt=sse): son user parçasını
  candidates[0].content.parts[0].text olarak döner; akışta 5'er karakterlik `data: {...}\n\n` çerçeveleri.
* GET /_received: alınan istek gövdelerinin listesi. POST /_reset: listeyi temizler.
Gövdeler asla yazdırılmaz (uvicorn log_level=warning).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
RECEIVED: list[dict[str, Any]] = []


def _last_user(body: dict[str, Any]) -> str:
    for m in reversed(body.get("messages") or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return "".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c or ""
    return ""


@app.get("/_received")
async def received() -> JSONResponse:
    return JSONResponse(RECEIVED)


@app.post("/_reset")
async def reset() -> JSONResponse:
    RECEIVED.clear()
    return JSONResponse({"ok": True})


@app.get("/v1/models")
async def models() -> JSONResponse:
    return JSONResponse({"object": "list", "data": [{"id": "echo", "object": "model"}]})


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Any:
    body = await request.json()
    RECEIVED.append(body)
    text = _last_user(body)
    cid = "chatcmpl-" + uuid.uuid4().hex[:12]
    created = int(time.time())
    tool = text.startswith("TOOL:")
    if text.startswith("SLEEP:"):
        await asyncio.sleep(2)
    if not body.get("stream"):
        msg: dict[str, Any] = {"role": "assistant", "content": None if tool else text}
        if tool:
            msg["tool_calls"] = [{"id": "call_1", "type": "function",
                                  "function": {"name": "echo", "arguments": json.dumps({"text": text[5:]}, ensure_ascii=False)}}]
        return JSONResponse({
            "id": cid, "object": "chat.completion", "created": created, "model": body.get("model", "echo"),
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool else "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    size = int(request.headers.get("x-echo-chunk-size", "5"))

    async def gen() -> Any:
        def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
            return "data: " + json.dumps({
                "id": cid, "object": "chat.completion.chunk", "created": created, "model": body.get("model", "echo"),
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }, ensure_ascii=False) + "\n\n"

        yield chunk({"role": "assistant", "content": ""})
        for k in range(0, len(text), size):
            yield chunk({"content": text[k : k + size]})
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/v1/completions")
async def completions(request: Request) -> Any:
    body = await request.json()
    RECEIVED.append(body)
    prompt = body.get("prompt")
    text = prompt[-1] if isinstance(prompt, list) else (prompt or "")
    cid = "cmpl-" + uuid.uuid4().hex[:12]
    created = int(time.time())
    if not body.get("stream"):
        return JSONResponse({"id": cid, "object": "text_completion", "created": created, "model": body.get("model", "echo"),
                             "choices": [{"index": 0, "text": text, "finish_reason": "stop", "logprobs": None}],
                             "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    size = int(request.headers.get("x-echo-chunk-size", "5"))

    async def gen() -> Any:
        def chunk(t: str, finish: str | None = None) -> str:
            return "data: " + json.dumps({"id": cid, "object": "text_completion", "created": created,
                                          "model": body.get("model", "echo"),
                                          "choices": [{"index": 0, "text": t, "finish_reason": finish, "logprobs": None}]},
                                         ensure_ascii=False) + "\n\n"

        for k in range(0, len(text), size):
            yield chunk(text[k : k + size])
        yield chunk("", "stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def _last_user_gemini(body: dict[str, Any]) -> str:
    contents = body.get("contents") or []
    if isinstance(contents, dict):
        contents = [contents]
    for c in reversed(contents):
        if c.get("role", "user") == "user":
            return "".join(p.get("text", "") for p in c.get("parts", []) if isinstance(p, dict))
    return ""


@app.post("/models/{rest:path}")
async def gemini(rest: str, request: Request) -> Any:
    body = await request.json()
    RECEIVED.append(body)
    text = _last_user_gemini(body)
    usage = {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}
    if rest.endswith(":generateContent"):
        return JSONResponse({"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP",
                                             "index": 0}], "usageMetadata": usage, "modelVersion": "echo"})
    size = int(request.headers.get("x-echo-chunk-size", "5"))

    async def gen() -> Any:
        pieces = [text[k : k + size] for k in range(0, len(text), size)] or [""]
        for i, p in enumerate(pieces):
            cand: dict[str, Any] = {"content": {"role": "model", "parts": [{"text": p}]}, "index": 0}
            frame: dict[str, Any] = {"candidates": [cand], "modelVersion": "echo"}
            if i == len(pieces) - 1:
                cand["finishReason"] = "STOP"
                frame["usageMetadata"] = usage
            yield "data: " + json.dumps(frame, ensure_ascii=False) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9911
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
