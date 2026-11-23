"""İstek/yanıt gövdelerindeki metin alanlarını bulan ve YERİNDE değiştiren gezgin.

Kurallar:
* Değişiklik mevcut dict/list'e yerinde yazılır (proxy'nin sığ gövde kopyası da maskelensin).
* JSON string'ler (tool argümanları, JSON içerikli mesajlar) çözülür; string/sayı yaprakları VE anahtarlar gezilir,
  yalnız değişiklik varsa yeniden serileştirilir (kaçış/escape otomatik).
* Yapısal alanlar (type, id, call_id, role, model, signature, base64 veri, URL) gezilmez.
* İmzalı düşünme blokları (Anthropic `thinking`/`redacted_thinking`) değiştirilmez: imza bozulur.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import TurkishPIIConfig

TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})
METADATA_BUCKET_CALLS = frozenset({"responses", "aresponses", "anthropic_messages", "aanthropic_messages"})
SIGNED_BLOCKS = frozenset({"thinking", "redacted_thinking"})
SKIP_PART_TYPES = frozenset({"image_url", "input_image", "image", "input_audio", "audio", "file", "input_file", "refusal"})
STRUCTURAL_KEYS = frozenset(
    {
        "type", "id", "call_id", "tool_call_id", "tool_use_id", "role", "model", "object", "index", "status",
        "signature", "encrypted_content", "media_type", "mime_type", "url", "image_url", "file_id", "file_data",
        "detail", "format", "cache_control", "citations", "annotations", "logprobs", "server_label",
    }
)
_MIN_NUMBER_DIGITS = 5  # bundan kısa sayılar (adet, fiyat) PII olamaz; JSON'da sayı olarak gelen TCKN/kart yakalanır


@dataclass
class TextRef:
    get: Callable[[], str]
    set: Callable[[str], None]
    kind: str  # text | json_leaf | json_key | name
    role: str | None
    path: str
    key: str = ""  # JSON yaprağının anahtarı (bağlam öneki için)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _setter(obj: Any, key: Any) -> Callable[[str], None]:
    if isinstance(obj, (dict, list)):

        def _s(v: str) -> None:
            obj[key] = v

    else:

        def _s(v: str) -> None:
            setattr(obj, key, v)

    return _s


def _getter(obj: Any, key: Any) -> Callable[[str], str]:  # type: ignore[type-arg]
    if isinstance(obj, (dict, list)):

        def _g() -> str:
            return obj[key]  # type: ignore[no-any-return]

    else:

        def _g() -> str:
            return getattr(obj, key)  # type: ignore[no-any-return]

    return _g  # type: ignore[return-value]


def _text(obj: Any, key: Any, kind: str, role: str | None, path: str, ckey: str = "") -> TextRef:
    return TextRef(_getter(obj, key), _setter(obj, key), kind, role, path, ckey)  # type: ignore[arg-type]


# ---------------------------------------------------------------- JSON anahtarı bağlamı
_KEY_CONTEXT: tuple[tuple[tuple[str, ...], str], ...] = (
    (("dogum_yeri", "dogumyeri", "birth_place", "birthplace", "place_of_birth"), "Doğum yeri: "),
    (("dogum", "birth", "dob"), "Doğum tarihi: "),
    (("musteri_no", "musterino", "customer_id", "customer_no", "cari_kod"), "Müşteri no: "),
    (("hesap_no", "hesapno", "account_no", "account_number"), "Hesap no: "),
    (("vkn", "vergi"), "Vergi no: "),
    (("pasaport", "passport"), "Pasaport no: "),
    (("ehliyet", "driver_license", "surucu_belgesi"), "Ehliyet no: "),
    (("sifre", "parola", "password", "passwd", "pin"), "Şifre: "),
    (("ad", "adi", "isim", "ismi", "name", "soyad", "soyadi", "surname", "ad_soyad", "adsoyad", "full_name", "fullname",
      "first_name", "firstname", "last_name", "lastname", "musteri_adi", "customer_name", "kisi", "yetkili", "contact",
      "unvan", "sahibi", "owner", "holder"), "Adı soyadı: "),
)


def context_prefix(ref: TextRef) -> str:
    """JSON yaprağında anahtar adı bağlam taşır ({"ad": "Ayşe"}); analize önek olarak verilir."""
    if ref.kind not in ("json_leaf", "json_number") or not ref.key:
        return ""
    from .text_utils import ascii_fold, tr_lower

    key = ascii_fold(tr_lower(ref.key)).replace("-", "_").strip("_")
    if not key or len(key) > 24:
        return ""
    parts = set(key.split("_"))
    for names, prefix in _KEY_CONTEXT:
        if key in names or any(n in parts for n in names if "_" not in n):
            return prefix
    return ""


def metadata_bucket(data: dict[str, Any], call_type: str | None) -> dict[str, Any]:
    """responses/anthropic çağrılarında `litellm_metadata`, diğerlerinde `metadata`."""
    if isinstance(data.get("litellm_metadata"), dict) and (call_type in METADATA_BUCKET_CALLS or "metadata" not in data):
        return data["litellm_metadata"]  # type: ignore[no-any-return]
    if call_type in METADATA_BUCKET_CALLS:
        if not isinstance(data.get("litellm_metadata"), dict):
            data["litellm_metadata"] = {}
        return data["litellm_metadata"]  # type: ignore[no-any-return]
    md = data.get("metadata")
    if not isinstance(md, dict):
        if md is None:
            data["metadata"] = {}
            return data["metadata"]  # type: ignore[no-any-return]
        if not isinstance(data.get("litellm_metadata"), dict):
            data["litellm_metadata"] = {}
        return data["litellm_metadata"]  # type: ignore[no-any-return]
    return md


# ---------------------------------------------------------------- genel yaprak gezgini
def _rename_key(d: dict[str, Any], old: str) -> Callable[[str], None]:
    def _s(new: str) -> None:
        if new == old or old not in d:
            return
        items = list(d.items())
        d.clear()
        for k, v in items:
            d[new if k == old else k] = v

    return _s


def walk_leaves(node: Any, path: str, role: str | None, on_change: Callable[[], None] | None = None,
                keys: bool = True) -> Iterator[TextRef]:
    """dict/list ağacındaki string ve uzun sayı yaprakları (+ anahtarlar). Yapısal anahtarlar atlanır."""

    def mark(setter: Callable[[Any], None], getter: Callable[[], Any]) -> Callable[[Any], None]:
        def _s(v: Any) -> None:
            if str(getter()) != str(v) or type(getter()) is not type(v):
                setter(v)
                if on_change:
                    on_change()

        return _s

    if isinstance(node, dict):
        if node.get("type") in SIGNED_BLOCKS or node.get("type") in SKIP_PART_TYPES:
            return
        for k in list(node.keys()):
            v = node[k]
            if k in STRUCTURAL_KEYS:
                continue
            p = f"{path}.{k}"
            if isinstance(v, str):
                yield TextRef(_getter(node, k), mark(_setter(node, k), _getter(node, k)), "json_leaf", role, p, k)  # type: ignore[arg-type]
            elif _long_number(v):
                g = _num_getter(node, k)
                yield TextRef(g, mark(_setter(node, k), g), "json_number", role, p, k)
            elif isinstance(v, dict | list):
                yield from walk_leaves(v, p, role, on_change, keys)
            if keys and isinstance(k, str) and len(k) >= 3 and any(c.isdigit() or c.isupper() for c in k):
                # anahtar olarak kullanılmış değerler ({"Ayşe Demir": {...}}, {"17291716060": ...})
                kk = k

                def kg(kk: str = kk) -> str:
                    return kk

                yield TextRef(kg, mark(_rename_key(node, kk), kg), "json_key", role, f"{path}.<anahtar>")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            p = f"{path}[{i}]"
            if isinstance(v, str):
                yield TextRef(_getter(node, i), mark(_setter(node, i), _getter(node, i)), "json_leaf", role, p)  # type: ignore[arg-type]
            elif _long_number(v):
                g = _num_getter(node, i)
                yield TextRef(g, mark(_setter(node, i), g), "json_number", role, p)
            elif isinstance(v, dict | list):
                yield from walk_leaves(v, p, role, on_change, keys)


def _long_number(v: Any) -> bool:
    """PII olabilecek uzun sayı (bool, NaN, sonsuz hariç)."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return False
    if isinstance(v, float) and not math.isfinite(v):
        return False
    return len(str(abs(int(v)))) >= _MIN_NUMBER_DIGITS


