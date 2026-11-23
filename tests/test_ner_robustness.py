"""NER (hf) üretim dayanıklılığı: cümle bazlı parçalama, ofset kaydırma, zaman aşımı, hata modu, olay döngüsü."""

from __future__ import annotations

import importlib.util
import time
from typing import Any

import pytest
from conftest import cfg_for
from test_hooks import G, chat, pre

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.recognizers.base import AnalysisContext
from matriks_pii.recognizers.ner_hf import HFNerRecognizer, _chunks


class RecordingPipe:
    """Her çağrıyı kaydeder; parçadaki "Zühtü Kurgusal" geçişlerini PER olarak döner (sahte model)."""

    def __init__(self, sleep: float = 0.0, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.sleep = sleep
        self.fail = fail

    def __call__(self, text: str) -> list[dict[str, Any]]:
        self.calls.append(text)
        if self.sleep:
            time.sleep(self.sleep)
        if self.fail:
            raise RuntimeError("model hatası: girdi metni burada olabilir")
        out = []
        i = text.find("Zühtü Kurgusal")
        while i >= 0:
            out.append({"entity_group": "PER", "score": 0.97, "start": i, "end": i + 14})
            i = text.find("Zühtü Kurgusal", i + 1)
        return out


def _rec(pipe: RecordingPipe, **nd: Any) -> tuple[HFNerRecognizer, Any]:
    cfg = cfg_for({"name_detection": {"ner_backend": "hf", "ner_preload": False, **nd}})
    r = HFNerRecognizer(cfg)
    r._pipe = pipe
    return r, cfg


def test_chunking_by_sentences() -> None:
    text = " ".join(f"Bu {i}. cümle biraz uzun bir açıklama içeriyor." for i in range(120))
    ctx = AnalysisContext.build(cfg_for(), text)
    parts = _chunks(text, ctx.sentences, 1200)
    assert len(parts) >= 4 and all(len(c) <= 1200 for _, c in parts)
    assert "".join(c for _, c in parts) == text  # kayıpsız, sıralı
    assert all(text[s : s + len(c)] == c for s, c in parts)


def test_chunking_hard_split_no_whitespace() -> None:
    text = "x" * 3000
    parts = _chunks(text, [(0, 3000)], 1200)
    assert [len(c) for _, c in parts] == [1200, 1200, 600]


def test_offsets_shifted_correctly() -> None:
    pipe = RecordingPipe()
    r, cfg = _rec(pipe, ner_max_chars=300)
    filler = "Bugün hava çok güzeldi ve toplantı uzun sürdü. " * 20
    text = filler + "Sonra Zühtü Kurgusal geldi."
    spans = r.find(text, AnalysisContext.build(cfg, text))
    assert len(pipe.calls) >= 3
    assert [(s.text, s.start) for s in spans] == [("Zühtü Kurgusal", text.index("Zühtü Kurgusal"))]


def test_timeout_closed_raises() -> None:
    r, cfg = _rec(RecordingPipe(sleep=1.0), ner_timeout_seconds=0.1)
    with pytest.raises(RuntimeError, match="NER başarısız"):
        r.find("Zühtü Kurgusal geldi.", AnalysisContext.build(cfg, "Zühtü Kurgusal geldi."))


def test_timeout_lexicon_returns_empty_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    r, cfg = _rec(RecordingPipe(sleep=1.0), ner_timeout_seconds=0.1, ner_fail_mode="lexicon")
    assert r.find("Zühtü Kurgusal geldi.", AnalysisContext.build(cfg, "Zühtü Kurgusal geldi.")) == []
    assert any("NER başarısız" in rec.getMessage() for rec in caplog.records)


def test_exception_in_pipeline_closed_value_free() -> None:
    r, cfg = _rec(RecordingPipe(fail=True))
    with pytest.raises(RuntimeError) as ei:
        r.find("Zühtü Kurgusal geldi.", AnalysisContext.build(cfg, "Zühtü Kurgusal geldi."))
    assert "girdi metni" not in str(ei.value) and "Zühtü" not in str(ei.value)


def test_engine_lexicon_mode_keeps_dictionary_results() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"name_detection": {"ner_backend": "hf", "ner_preload": False,
                                                               "ner_fail_mode": "lexicon", "ner_timeout_seconds": 0.1}}))
    for r in eng.recognizers:
        if isinstance(r, HFNerRecognizer):
            r._pipe = RecordingPipe(fail=True)
    assert [(s.entity, s.text) for s in eng.detected("Ayşe Demir aradı, TCKN 17291716060")] == [
        ("KISI", "Ayşe Demir"), ("TCKN", "17291716060")]


async def test_ner_forces_executor_path() -> None:
    import threading

    g = G(name_detection={"ner_backend": "hf", "ner_preload": False})
    for r in g.engine.recognizers:
        if isinstance(r, HFNerRecognizer):
            r._pipe = RecordingPipe()
    names: list[str] = []
    orig = g._analyze_refs

    def spy(refs: Any, texts: Any) -> Any:
        names.append(threading.current_thread().name)
        return orig(refs, texts)

    g._analyze_refs = spy  # type: ignore[method-assign]
    out = await pre(g, chat("Zühtü Kurgusal kısa metin"))
    assert names and names[0].startswith("matriks-pii")  # kısa metin bile olay döngüsünde değil
    assert out["messages"][0]["content"] == "<KISI_1> kısa metin"


def test_ner_preload_loads_at_init(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_pipeline(self: HFNerRecognizer) -> Any:
        calls.append(1)
        self._pipe = RecordingPipe()
        return self._pipe

    monkeypatch.setattr(HFNerRecognizer, "_pipeline", fake_pipeline)
    G(name_detection={"ner_backend": "hf"})
    assert calls == [1]
    calls.clear()
    G(name_detection={"ner_backend": "hf", "ner_preload": False})
    assert calls == []


def test_ner_preload_failure_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: HFNerRecognizer) -> Any:
        raise RuntimeError("ner_backend=hf için 'pip install matriks-mask[ner]' gerekli")

    monkeypatch.setattr(HFNerRecognizer, "_pipeline", broken)
    with pytest.raises(RuntimeError, match="ner"):
        G(name_detection={"ner_backend": "hf"})


@pytest.mark.ner
@pytest.mark.skipif(importlib.util.find_spec("transformers") is None, reason="transformers yok")
def test_ner_real_model_long_text() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"name_detection": {"ner_backend": "hf"}}))
    text = "Bugün piyasalar sakin seyretti ve endeks yatay kapandı. " * 75 + "Toplantıya Jerome Powell katıldı."
    assert len(text) > 4000
    spans = eng.detected(text)
    assert any(s.entity == "KISI" and "Powell" in s.text for s in spans)
