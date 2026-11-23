"""Akış (streaming) yanıtlarında yer tutucuların parça sınırlarında güvenle geri çevrilmesi.

Desteklenen akış biçimleri:
* Chat Completions `ModelResponseStream` (choices[i].delta.content / reasoning_content / tool_calls[j].function.arguments)
* Text Completions akış parçaları (choices[i].text)
* Responses API olayları (`response.output_text.delta`, `response.function_call_arguments.delta`,
  `response.reasoning_summary_text.delta`, `*.done`, `response.completed`)
* Anthropic Messages ham SSE (bytes/str; `content_block_delta` text/input_json, `content_block_stop`)

Değişmez: yayılan delta'ların birleşimi == Reverter.revert(tüm metin). Tool/JSON argüman akışında değerler
JSON-kaçışlı yazılır. İmzalı düşünme (thinking) delta'larına dokunulmaz.
"""

from __future__ import annotations

import codecs
import copy
import json
from collections.abc import Callable
from typing import Any

from .revert import Reverter, StreamingReverter


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj: Any, key: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def _copy(item: Any) -> Any:
    if hasattr(item, "model_copy"):
        return item.model_copy(deep=True)
    return copy.deepcopy(item)


class StreamProcessor:
    """Her choice/alan/blok için ayrı StreamingReverter tutar; `process` 0..n parça döndürür."""

    def __init__(
        self,
        reverter: Reverter,
        holdback_max_chars: int,
        restore_tools: bool = True,
        revert_obj: Callable[[Any, str], Any] | None = None,
    ) -> None:
        self.reverter = reverter
        self.holdback = holdback_max_chars
        self.restore_tools = restore_tools
        self.revert_obj = revert_obj  # tam nesneyi (ör. response.completed içindeki yanıt) kopyada geri çevirir
        self.states: dict[tuple[Any, ...], StreamingReverter] = {}
        self.template: Any = None
        self._sse_buf = ""
        self._sse_bytes = False
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def _st(self, key: tuple[Any, ...]) -> StreamingReverter:
        st = self.states.get(key)
        if st is None:
            st = self.states[key] = StreamingReverter(self.reverter, self.holdback, json_escape=key[0] == "t")
        return st

    # ------------------------------------------------------------------ giriş noktası
    def process(self, item: Any) -> list[Any]:
        if isinstance(item, bytes | bytearray | str):
            return self._process_sse(item)
        choices = _get(item, "choices")
        if isinstance(choices, list):
            return [self._process_chat(item)] if choices else [item]
        etype = _get(item, "type")
        if isinstance(etype, str) and etype.startswith("response."):
            return self._process_responses(item, etype)
        if isinstance(etype, str) and etype.startswith(("content_block", "message_")):
            out = self._anthropic_event(item if isinstance(item, dict) else _to_dict(item))
            return out if out is not None else [item]
        return [item]

    # ------------------------------------------------------------------ Chat Completions
    def _process_chat(self, item: Any) -> Any:
        choices = _get(item, "choices")
        out = None

        def target() -> Any:
            nonlocal out
            if out is None:
                out = _copy(item)
            return out

        for pos, ch in enumerate(choices):
            ci = _get(ch, "index", pos) or 0
            delta = _get(ch, "delta")
            if delta is None:
                # /completions akışı: choices[i].text (delta yok)
                txt = _get(ch, "text")
                if isinstance(txt, str):
                    new = self._st(("k", ci)).feed(txt) if txt else ""
                    if _get(ch, "finish_reason"):
                        st = self.states.pop(("k", ci), None)
                        new += st.flush() if st is not None else ""
                    if new != txt:
                        _set(_get(target(), "choices")[pos], "text", new)
                continue
            finish = _get(ch, "finish_reason")
            new_vals: dict[str, Any] = {}
            content = _get(delta, "content")
            if isinstance(content, str) and content:
                new_vals["content"] = self._st(("c", ci)).feed(content)
            rc = _get(delta, "reasoning_content")
            if isinstance(rc, str) and rc:
                new_vals["reasoning_content"] = self._st(("r", ci)).feed(rc)
            tool_args: dict[int, str] = {}
            tcs = _get(delta, "tool_calls")
            if self.restore_tools and isinstance(tcs, list):
                for j, tc in enumerate(tcs):
                    fn = _get(tc, "function")
                    args = _get(fn, "arguments") if fn is not None else None
                    tidx = _get(tc, "index", j) or 0
                    if isinstance(args, str) and args:
                        tool_args[j] = self._st(("t", ci, tidx)).feed(args)
            flushed: dict[str, str] = {}
            flushed_tools: dict[int, str] = {}
            if finish:
                for key in list(self.states):
                    if key[1] != ci or key[0] == "k":
                        continue
                    rest = self.states[key].flush()
                    if not rest:
                        continue
                    if key[0] == "c":
                        flushed["content"] = rest
                    elif key[0] == "r":
                        flushed["reasoning_content"] = rest
                    else:
                        flushed_tools[key[2]] = rest
            changed = (
                any(new_vals.get(k) != _get(delta, k) for k in new_vals)
                or bool(flushed)
                or bool(flushed_tools)
                or any(tool_args[j] != _get(_get(tcs[j], "function"), "arguments") for j in tool_args)
            )
            if not changed:
                continue
            tobj = target()
            tch = _get(tobj, "choices")[pos]
            tdelta = _get(tch, "delta")
            for k, v in new_vals.items():
                _set(tdelta, k, v + flushed.pop(k, ""))
            for k, v in flushed.items():
                _set(tdelta, k, (_get(tdelta, k) or "") + v)
            ttcs = _get(tdelta, "tool_calls")
            for j, v in tool_args.items():
                fn = _get(ttcs[j], "function")
                tidx = _get(ttcs[j], "index", j) or 0
                _set(fn, "arguments", v + flushed_tools.pop(tidx, ""))
            if flushed_tools:
                self._append_tool_rest(tdelta, flushed_tools)
        self.template = item
        return out if out is not None else item

    def _append_tool_rest(self, tdelta: Any, rest: dict[int, str]) -> None:
        new: list[Any]
        try:
            from litellm.types.utils import ChatCompletionDeltaToolCall, Function

            new = [ChatCompletionDeltaToolCall(index=t, function=Function(arguments=v)) for t, v in rest.items()]
        except Exception:  # pragma: no cover - litellm yoksa dict
            new = [{"index": t, "function": {"arguments": v}} for t, v in rest.items()]
        cur = _get(tdelta, "tool_calls") or []
        _set(tdelta, "tool_calls", list(cur) + new)

    # ------------------------------------------------------------------ Responses API olayları
    def _process_responses(self, item: Any, etype: str) -> list[Any]:
        oi = _get(item, "output_index", 0) or 0
        if etype in ("response.output_text.delta", "response.function_call_arguments.delta",
                     "response.reasoning_summary_text.delta", "response.custom_tool_call_input.delta"):
            delta = _get(item, "delta")
            if not isinstance(delta, str) or not delta:
                return [item]
            if etype == "response.output_text.delta":
                key: tuple[Any, ...] = ("c", "x", oi, _get(item, "content_index", 0) or 0)
            elif etype == "response.reasoning_summary_text.delta":
                key = ("r", "x", oi, _get(item, "summary_index", 0) or 0)
            else:
                if not self.restore_tools:
                    return [item]
                key = ("t", "x", oi, 0)
            new = self._st(key).feed(delta)
            if new == delta:
                return [item]
            out = _copy(item)
            _set(out, "delta", new)
            return [out]
        if etype in ("response.output_text.done", "response.function_call_arguments.done",
                     "response.reasoning_summary_text.done", "response.content_part.done",
                     "response.output_item.done", "response.custom_tool_call_input.done"):
            pre = self._flush_responses(item, oi, etype)
            out = _copy(item)
            for fld in ("text", "arguments", "input"):
                v = _get(out, fld)
                if isinstance(v, str):
                    _set(out, fld, self._revert_full(v, json_mode=fld != "text"))
            for fld in ("part", "item"):
                v = _get(out, fld)
                if v is not None and self.revert_obj is not None:
                    _set(out, fld, self.revert_obj({"output": [v]} if fld == "item" else {"output": [{"type": "message", "content": [v]}]}, fld))
            return pre + [out]
        if etype in ("response.completed", "response.incomplete", "response.failed", "response.done"):
            resp = _get(item, "response")
            if resp is not None and self.revert_obj is not None:
                out = _copy(item)
                _set(out, "response", self.revert_obj(_get(out, "response"), "response"))
                return [out]
        return [item]

    def _flush_responses(self, item: Any, oi: int, etype: str) -> list[Any]:
        """`*.done` öncesinde aynı çıktı için tamponda kalanı sentetik delta olayı olarak yayar."""
        kind = {"response.output_text.done": "c", "response.function_call_arguments.done": "t",
                "response.reasoning_summary_text.done": "r", "response.custom_tool_call_input.done": "t"}.get(etype)
        if kind is None:
            return []
        ci = _get(item, "content_index", None)
        si = _get(item, "summary_index", None)
        sub = (ci if kind == "c" else si if kind == "r" else 0) or 0
        st = self.states.pop((kind, "x", oi, sub), None)
        rest = st.flush() if st else ""
        if not rest:
            return []
        dtype = {"c": "response.output_text.delta", "t": "response.function_call_arguments.delta",
                 "r": "response.reasoning_summary_text.delta"}[kind]
        ev: dict[str, Any] = {"type": dtype, "output_index": oi, "delta": rest}
        for fld in ("item_id", "content_index", "summary_index"):
            v = _get(item, fld)
            if v is not None:
                ev[fld] = v
        return [ev]

    def _revert_full(self, text: str, json_mode: bool) -> str:
        if json_mode:
            try:
                obj = json.loads(text)
            except ValueError:
                return self.reverter.revert(text, json_escape=True)
            if self.revert_obj is not None:
                return json.dumps(self.revert_obj(obj, "json"), ensure_ascii=False, separators=(",", ":"))
        return self.reverter.revert(text)

    # ------------------------------------------------------------------ Anthropic ham SSE
    def _process_sse(self, chunk: Any) -> list[Any]:
        is_bytes = isinstance(chunk, bytes | bytearray)
        self._sse_bytes = is_bytes
        # bayt parçaları çok baytlı UTF-8 karakterin (ş, İ, ğ) ortasından bölünebilir → artımlı çözücü.
        # Geçersiz UTF-8 → UnicodeDecodeError yükselir; kanca revert_fail_mode'a göre yönetir.
        s = self._dec.decode(bytes(chunk), final=False) if is_bytes else chunk
        # CRLF normalizasyonu tampon üzerinde: "\r" ve "\n" ayrı parçalarda gelse de olay sınırı bulunur
        self._sse_buf = (self._sse_buf + s).replace("\r\n", "\n")
        # yalnız tamamlanmış olayları işle ("\n\n" ile biten); kalanı tut
        idx = self._sse_buf.rfind("\n\n")
        if idx < 0:
            return []
        ready, self._sse_buf = self._sse_buf[: idx + 2], self._sse_buf[idx + 2 :]
        out_events: list[str] = []
        for ev in ready.split("\n\n"):
            if not ev:
                continue
            out_events.extend(self._sse_event(ev))
        res = "".join(e + "\n\n" for e in out_events)
        return [res.encode("utf-8") if is_bytes else res] if res else []

    def _sse_event(self, ev: str) -> list[str]:
        lines = ev.split("\n")
        data_i = next((i for i, ln in enumerate(lines) if ln.startswith("data:")), None)
        if data_i is None:
            return [ev]
        payload = lines[data_i][5:].strip()
        try:
            obj = json.loads(payload)
        except ValueError:
            return [ev]
        if isinstance(obj, dict) and "candidates" in obj:
            g = self._gemini_event(obj)
            if g is None:
                return [ev]
            prefix = "\n".join(lines[:data_i])  # "event:"/"id:" satırları varsa korunur
            body = "data: " + json.dumps(g, ensure_ascii=False, separators=(",", ":"))
            return [(prefix + "\n" + body) if prefix else body]
        if not isinstance(obj, dict):
            return [ev]
        res = self._anthropic_event(obj)
        if res is None:
            return [ev]
        out = []
        for o in res:
            name = o.get("type", "")
            out.append(f"event: {name}\ndata: {json.dumps(o, ensure_ascii=False, separators=(',', ':'))}")
        return out

    def _anthropic_event(self, obj: dict[str, Any]) -> list[Any] | None:
        t = obj.get("type")
        idx = obj.get("index", 0)
        if t == "content_block_delta":
            d = obj.get("delta") or {}
            dt = d.get("type")
            if dt == "text_delta" and isinstance(d.get("text"), str):
                new = self._st(("c", "a", idx)).feed(d["text"])
                if new == d["text"]:
                    return None
                o = copy.deepcopy(obj)
                o["delta"]["text"] = new
                return [o]
            if dt == "input_json_delta" and isinstance(d.get("partial_json"), str) and self.restore_tools:
                new = self._st(("t", "a", idx)).feed(d["partial_json"])
                if new == d["partial_json"]:
                    return None
                o = copy.deepcopy(obj)
                o["delta"]["partial_json"] = new
                return [o]
            return None  # thinking/signature delta'ları imzalı → dokunma
        if t == "content_block_stop":
            pre = []
            for kind, dtype, fld in (("c", "text_delta", "text"), ("t", "input_json_delta", "partial_json")):
                st = self.states.pop((kind, "a", idx), None)
                rest = st.flush() if st else ""
                if rest:
                    pre.append({"type": "content_block_delta", "index": idx, "delta": {"type": dtype, fld: rest}})
            return pre + [obj] if pre else None
        return None

    # ------------------------------------------------------------------ Gemini streamGenerateContent
    def _gemini_event(self, obj: dict[str, Any]) -> dict[str, Any] | None:
        """`{"candidates":[{"content":{"parts":[{"text":…}]},"finishReason":…,"index":i}], "usageMetadata":…}`"""
        changed = False
        o = copy.deepcopy(obj)
        for pos, cand in enumerate(o.get("candidates") or []):
            if not isinstance(cand, dict):
                continue
            ci = cand.get("index", pos)
            content = cand.get("content") if isinstance(cand.get("content"), dict) else None
            parts = content.get("parts") if content is not None and isinstance(content.get("parts"), list) else []
            last_text: dict[str, Any] | None = None
            for j, part in enumerate(parts):
                if not isinstance(part, dict):
                    continue
                if isinstance(part.get("text"), str) and not (part.get("thought") and part.get("thoughtSignature")):
                    new = self._st(("c", "g", ci, j)).feed(part["text"])
                    if new != part["text"]:
                        part["text"] = new
                        changed = True
                    last_text = part
                fc = part.get("functionCall")
                if isinstance(fc, dict) and isinstance(fc.get("args"), dict | list) and self.restore_tools and self.revert_obj:
                    new_args = self.revert_obj(fc["args"], "json")
                    if new_args != fc["args"]:
                        fc["args"] = new_args
                        changed = True
            if cand.get("finishReason"):
                rest = ""
                for key in sorted(k for k in self.states if k[:3] == ("c", "g", ci)):
                    rest += self.states.pop(key).flush()
                if rest:
                    changed = True
                    if last_text is not None:
                        last_text["text"] += rest
                    else:
                        if content is None:
                            content = cand["content"] = {"role": "model", "parts": []}
                        content.setdefault("parts", []).append({"text": rest})
        return o if changed else None

    # ------------------------------------------------------------------ akış sonu / hata
    def final_items(self) -> list[Any]:
        """finish_reason/stop gelmeden akış bittiyse tamponda kalanı taşıyan sentetik parça(lar)."""
        items: list[Any] = []
        self._flush_decoder()
        if self._sse_buf:
            rest_ev = self._sse_buf
            self._sse_buf = ""
            evs = []
            for raw_ev in rest_ev.split("\n\n"):
                if raw_ev:
                    evs.extend(self._sse_event(raw_ev))
            res = "".join(e + "\n\n" for e in evs)
            if res:
                items.append(res.encode("utf-8") if self._sse_bytes else res)
        chat = self._final_chat_chunk()
        if chat is not None:
            items.append(chat)
        for key in list(self.states):  # Responses/Anthropic artakalanı
            rest = self.states.pop(key).flush()
            if not rest:
                continue
            if key[1] == "a":
                ev = {"type": "content_block_delta", "index": key[2],
                      "delta": {"type": "text_delta" if key[0] == "c" else "input_json_delta",
                                "text" if key[0] == "c" else "partial_json": rest}}
                s = f"event: content_block_delta\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                items.append(s.encode("utf-8") if self._sse_bytes else s)
            elif key[1] == "g":
                gev = {"candidates": [{"content": {"parts": [{"text": rest}], "role": "model"}, "index": key[2]}]}
                items.append(self._enc(f"data: {json.dumps(gev, ensure_ascii=False, separators=(',', ':'))}\n\n"))
            elif key[1] == "x":
                items.append({"type": {"c": "response.output_text.delta", "t": "response.function_call_arguments.delta",
                                       "r": "response.reasoning_summary_text.delta"}[key[0]],
                              "output_index": key[2], "delta": rest})
        return items

    def _flush_decoder(self) -> None:
        """Artımlı çözücüde kalan yarım bayt dizisini tampona ekle (akış sonu / hata yolu)."""
        try:
            tail = self._dec.decode(b"", final=True)
        except UnicodeDecodeError:
            tail = ""
        self._dec.reset()
        if tail:
            self._sse_buf += tail

    def _enc(self, s: str) -> Any:
        return s.encode("utf-8") if self._sse_bytes else s

    def _final_chat_chunk(self) -> Any | None:
        if self.template is None:
            return None
        chat_keys = [k for k in self.states if not isinstance(k[1], str)]
        rest = {k: self.states.pop(k).flush() for k in chat_keys}
        rest = {k: v for k, v in rest.items() if v}
        if not rest or self.template is None:
            return None
        chunk = _copy(self.template)
        choices = _get(chunk, "choices")
        by_index = {(_get(c, "index", i) or 0): c for i, c in enumerate(choices)}
        for ch in choices:
            _set(ch, "finish_reason", None)
            delta = _get(ch, "delta")
            if delta is None:
                if isinstance(_get(ch, "text"), str):
                    _set(ch, "text", "")
                continue
            _set(delta, "content", None)
            if _get(delta, "reasoning_content") is not None:
                _set(delta, "reasoning_content", None)
            _set(delta, "tool_calls", None)
        for key, v in rest.items():
            ch = by_index.get(key[1]) or choices[0]
            if key[0] == "k":
                _set(ch, "text", (_get(ch, "text") or "") + v)
                continue
            delta = _get(ch, "delta")
            if key[0] == "c":
                _set(delta, "content", v)
            elif key[0] == "r":
                _set(delta, "reasoning_content", v)
            else:
                self._append_tool_rest(delta, {key[2]: v})
        return chunk

    def drain_raw(self) -> list[Any]:
        """Hata yolunda (fail-open): tamponları geri çevirmeden, sırayı koruyarak boşalt."""
        items: list[Any] = []
        self._flush_decoder()
        rest = {k: st.drain_raw() for k, st in self.states.items() if st.buf}
        self.states.clear()
        # SSE tabanlı akışların (Anthropic "a", Gemini "g") ve Responses ("x") tamponu: daha önce işlenmiş olaylardan
        # kaldığı için ham olay tamponundan (sonraki, yarım olaylar) ÖNCE yayılır
        for key in [k for k in rest if isinstance(k[1], str)]:
            raw = rest.pop(key)
            if key[1] == "a":
                delta = ({"type": "input_json_delta", "partial_json": raw} if key[0] == "t"
                         else {"type": "text_delta", "text": raw})
                ev = {"type": "content_block_delta", "index": key[2], "delta": delta}
                items.append(self._enc(f"event: content_block_delta\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"))
            elif key[1] == "g":
                gev = {"candidates": [{"content": {"parts": [{"text": raw}], "role": "model"}, "index": key[2]}]}
                items.append(self._enc(f"data: {json.dumps(gev, ensure_ascii=False)}\n\n"))
            elif key[1] == "x":
                items.append({"type": _RESP_DELTA[key[0]], "output_index": key[2], "delta": raw})
        if self._sse_buf:
            items.append(self._enc(self._sse_buf))
            self._sse_buf = ""
        if rest and self.template is not None:
            chunk = _copy(self.template)
            for ch in _get(chunk, "choices"):
                _set(ch, "finish_reason", None)
                d = _get(ch, "delta")
                if d is None:  # /completions
                    _set(ch, "text", "".join(v for k, v in rest.items() if k[0] in ("c", "k")))
                    continue
                _set(d, "content", "".join(v for k, v in rest.items() if k[0] == "c"))
                _set(d, "tool_calls", None)
            items.append(chunk)
        return items


_RESP_DELTA = {"c": "response.output_text.delta", "t": "response.function_call_arguments.delta",
               "r": "response.reasoning_summary_text.delta"}


def _to_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()  # type: ignore[no-any-return]
    return dict(item)