def _num_getter(obj: Any, key: Any) -> Callable[[], str]:
    def _g() -> str:
        v = obj[key]
        return v if isinstance(v, str) else str(v)

    return _g


class _Flag:
    __slots__ = ("changed",)

    def __init__(self) -> None:
        self.changed = False

    def __call__(self) -> None:
        self.changed = True


def _looks_json(s: str) -> bool:
    t = s.lstrip()
    return bool(t) and t[0] in "{[" and len(t) >= 2


def json_or_text(holder: Any, key: Any, path: str, role: str | None, commits: list[Callable[[], None]],
                 force_json: bool = False, parse_json: bool = True) -> Iterator[TextRef]:
    """String alan: JSON ise yaprakları (+ anahtarları), değilse düz metin.

    `parse_json=False` (yanıt içeriği, biçim korunur): JSON metin ham hâliyle "text_json" türünde verilir; geri çevirmede
    değerler JSON-kaçışlı yazılır, girinti/anahtar sırası bozulmaz."""
    raw = _get(holder, key) if not isinstance(holder, list) else holder[key]
    if not isinstance(raw, str) or not raw:
        return
    if not parse_json and not force_json:
        kind = "text"
        if _looks_json(raw):
            try:
                json.loads(raw)
                kind = "text_json"
            except (ValueError, TypeError):
                pass
        yield _text(holder, key, kind, role, path)
        return
    obj: Any = None
    if force_json or _looks_json(raw):
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            obj = None
    if not isinstance(obj, dict | list):
        yield _text(holder, key, "text", role, path)
        return
    flag = _Flag()
    setter = _setter(holder, key)
    ensure_ascii = "\\u" in raw  # orijinal kaçış biçimini koru

    def commit() -> None:
        if flag.changed:
            setter(json.dumps(obj, ensure_ascii=ensure_ascii, separators=(",", ":")))

    commits.append(commit)
    yield from walk_leaves(obj, path, role, flag)


