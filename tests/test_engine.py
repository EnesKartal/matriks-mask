"""Motor, oturum, config ve morfoloji birim testleri."""

from __future__ import annotations

import pytest
from conftest import cfg_for, engine_for

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import resolve_overlaps
from matriks_pii.recognizers.base import Span
from matriks_pii.session import MaskSession
from matriks_pii.text_utils import fold_text, is_sentence_start, tr_lower, tr_upper
from matriks_pii.tr_morphology import repair_suffix, strip_suffixes


def S(s: int, e: int, ent: str, score: float = 0.9) -> Span:
    return Span(s, e, ent, "x" * (e - s), score, "t", "x")


def test_resolve_overlaps_priority() -> None:
    got = resolve_overlaps([S(0, 26, "IBAN"), S(5, 16, "TCKN"), S(30, 40, "KISI"), S(35, 45, "ADRES")])
    assert [(s.entity, s.start) for s in got] == [("IBAN", 0), ("ADRES", 35)]


def test_tr_case() -> None:
    assert tr_lower("İSTANBUL IĞDIR") == "istanbul ığdır"
    assert tr_upper("istanbul ığdır") == "İSTANBUL IĞDIR"
    assert len(fold_text("İİİ")) == 3 and fold_text("İMEİ IMEI") == "imei imei"


def test_sentence_start() -> None:
    t = "Merhaba. Ahmet geldi. Dr. Ayşe de."
    assert is_sentence_start(t, t.index("Ahmet"))
    assert not is_sentence_start(t, t.index("Ayşe"))


@pytest.mark.parametrize(
    "word,sfx,exp",
    [("Ayşe", "ye", "ye"), ("Ahmet", "ye", "e"), ("Mehmet", "ya", "e"), ("Ali", "e", "ye"), ("Kadıköy", "de", "de"),
     ("Ahmet", "de", "te"), ("Zeynep", "da", "te"), ("Umut", "un", "un"), ("Ali", "nin", "nin"), ("Ayşe", "le", "yle"),
     ("Ayşe", "in", "nin"), ("Mehmet", "dan", "ten"), ("AYŞE", "E", "YE"), ("Ahmet", "daki", "teki"), ("Ufuk", "ya", "a"),
     ("17291716060", "in", "ın"), ("Ali", "xyz", "xyz")],
)
def test_repair_suffix(word: str, sfx: str, exp: str) -> None:
    assert repair_suffix(word, sfx) == exp


def test_strip_suffixes() -> None:
    assert "Ahmet" in strip_suffixes("Ahmetin")
    assert "Ayşe" in strip_suffixes("Ayşeye")
    assert "Mehmet" in strip_suffixes("Mehmetlerden")


def test_session_numbering_and_restore_flags() -> None:
    cfg = cfg_for()
    s = MaskSession(cfg)
    a = s.placeholder_for(Span(0, 4, "KISI", "Ayşe", 0.9, "t", "ayse"))
    b = s.placeholder_for(Span(0, 4, "KISI", "AYŞE", 0.9, "t", "ayse"))
    c = s.placeholder_for(Span(0, 16, "KART", "4111111111111111", 0.9, "t", "4111111111111111"))
    assert a == b == "<KISI_1>" and s.map["<KISI_1>"] == "Ayşe"
    assert c == "<KART_1>" and s.map[c] == "**** **** **** 1111"
    assert "4111111111111111" not in repr(s)


def test_session_serialization_roundtrip() -> None:
    cfg = cfg_for()
    s = MaskSession(cfg)
    s.placeholder_for(Span(0, 4, "KISI", "Ayşe", 0.9, "t", "ayse"))
    s2 = MaskSession.from_dict(cfg, s.to_dict())
    assert s2.map == s.map and s2.by_key == s.by_key


def test_profiles() -> None:
    strict = TurkishPIIConfig.build({"profile": "strict"})
    assert strict.action("OZEL_DIN") == "MASK" and strict.action("KRIPTO_CUZDAN") == "MASK"
    minimal = TurkishPIIConfig.build({"profile": "minimal"})
    assert minimal.action("PLAKA") == "IGNORE" and minimal.action("OZEL_SAGLIK") == "LOG"
    over = TurkishPIIConfig.build({"profile": "strict", "entities": {"ozel_din": "log", "kisi": {"action": "ignore"}}})
    assert over.action("OZEL_DIN") == "LOG" and over.action("KISI") == "IGNORE"


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        TurkishPIIConfig.build({"placeholder_format": "<{label}{n}>"})
    with pytest.raises(ValueError):
        TurkishPIIConfig.build({"placeholder_id": "hmac"})
    with pytest.raises(ValueError):
        TurkishPIIConfig.build({"bilinmeyen": 1})
    cfg, rest = TurkishPIIConfig.from_kwargs({"profile": "strict", "fail_on_error": False, "api_key": "x"})
    assert cfg.fail_mode == "open" and rest == {"fail_on_error": False, "api_key": "x"}


def test_extra_regex_entity_label() -> None:
    eng = engine_for({"extra_regex": [{"entity": "mkk_sicil", "pattern": "MK-[0-9]{6}"}]})
    assert [s.entity for s in eng.detected("MK-123456")] == ["MKK_SICIL"]


def test_analysis_cache_hit() -> None:
    eng = engine_for()
    t = "TCKN 17291716060 önbellek testi"
    a = eng.analyze(t)
    assert eng.analyze(t) is a


def test_max_text_chars() -> None:
    eng = engine_for({"max_text_chars": 1024})
    with pytest.raises(ValueError):
        eng.analyze("x" * 1025)


def test_ner_backend_lazy_import_does_not_break_default() -> None:
    eng = engine_for()
    assert all(r.name != "ner_hf" for r in eng.recognizers)
