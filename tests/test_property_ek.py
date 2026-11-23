"""Ek özellik (hypothesis) testleri: Türkçe ad biçimleri, SSE bayt bölmeleri, yer tutucu biçimleri, ek sabit noktası,
JSON gövde bütünlüğü. Tüm değerler sentetiktir."""

from __future__ import annotations

import copy
import json
from typing import Any

from conftest import cfg_for, engine_for
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from matriks_pii.recognizers.checksums import make_tckn
from matriks_pii.revert import Reverter, StreamingReverter
from matriks_pii.session import MaskSession
from matriks_pii.streaming import StreamProcessor
from matriks_pii.text_utils import tr_lower, tr_upper
from matriks_pii.tr_morphology import generate, parse_suffix, repair_suffix
from matriks_pii.traverse import iter_request_texts

FIRSTS = ["Ahmet", "Ayşe", "Mehmet", "Fatma", "Mustafa", "Zeynep", "Emre", "Elif", "Hüseyin", "Şükrü", "İbrahim", "Gökhan"]
LASTS = ["Yılmaz", "Demir", "Kaya", "Şahin", "Çelik", "Öztürk", "Aydın", "Arslan", "Doğan", "Kılıç", "Koç", "Kurt"]
SUFFIXES = ["", "'in", "'ın", "'e", "'a", "'de", "'den", "'le", "'yle", "'ye", "'ya", "'i"]
TR_ALPHA = "abcçdefgğhıijklmnoöprsştuüvyzABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ .,;:!?\n"
SETTINGS = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _style(name: str, mode: int) -> str:
    first, last = name.split(" ")
    if mode == 0:
        return f"{first} {last}"
    if mode == 1:
        return f"{first} {tr_upper(last)}"
    return f"{tr_upper(first)} {tr_upper(last)}"


@SETTINGS
@given(st.sampled_from(FIRSTS), st.sampled_from(LASTS), st.integers(0, 2), st.sampled_from(SUFFIXES),
       st.sampled_from(["Müşteri {} aradı.", "Sayın {}, başvurunuz alındı.", "Dün {} ile görüştük.", "İmza: {}"]))
def test_name_styles_detected_and_roundtrip(first: str, last: str, mode: int, sfx: str, tpl: str) -> None:
    name = _style(f"{first} {last}", mode)
    text = tpl.format(name + sfx)
    eng = engine_for()
    spans = [s for s in eng.detected(text) if s.entity == "KISI"]
    assert any(s.text == name for s in spans), (text, [(s.text, s.score) for s in spans])
    cfg = cfg_for({"suffix_repair": False})
    s = MaskSession(cfg)
    masked = eng.mask(text, eng.actionable(eng.analyze(text))[0], s)
    assert name not in masked
    assert Reverter(s.map, s.entities, cfg).revert(masked) == text


@SETTINGS
@given(st.text(alphabet=TR_ALPHA, max_size=120), st.lists(st.integers(1_000_000_00, 9_999_999_99), min_size=1, max_size=3))
def test_random_turkish_text_with_tckn_roundtrip(filler: str, seeds: list[int]) -> None:
    values = [make_tckn(str(x)[:9]) for x in seeds]
    text = filler + " TCKN " + " ve TCKN ".join(values) + "."
    eng = engine_for()
    cfg = cfg_for({"suffix_repair": False})
    s = MaskSession(cfg)
    masked = eng.mask(text, eng.actionable(eng.analyze(text))[0], s)
    assert all(v not in masked for v in values)
    assert Reverter(s.map, s.entities, cfg).revert(masked) == text