# ---------------------------------------------------------------- içerik blokları
def _content(holder: Any, key: str, path: str, role: str | None, commits: list[Callable[[], None]],
             parse_json: bool = True) -> Iterator[TextRef]:
    c = _get(holder, key)
    if c is None:
        return
    if isinstance(c, str):
        yield from json_or_text(holder, key, path, role, commits, parse_json=parse_json)
        return
    if not isinstance(c, list):
        return
    for i, part in enumerate(c):
        p = f"{path}[{i}]"
        if isinstance(part, str):
            yield from json_or_text(c, i, p, role, commits, parse_json=parse_json)
            continue
        ptype = _get(part, "type")
        if ptype in SIGNED_BLOCKS or ptype in SKIP_PART_TYPES:
            continue
        if ptype in TEXT_PART_TYPES and isinstance(_get(part, "text"), str):
            yield from json_or_text(part, "text", f"{p}.text", role, commits, parse_json=parse_json)
        elif ptype == "tool_use":
            inp = _get(part, "input")
            if isinstance(inp, dict | list):
                yield from walk_leaves(inp, f"{p}.input", role)
            elif isinstance(inp, str):
                yield from json_or_text(part, "input", f"{p}.input", role, commits, force_json=True)
        elif ptype in ("tool_result", "search_result"):
            yield from _content(part, "content", f"{p}.content", role, commits)
            if ptype == "search_result" and isinstance(_get(part, "title"), str):
                yield _text(part, "title", "text", role, f"{p}.title")
        elif ptype == "document":
            src = _get(part, "source")
            if isinstance(src, dict) and src.get("type") == "text" and isinstance(src.get("data"), str):
                yield _text(src, "data", "text", role, f"{p}.source.data")
            elif isinstance(src, dict) and src.get("type") == "content":
                yield from _content(src, "content", f"{p}.source.content", role, commits)
            for fld in ("title", "context"):
                if isinstance(_get(part, fld), str):
                    yield _text(part, fld, "text", role, f"{p}.{fld}")
        elif isinstance(part, dict):
            yield from walk_leaves(part, p, role, keys=False)  # bilinmeyen blok türü: yapısal olmayan yapraklar


