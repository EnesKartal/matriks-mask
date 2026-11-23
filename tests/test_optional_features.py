"""Opsiyonel özellikler: HF NER adaptörü, yanıt taraması (scan_response), Redis deposu, Anthropic SSE."""

from __future__ import annotations

import importlib.util
import json
from typing import Any

import pytest
from conftest import cfg_for
from helpers import model_response
from test_hooks import T1, G, chat, pre

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.recognizers.base import AnalysisContext
from matriks_pii.recognizers.ner_hf import HFNerRecognizer


# ---------------------------------------------------------------- HF NER adaptörü (sahte pipeline ile)
class _FakePipe:
    def __init__(self, ents: list[dict[str, Any]]) -> None:
        self.ents = ents

    def __call__(self, text: str) -> list[dict[str, Any]]:
        return self.ents


def _ner_engine(ents: list[dict[str, Any]], **cfg: Any) -> PIIEngine:
    eng = PIIEngine(TurkishPIIConfig.build({"name_detection": {"ner_backend": "hf"}, **cfg}))
    for r in eng.recognizers:
        if isinstance(r, HFNerRecognizer):
            r._pipe = _FakePipe(ents)
    return eng


def test_ner_maps_per_and_strips_suffix() -> None:
    text = "John Smith'in hesabı açıldı, Ankara şubesi."
    ents = [{"entity_group": "PER", "score": 0.97, "start": 0, "end": 13},
            {"entity_group": "LOC", "score": 0.99, "start": 29, "end": 35}]
    eng = _ner_engine(ents)
    got = [(s.entity, s.text) for s in eng.detected(text)]
    assert got == [("KISI", "John Smith")]  # LOC maskelenmez; apostroflu ek span dışında


def test_ner_min_score_and_label_map() -> None:
    text = "Müşteri Zeynep geldi"
    eng = _ner_engine([{"entity_group": "KISI_AD_SOYAD", "score": 0.6, "start": 8, "end": 14}],
                      name_detection={"ner_backend": "hf", "ner_label_map": {"KISI_AD_SOYAD": "KISI"}, "ner_min_score": 0.85})
    assert [s.recognizer for s in eng.analyze(text) if s.entity == "KISI"] == ["person"]  # NER skoru eşik altında
    eng2 = _ner_engine([{"entity_group": "KISI_AD_SOYAD", "score": 0.95, "start": 8, "end": 14}],
                       name_detection={"ner_backend": "hf", "ner_label_map": {"KISI_AD_SOYAD": "KISI"}})
    assert [s.text for s in eng2.detected(text)] == ["Zeynep"]


def test_ner_overlap_with_lexicon_keeps_longer() -> None:
    text = "Dün Ahmet Yılmaz Kaya geldi"
    eng = _ner_engine([{"entity_group": "PER", "score": 0.99, "start": 4, "end": 21}])
    assert [s.text for s in eng.detected(text)] == ["Ahmet Yılmaz Kaya"]


def test_ner_subword_fragments_merged_to_words() -> None:
    # gerçek modelin çıktısı: "Jer" + "##om" + "##e Powell" ayrı gruplar olarak gelir
    text = "Jerome Powell konuştu."
    eng = _ner_engine([{"entity_group": "PER", "score": 0.99, "start": 0, "end": 3},
                       {"entity_group": "PER", "score": 0.99, "start": 3, "end": 5},
                       {"entity_group": "PER", "score": 0.99, "start": 5, "end": 13}])
    assert [s.text for s in eng.detected(text)] == ["Jerome Powell"]


@pytest.mark.parametrize(("text", "start", "end"), [
    ("Kaya gibi sağlam bilanço yapısı dikkat çekti.", 0, 4),   # cümle başında sık sözcük olan tek ad
    ("Atatürk 1881'de Selanik'te doğdu.", 0, 7),              # tarihî kişi (kurum/tarihî ad listesi)
    ("JSON: {'status': 'ok'}", 0, 4),                         # kısaltma
])
def test_ner_lexicon_false_positive_guards(text: str, start: int, end: int) -> None:
    eng = _ner_engine([{"entity_group": "PER", "score": 0.99, "start": start, "end": end}])
    assert [s for s in eng.detected(text) if s.entity == "KISI"] == []


def test_ner_missing_dependency_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *a: Any, **k: Any) -> Any:
        if name == "transformers":
            raise ImportError("yok")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = HFNerRecognizer(cfg_for({"name_detection": {"ner_backend": "hf"}}))
    with pytest.raises(RuntimeError, match=r"matriks-mask\[ner\]"):
        r.find("Ahmet", AnalysisContext.build(cfg_for(), "Ahmet"))


@pytest.mark.ner
@pytest.mark.skipif(importlib.util.find_spec("transformers") is None, reason="transformers kurulu değil ([ner] extra)")
def test_ner_real_model() -> None:  # pragma: no cover - ağ ve model indirme gerektirir
    eng = PIIEngine(TurkishPIIConfig.build({"name_detection": {"ner_backend": "hf"}}))
    assert any(s.entity == "KISI" for s in eng.detected("Dün John Smith ile görüştüm."))


# ---------------------------------------------------------------- scan_response
async def test_scan_response_masks_new_pii_only() -> None:
    g = G(scan_response=True)
    d = chat(f"Ben Ayşe Demir, TCKN {T1}")
    await pre(g, d)
    llm = "Merhaba <KISI_1>. Danışmanınız Mehmet Öztürk, tel 0532 345 67 89. Kimliğiniz <TCKN_1>."
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=model_response(llm))
    assert out.choices[0].message.content == f"Merhaba Ayşe Demir. Danışmanınız <KISI_2>, tel <TELEFON_1>. Kimliğiniz {T1}."


async def test_scan_response_off_by_default_and_on_in_strict() -> None:
    assert not cfg_for().scan_response and cfg_for({"profile": "strict"}).scan_response


async def test_scan_response_tool_args() -> None:
    g = G(scan_response=True)
    d = chat("merhaba")
    await pre(g, d)
    out = await g.async_post_call_success_hook(
        data=d, user_api_key_dict=None,
        response=model_response(None, tool_args=[json.dumps({"tckn": "44771278268", "not": "tamam"})]))
    # istekte PII olmasa da yanıt taranır; LLM'in ürettiği TCKN maskelenir, geri çevrilmez
    assert json.loads(out.choices[0].message.tool_calls[0].function.arguments) == {"tckn": "<TCKN_1>", "not": "tamam"}