def _sse(text: str) -> bytes:
    ev = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    return (f"event: content_block_delta\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n').encode()


@SETTINGS
@given(st.lists(st.integers(1, 9), min_size=1, max_size=400),
       st.sampled_from(["Şükrü <KISI_1>'e iletti", "İş <TCKN_1> ğüş <KISI_1>", "<KISI_1><TCKN_1>ç"]))
def test_sse_random_byte_splits(sizes: list[int], text: str) -> None:
    mp = {"<KISI_1>": "Ayşe Demir", "<TCKN_1>": "17291716060"}
    cfg = cfg_for()
    raw = _sse(text)
    expected = Reverter(mp, {}, cfg).revert(text, final=True)
    proc = StreamProcessor(Reverter(mp, {}, cfg), 48)
    outs: list[Any] = []
    pos, k = 0, 0
    while pos < len(raw):
        n = sizes[k % len(sizes)]
        outs += proc.process(raw[pos : pos + n])
        pos += n
        k += 1
    outs += proc.final_items()
    body = b"".join(o for o in outs if isinstance(o, bytes)).decode("utf-8")
    got = "".join(json.loads(ln[5:])["delta"].get("text", "") for ln in body.split("\n")
                  if ln.startswith("data:") and "text_delta" in ln)
    assert got == expected


@SETTINGS
@given(st.sampled_from(["<{label}_{n}>", "[{label}_{n}]", "__{label}_{n}__", "PII_{label}_{n}", "<{label}-{n}>", "<<{label}_{n}>>"]),
       st.sampled_from([{}, {"KISI": "AD"}, {"KISI": "MUSTERI", "TCKN": "KIMLIK"}]),
       st.lists(st.integers(1, 7), min_size=1, max_size=50))
def test_placeholder_formats_scanner_and_stream(fmt: str, labels: dict[str, str], splits: list[int]) -> None:
    cfg = cfg_for({"placeholder_format": fmt, "labels": labels})
    eng = engine_for({"placeholder_format": fmt, "labels": labels, "suffix_repair": False})
    text = "Ben Ayşe Demir, TCKN 17291716060; Ayşe Demir tekrar."
    s = MaskSession(eng.cfg)
    masked = eng.mask(text, eng.actionable(eng.analyze(text))[0], s)
    rev = Reverter(s.map, s.entities, eng.cfg)
    assert rev.revert(masked) == text
    sr = StreamingReverter(Reverter(s.map, s.entities, eng.cfg), cfg.streaming.holdback_max_chars)
    out, pos, k = "", 0, 0
    while pos < len(masked):
        n = splits[k % len(splits)]
        out += sr.feed(masked[pos : pos + n])
        pos += n
        k += 1
    assert out + sr.flush() == text


NAMES_FOR_FP = ["Ahmet", "Ayşe", "Kemal", "Celal", "Ufuk", "Öztürk", "Gül", "Ali", "Umut", "Deniz", "Şükrü", "Hüseyin",
                "Yılmaz", "Çelik", "Burak", "Tuba", "AHMET", "Mustafa Kemal", "No: 6", "100", "17291716060", "1000", "30"]


@settings(max_examples=500, deadline=None)
@given(st.sampled_from(NAMES_FOR_FP),
       st.sampled_from(["GEN", "DAT", "ACC", "LOC", "ABL", "INS", "PLU", "COP", "P3S", "PAST", "EVID", "EQU"]))
def test_repair_suffix_fixed_point(word: str, cls: str) -> None:
    from matriks_pii.tr_morphology import _digit_stem

    stem = word if word[-1].isalpha() else _digit_stem(word)
    assert stem
    sfx = generate(cls, stem)
    if not parse_suffix(sfx):
        return
    assert tr_lower(repair_suffix(word, sfx)) == tr_lower(sfx)


_keys = st.sampled_from(["ad", "soyad", "tc", "not", "tutar", "adres", "musteri_no", "x", "Ayşe Demir", "17291716060"])
_leaves = st.one_of(
    st.sampled_from(["Ayşe Demir", "17291716060", "THYAO", "merhaba", "0532 234 56 78", ""]),
    st.integers(0, 10**12), st.booleans(), st.none(), st.floats(allow_nan=False, allow_infinity=False),
)
_json = st.recursive(_leaves, lambda ch: st.lists(ch, max_size=4) | st.dictionaries(_keys, ch, max_size=4), max_leaves=15)


@SETTINGS
@given(_json)
def test_random_json_tool_args_stay_valid(obj: Any) -> None:
    raw = json.dumps(obj, ensure_ascii=False)
    data = {"messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "f", "arguments": raw}}]}]}
    before = copy.deepcopy(data)
    eng = engine_for()
    s = MaskSession(eng.cfg)
    commits: list[Any] = []
    for ref in list(iter_request_texts(data, "acompletion", eng.cfg, commits)):
        t = ref.get()
        if isinstance(t, str) and t:
            to_mask = eng.actionable(eng.analyze(t))[0]
            if to_mask:
                ref.set(eng.mask(t, to_mask, s))
    for c in commits:
        c()
    out = json.loads(data["messages"][0]["tool_calls"][0]["function"]["arguments"])  # her zaman geçerli JSON
    if not s.map:
        assert data == before  # değişiklik yoksa baytlar aynen
    dumped = json.dumps(out, ensure_ascii=False)
    for v in s.map.values():
        assert v not in dumped  # maskelenen değer argümanlarda kalmaz (anahtar, sayı yaprağı dâhil)