def _role_allowed(role: str | None, cfg: TurkishPIIConfig, skip_system: bool) -> bool:
    if role in ("system", "developer"):
        return cfg.mask_system_messages and not skip_system
    if role == "assistant":
        return cfg.mask_assistant_messages
    if role in ("tool", "function"):
        return cfg.mask_tool_messages
    return True


def _messages(msgs: Any, base: str, cfg: TurkishPIIConfig, skip_system: bool, commits: list[Callable[[], None]]) -> Iterator[TextRef]:
    if not isinstance(msgs, list):
        return
    for i, msg in enumerate(msgs):
        p = f"{base}[{i}]"
        if isinstance(msg, str):
            yield from json_or_text(msgs, i, p, "user", commits)
            continue
        role = _get(msg, "role")
        mtype = _get(msg, "type")
        if not _role_allowed(role, cfg, skip_system):
            continue
        if mtype in ("function_call", "custom_tool_call"):  # Responses API
            for fld in ("arguments", "input"):
                yield from json_or_text(msg, fld, f"{p}.{fld}", "assistant", commits)
            continue
        if mtype in ("function_call_output", "custom_tool_call_output", "computer_call_output"):
            out = _get(msg, "output")
            if isinstance(out, str):
                yield from json_or_text(msg, "output", f"{p}.output", "tool", commits)
            elif isinstance(out, list):
                yield from _content(msg, "output", f"{p}.output", "tool", commits)
            continue
        if mtype == "reasoning":
            summ = _get(msg, "summary")
            if isinstance(summ, list):
                for k, sm in enumerate(summ):
                    if isinstance(_get(sm, "text"), str):
                        yield _text(sm, "text", "text", "assistant", f"{p}.summary[{k}].text")
            continue
        if isinstance(mtype, str) and mtype.startswith("mcp_") and isinstance(msg, dict):
            yield from walk_leaves(msg, p, "tool", keys=False)
            continue
        yield from _content(msg, "content", f"{p}.content", role, commits)
        if isinstance(_get(msg, "name"), str) and role != "tool":
            yield _text(msg, "name", "name", role, f"{p}.name")
        if isinstance(_get(msg, "reasoning_content"), str):
            yield _text(msg, "reasoning_content", "text", role, f"{p}.reasoning_content")
        tcs = _get(msg, "tool_calls")
        if isinstance(tcs, list):
            for j, tc in enumerate(tcs):
                fn = _get(tc, "function")
                if fn is not None:
                    yield from json_or_text(fn, "arguments", f"{p}.tool_calls[{j}].function.arguments", role, commits, force_json=True)
        fc = _get(msg, "function_call")
        if fc is not None:
            yield from json_or_text(fc, "arguments", f"{p}.function_call.arguments", role, commits, force_json=True)


# alan adı → (rol) — desteklenmeyen çağrı türlerinde (rerank, görsel, ses...) genel maskeleme
GENERIC_REQUEST_FIELDS = ("prompt", "input", "query", "documents", "text", "contents", "instructions", "messages")


