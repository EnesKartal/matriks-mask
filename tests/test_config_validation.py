"""Yapılandırma doğrulama: sınırlar, değersiz hata iletileri, bilinmeyen varlık, sır uyarıları, birleştirme anlamı."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine

B = TurkishPIIConfig.build


@pytest.mark.parametrize(
    "override",
    [
        {"session_store": {"ttl_seconds": -1}},
        {"session_store": {"ttl_seconds": 59}},
        {"session_store": {"max_sessions": 0}},
        {"session_store": {"redis_timeout_seconds": 0}},
        {"session_store": {"redis_timeout_seconds": 31}},
        {"streaming": {"holdback_max_chars": 0}},
        {"streaming": {"holdback_max_chars": 513}},
        {"max_text_chars": 0},
        {"max_text_chars": 1023},
        {"max_request_chars": 10},
        {"max_text_chars": 5000, "max_request_chars": 4000},
        {"context_window": 0},
        {"context_window": 501},
        {"executor_threshold_chars": -1},
        {"analysis_threads": 0},
        {"analysis_threads": 65},
        {"analysis_cache": {"max_entries": -5}},
        {"analysis_cache": {"ttl_seconds": -1}},
        {"name_detection": {"ner_min_score": 1.5}},
        {"entities": {"TCKN": {"min_score": -0.1}}},
        {"min_scores": {"KISI": 2}},
        {"extra_regex": [{"entity": "X_NO", "pattern": "X[0-9]+", "score": 1.2}]},
        {"profile": "x"},
        {"placeholder_id": "y"},
        {"fail_mode": "maybe"},
    ],
)
def test_bounds_and_literals_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="yapılandırma hatası"):
        B(override)


@pytest.mark.parametrize(
    "override",
    [
        {"session_store": {"ttl_seconds": 60, "max_sessions": 1}},
        {"streaming": {"holdback_max_chars": 48}},
        {"max_text_chars": 1024, "max_request_chars": 1024},
        {"analysis_cache": {"max_entries": 0, "ttl_seconds": 0}},
        {"context_window": 500, "analysis_threads": 64},
    ],
)
def test_bounds_edges_accepted(override: dict[str, Any]) -> None:
    B(override)


def test_unknown_entity_rejected() -> None:
    with pytest.raises(ValueError, match="bilinmeyen varlık: TCKNN"):
        B({"entities": {"TCKNN": "IGNORE"}})


def test_unknown_entity_via_special_categories_alias_rejected() -> None:
    with pytest.raises(ValueError, match="bilinmeyen varlık"):
        B({"special_categories": {"OZEL_SAGLK": "MASK"}})


def test_extra_regex_entity_is_known() -> None:
    cfg = B({"extra_regex": [{"entity": "KURUM_LISANS", "pattern": "LIS-[0-9]{8}"}], "entities": {"KURUM_LISANS": "BLOCK"}})
    assert cfg.action("KURUM_LISANS") == "BLOCK"


@pytest.mark.parametrize(
    "override",
    [
        {"hash_secret": 123456789, "placeholder_id": "hmac"},
        {"session_secret": 123456789},
        {"session_secret_previous": [123456789]},
        {"session_store": {"encryption_key": 123456789}},
        {"session_store": {"encryption_key_previous": 123456789}},
        {"session_store": {"redis_url": 123456789}},
    ],
)
def test_wrong_type_secret_error_is_value_free(override: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as ei:
        B(override)
    assert "123456789" not in str(ei.value)
    assert "metin olmalı" in str(ei.value)


def test_short_secret_error_is_value_free() -> None:
    with pytest.raises(ValueError) as ei:
        B({"session_secret": "GIZLISIRGIZLISIR"})
    assert "GIZLISIR" not in str(ei.value)


def test_bad_regex_is_valueerror() -> None:
    with pytest.raises(ValueError, match="pattern geçersiz"):
        B({"extra_regex": [{"entity": "X_NO", "pattern": "([0-9]"}]})


def test_extra_regex_entity_must_be_upper_ascii() -> None:
    with pytest.raises(ValueError):
        B({"extra_regex": [{"entity": "x no", "pattern": "x"}]})


def test_invalid_label_rejected() -> None:
    with pytest.raises(ValueError, match="etiket"):
        B({"labels": {"KISI": "ad soyad"}})


def test_holdback_vs_placeholder_length() -> None:
    with pytest.raises(ValueError, match="holdback_max_chars"):
        B({"labels": {"KISI": "COKUZUNBIRETIKETADIKIMLIKBILGISI"}, "streaming": {"holdback_max_chars": 30}})
    B({"labels": {"KISI": "COKUZUNBIRETIKETADIKIMLIKBILGISI"}, "streaming": {"holdback_max_chars": 64}})


def test_secret_literal_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="matriks_pii"):
        TurkishPIIConfig.from_kwargs({"session_secret": "x" * 40})
    assert any("session_secret düz metin" in r.getMessage() for r in caplog.records)
    assert all("x" * 40 not in r.getMessage() for r in caplog.records)


def test_secret_literal_strict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIKS_PII_STRICT_SECRETS", "1")
    with pytest.raises(ValueError, match="düz metin"):
        TurkishPIIConfig.from_kwargs({"hash_secret": "y" * 40})


def test_secret_env_ref_no_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("X_SECRET", "z" * 40)
    with caplog.at_level(logging.WARNING, logger="matriks_pii"):
        cfg, _ = TurkishPIIConfig.from_kwargs({"session_secret": "os.environ/X_SECRET"})
    assert cfg.session_secret == "z" * 40
    assert not [r for r in caplog.records if "düz metin" in r.getMessage()]


def test_redis_url_without_password_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="matriks_pii"):
        TurkishPIIConfig.from_kwargs({"session_store": {"redis_url": "redis://redis:6379/0"}})
        TurkishPIIConfig.from_kwargs({"session_store": {"redis_url": "redis://:parola@redis:6379/0"}})
    msgs = [r.getMessage() for r in caplog.records if "düz metin" in r.getMessage()]
    assert len(msgs) == 1 and "redis_url" in msgs[0] and "parola" not in msgs[0]


def test_ignore_unknown_keys_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValueError):
        B({"gelecek_surum_anahtari": 1, "session_store": {"yeni_alan": 2}})
    monkeypatch.setenv("MATRIKS_PII_IGNORE_UNKNOWN_KEYS", "1")
    with caplog.at_level(logging.WARNING, logger="matriks_pii"):
        cfg = B({"gelecek_surum_anahtari": 1, "session_store": {"yeni_alan": 2, "ttl_seconds": 120}})
    assert cfg.session_store.ttl_seconds == 120
    assert sum("yok sayıldı" in r.getMessage() for r in caplog.records) == 2


def test_profile_nested_merge() -> None:
    cfg = B({"profile": "strict", "phone": {"mask_444": False}})
    assert cfg.phone.mask_444 is False
    assert cfg.scan_response is True and cfg.checksum_policy == "context"


def test_extra_regex_with_profile() -> None:
    cfg = B({"profile": "minimal", "extra_regex": [{"entity": "MKK_X", "pattern": "MKK-[0-9]{6}"}]})
    eng = PIIEngine(cfg)
    assert [(s.entity, s.text) for s in eng.detected("kayıt MKK-123456")] == [("MKK_X", "MKK-123456")]


def test_special_categories_alias() -> None:
    cfg = B({"special_categories": {"ozel_din": "mask"}})
    assert cfg.action("OZEL_DIN") == "MASK"


def test_checksum_policy_context_card() -> None:
    eng = PIIEngine(B({"checksum_policy": "context"}))
    got = [(s.entity, s.text, s.score) for s in eng.detected("kart 4111 1111 1111 1112")]
    assert got == [("KART", "4111 1111 1111 1112", 0.75)]
    assert PIIEngine(B({})).detected("kart 4111 1111 1111 1112") == []


def test_version_hash_excludes_all_secrets() -> None:
    a = B({"hash_secret": "a" * 40, "placeholder_id": "hmac", "session_secret": "b" * 40})
    b = B({"hash_secret": "c" * 40, "placeholder_id": "hmac", "session_secret": "d" * 40})
    assert a.version_hash == b.version_hash


def test_defaults_tightened() -> None:
    cfg = B({})
    assert cfg.session_store.max_sessions == 10_000
    assert cfg.analysis_cache.ttl_seconds == 300


async def test_labels_hmac_bracket_roundtrip() -> None:
    """Özel etiket + hmac kimlik + köşeli parantez biçimi: maskele → yanıtta geri çevir (ekli biçim dâhil)."""
    import re

    from helpers import model_response
    from test_hooks import G, chat, pre

    g = G(labels={"KISI": "AD", "TCKN": "KIMLIK"}, placeholder_id="hmac", placeholder_format="[{label}_{n}]",
          hash_secret="h" * 40, session_secret="s" * 40)
    d = chat("Ben Ayşe Demir, TCKN 17291716060")
    await pre(g, d)
    masked = d["messages"][0]["content"]
    m_ad = re.search(r"\[AD_[a-z2-7]{6,12}\]", masked)
    m_id = re.search(r"\[KIMLIK_[a-z2-7]{6,12}\]", masked)
    assert m_ad and m_id and "Ayşe" not in masked and "17291716060" not in masked
    resp = model_response(f"Merhaba {m_ad.group()}'e, {m_id.group()} doğrulandı.")
    out = await g.async_post_call_success_hook(data=d, user_api_key_dict=None, response=resp)
    assert out.choices[0].message.content == "Merhaba Ayşe Demir'e, 17291716060 doğrulandı."


def test_stream_placeholder_longer_than_holdback_rejected_by_config() -> None:
    # en uzun varsayılan yer tutucu (<GIZLI_ANAHTAR_999999999999>) + 8 > 16 → akışta bölünüp sızabilirdi
    with pytest.raises(ValueError, match="holdback_max_chars"):
        B({"streaming": {"holdback_max_chars": 16}})