def iter_request_texts(
    data: dict[str, Any], call_type: str | None, cfg: TurkishPIIConfig, commits: list[Callable[[], None]] | None = None,
    skip_system: bool = False, generic: bool = False,
) -> Iterator[TextRef]:
    """Sıra deterministiktir: instructions/system → messages/input → prompt."""
    commits = commits if commits is not None else []
    if generic:
        for f in GENERIC_REQUEST_FIELDS:
            v = data.get(f)
            if isinstance(v, str):
                yield from json_or_text(data, f, f, "user", commits)
            elif isinstance(v, dict | list):
                yield from walk_leaves(v, f, "user", keys=False)
        return
    if isinstance(data.get("instructions"), str) and cfg.mask_system_messages and not skip_system:
        yield _text(data, "instructions", "text", "system", "instructions")
    if data.get("system") is not None and cfg.mask_system_messages and not skip_system:
        yield from _content(data, "system", "system", "system", commits)
    if "messages" in data:
        yield from _messages(data.get("messages"), "messages", cfg, skip_system, commits)
    is_embedding = call_type in ("embedding", "aembedding", "embeddings")
    inp = data.get("input")
    if inp is not None and (not is_embedding or cfg.mask_embeddings):
        if isinstance(inp, str):
            yield from json_or_text(data, "input", "input", "user", commits)
        elif isinstance(inp, list):
            if all(isinstance(x, str | int) or isinstance(x, list) and all(isinstance(y, int) for y in x) for x in inp):
                for i, x in enumerate(inp):
                    if isinstance(x, str):
                        yield from json_or_text(inp, i, f"input[{i}]", "user", commits)
            else:
                yield from _messages(inp, "input", cfg, skip_system, commits)
    if call_type and "generate_content" in call_type:
        yield from _gemini_request(data, cfg, skip_system, commits)
    prompt = data.get("prompt")
    if isinstance(prompt, str):
        yield from json_or_text(data, "prompt", "prompt", "user", commits)
    elif isinstance(prompt, list):
        for i, x in enumerate(prompt):
            if isinstance(x, str):
                yield from json_or_text(prompt, i, f"prompt[{i}]", "user", commits)
    elif isinstance(prompt, dict) and isinstance(prompt.get("variables"), dict):  # Responses API istem şablonu
        yield from walk_leaves(prompt["variables"], "prompt.variables", "user", keys=False)


# ---------------------------------------------------------------- Gemini generateContent
GEMINI_CALLS = frozenset({"generate_content", "agenerate_content", "generate_content_stream", "agenerate_content_stream"})


def _gemini_parts(content: Any, path: str, role: str | None, cfg: TurkishPIIConfig, commits: list[Callable[[], None]],
                  tools: bool = True, parse_json: bool = True) -> Iterator[TextRef]:
    """`{role, parts: [{text} | {functionCall: {args}} | {functionResponse: {response}} | {inlineData}...]}`"""
    if isinstance(content, str):
        return
    parts = _get(content, "parts")
    if isinstance(parts, tuple):  # google-genai SDK nesnesi: yerinde yazılabilsin
        parts = list(parts)
        _setter(content, "parts")(parts)  # type: ignore[arg-type]
    if not isinstance(parts, list):
        return
    for j, part in enumerate(parts):
        p = f"{path}.parts[{j}]"
        if isinstance(part, str):
            yield from json_or_text(parts, j, p, role, commits, parse_json=parse_json)
            continue
        if isinstance(_get(part, "text"), str):
            if _get(part, "thought") is True and _get(part, "thoughtSignature"):
                continue  # imzalı düşünce parçası
            yield from json_or_text(part, "text", f"{p}.text", role, commits, parse_json=parse_json)
            continue
        fc = _get(part, "functionCall") or _get(part, "function_call")
        if fc is not None and tools:
            args = _get(fc, "args")
            if isinstance(args, dict | list):
                yield from walk_leaves(args, f"{p}.functionCall.args", "assistant")
            continue
        fr = _get(part, "functionResponse") or _get(part, "function_response")
        if fr is not None and cfg.mask_tool_messages:
            resp = _get(fr, "response")
            if isinstance(resp, dict | list):
                yield from walk_leaves(resp, f"{p}.functionResponse.response", "tool")


def _gemini_request(data: dict[str, Any], cfg: TurkishPIIConfig, skip_system: bool,
                    commits: list[Callable[[], None]]) -> Iterator[TextRef]:
    """Sıra: systemInstruction (üst düzey, sonra config altında) → contents (sırayla)."""
    if cfg.mask_system_messages and not skip_system:
        for holder in (data, data.get("config")):
            if not isinstance(holder, dict):
                continue
            for key in ("systemInstruction", "system_instruction"):
                si = holder.get(key)
                if isinstance(si, str):
                    yield _text(holder, key, "text", "system", key)
                elif isinstance(si, dict):
                    yield from _gemini_parts(si, key, "system", cfg, commits)
                elif isinstance(si, list):
                    for k, item in enumerate(si):
                        if isinstance(item, str):
                            yield _text(si, k, "text", "system", f"{key}[{k}]")
                        else:
                            yield from _gemini_parts(item, f"{key}[{k}]", "system", cfg, commits)
    contents = data.get("contents")
    if isinstance(contents, dict):
        contents = [contents]
    if isinstance(contents, str):
        yield from json_or_text(data, "contents", "contents", "user", commits)
        return
    if not isinstance(contents, list):
        return
    for i, c in enumerate(contents):
        if isinstance(c, str):
            yield from json_or_text(contents, i, f"contents[{i}]", "user", commits)
            continue
        role = "assistant" if _get(c, "role") == "model" else "user"
        if not _role_allowed(role, cfg, skip_system):
            continue
        yield from _gemini_parts(c, f"contents[{i}]", role, cfg, commits)


# ---------------------------------------------------------------- yanıt
def iter_response_texts(resp: Any, cfg: TurkishPIIConfig, commits: list[Callable[[], None]] | None = None,
                        preserve: bool = False) -> Iterator[TextRef]:
    """`preserve=True` yalnız geri çevirmede: içerikteki JSON metin ayrıştırılmadan (biçim korunarak) verilir.
    Tarama/log maskeleme varsayılan (ayrıştırılmış) yolu kullanır: JSON anahtarı bağlam taşır ({"ad": "deniz"})."""
    commits = commits if commits is not None else []
    tools = cfg.tool_restore_policy == "all"
    pj = not (cfg.response_json_preserve_format and preserve)  # içerik JSON'u ayrıştırılsın mı?
    choices = _get(resp, "choices")
    if isinstance(choices, list):
        for ci, ch in enumerate(choices):
            msg = _get(ch, "message")
            if msg is None:
                if isinstance(_get(ch, "text"), str):  # text_completion
                    yield from json_or_text(ch, "text", f"choices[{ci}].text", "assistant", commits, parse_json=pj)
                continue
            p = f"choices[{ci}].message"
            yield from _content(msg, "content", f"{p}.content", "assistant", commits, parse_json=pj)
            if isinstance(_get(msg, "reasoning_content"), str):
                yield _text(msg, "reasoning_content", "text", "assistant", f"{p}.reasoning_content")
            if tools:
                tcs = _get(msg, "tool_calls")
                if isinstance(tcs, list):
                    for j, tc in enumerate(tcs):
                        fn = _get(tc, "function")
                        if fn is not None:
                            yield from json_or_text(fn, "arguments", f"{p}.tool_calls[{j}].function.arguments", "assistant", commits, force_json=True)
                fc = _get(msg, "function_call")
                if fc is not None:
                    yield from json_or_text(fc, "arguments", f"{p}.function_call.arguments", "assistant", commits, force_json=True)
        return
    candidates = _get(resp, "candidates")
    if isinstance(candidates, list):  # Gemini generateContent
        for ci, cand in enumerate(candidates):
            content = _get(cand, "content")
            if content is not None:
                yield from _gemini_parts(content, f"candidates[{ci}].content", "assistant", cfg, commits, tools=tools,
                                         parse_json=pj)
        return
    output = _get(resp, "output")
    if isinstance(output, list):  # Responses API
        for i, item in enumerate(output):
            itype = _get(item, "type")
            if itype == "message":
                yield from _content(item, "content", f"output[{i}].content", "assistant", commits, parse_json=pj)
            elif itype in ("function_call", "custom_tool_call") and tools:
                for fld in ("arguments", "input"):
                    yield from json_or_text(item, fld, f"output[{i}].{fld}", "assistant", commits)
            elif itype == "reasoning":
                summ = _get(item, "summary")
                if isinstance(summ, list):
                    for k, sm in enumerate(summ):
                        if isinstance(_get(sm, "text"), str):
                            yield _text(sm, "text", "text", "assistant", f"output[{i}].summary[{k}]")
        return
    content = _get(resp, "content")
    if isinstance(content, list):  # Anthropic messages (thinking blokları imzalı → dokunulmaz)
        for i, block in enumerate(content):
            btype = _get(block, "type")
            if btype == "text" and isinstance(_get(block, "text"), str):
                yield from json_or_text(block, "text", f"content[{i}].text", "assistant", commits, parse_json=pj)
            elif btype == "tool_use" and tools:
                inp = _get(block, "input")
                if isinstance(inp, dict | list):
                    yield from walk_leaves(inp, f"content[{i}].input", "assistant")
