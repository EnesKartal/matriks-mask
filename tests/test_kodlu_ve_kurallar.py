"""URL/HTML kodlu değerler, extra_regex `group`, strict tarih kuralı, --corpus hata iletisi."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import engine_for

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.revert import Reverter
from matriks_pii.selftest import main as selftest_main
from matriks_pii.session import MaskSession
from matriks_pii.text_utils import decode_for_scan

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _roundtrip(text: str, override: dict | None = None) -> tuple[str, str]:
    eng = engine_for(override)
    sess = MaskSession(eng.cfg)
    masked = eng.mask_text(text, sess)[0]
    return masked, Reverter(sess.map, sess.entities, eng.cfg).revert(masked, final=True)


def test_url_encoded_roundtrip_keeps_original_encoding() -> None:
    text = "https://x.example/?u=ayse.demir%40example.com&t=0532%20123%2045%2067&next=%2Fhome"
    masked, back = _roundtrip(text)
    assert "%40example" not in masked and "0532%20" not in masked and "%2Fhome" in masked
    assert back == text


def test_html_entity_roundtrip() -> None:
    text = "Yazın: ayse&#64;example.com veya ayse@example.com"
    masked, back = _roundtrip(text)
    assert masked == "Yazın: <EPOSTA_1> veya <EPOSTA_2>"  # kodlu ve düz yazım ayrı yer tutucu
    assert back == text  # her biri kendi yazımıyla geri döner


@pytest.mark.parametrize("text,ent", [
    ("IBAN: TR33 0006 1005 1978 6457 8413 26", "IBAN"),
    ("Kart: 4111 1111 1111 1111", "KART"),
    ("Kart: 4111‑1111‑1111‑1111", "KART"),
    ("TCKN 17291716060", "TCKN"),
])
def test_unicode_spaces_and_dashes(text: str, ent: str) -> None:
    got = engine_for().detected(text)
    assert [s.entity for s in got] == [ent] and got[0].text in text


def test_merged_span_prefers_masked_entity() -> None:
    got = engine_for().detected("şifre: Gizli123!AA%3ABB%3ACC%3ADD%3AEE%3AFF")
    assert [s.entity for s in got] == ["SIFRE"]


def test_cli_non_utf8_stdin() -> None:
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "matriks_pii.cli", "mask"], input=b"Ay\xfee Demir 0532 234 56 78\n",
                       capture_output=True)
    assert r.returncode == 0 and b"<TELEFON_1>" in r.stdout, r.stderr


@pytest.mark.parametrize("text", ["Faiz %40 arttı", "(%53)", "%20'ye", "hedef %25.", "R&D", "a & b", "100%"])
def test_percent_and_ampersand_text_not_decoded(text: str) -> None:
    assert decode_for_scan(text) is None


def test_decode_map_points_to_original_ranges() -> None:
    text = "q=%C3%9Cmit%20Kaya&m=a%2540b.com"
    dec, starts, ends = decode_for_scan(text)  # type: ignore[misc]
    assert dec == "q=Ümit Kaya&m=a@b.com"
    i = dec.index("Ü")
    assert text[starts[i] : ends[i]] == "%C3%9C"
    j = dec.index("@")
    assert text[starts[j] : ends[j]] == "%2540"


def test_decoding_does_not_change_unencoded_detection() -> None:
    plain = "Ahmet Yılmaz 0532 234 56 78"
    eng = engine_for()
    base = [(s.entity, s.start, s.end) for s in eng.detected(plain)]
    assert [(s.entity, s.start, s.end) for s in eng.detected(plain + " ?q=a%20b")] == base


def test_extra_regex_group() -> None:
    eng = engine_for({"extra_regex": [
        {"entity": "HESAP_NO", "pattern": r"(?:AccountId=|\|1=)(\d{6,12})", "group": 1, "score": 0.9},
        {"entity": "KULLANICI_ADI", "pattern": r"username=(?P<u>[\w.\-]+)", "group": "u"},
    ]})
    got = [(s.entity, s.text) for s in eng.detected("login failed username=ademir AccountId=12345678 8=FIX.4.4|35=D|1=48213377")]
    assert got == [("KULLANICI_ADI", "ademir"), ("HESAP_NO", "12345678"), ("HESAP_NO", "48213377")]


@pytest.mark.parametrize("group", [2, "yok", True])
def test_extra_regex_group_validated(group: object) -> None:
    with pytest.raises(ValueError):
        TurkishPIIConfig.build({"extra_regex": [{"entity": "X", "pattern": r"a(\d+)", "group": group}]})


def test_strict_dates() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"profile": "strict"}))
    assert [s.entity for s in eng.detected("Not: 12.03.1985")] == ["DOGUM_TARIHI"]  # strict: bağlamsız da
    assert eng.detected("2026-11-20 14:32:11 INFO order accepted") == []
    assert eng.detected("Ödeme 20.11.2026 saat 14:30'da alındı") == []
    assert eng.detected("Vade 15.03.2099") == []


def test_corpus_format_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "k.txt"
    bad.write_text("düz metin, JSON değil\n", encoding="utf-8")
    assert selftest_main(["--config", str(EXAMPLES / "config.yaml"), "--quick", "--corpus", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "JSONL" in err and "Traceback" not in err and "düz metin" not in err


def test_corpus_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ok = tmp_path / "k.jsonl"
    ok.write_text(json.dumps({"text": "TCKN 17291716060", "entities": [{"entity": "TCKN", "value": "17291716060"}]}) + "\n",
                  encoding="utf-8")
    assert selftest_main(["--config", str(EXAMPLES / "config.yaml"), "--quick", "--corpus", str(ok), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["guardrails"][0]["corpus"]["TCKN"]["r"] == 1.0


@pytest.mark.parametrize("text,ent,val", [
    ("hesap no 12345678-9", "HESAP_NO", "12345678-9"),
    ("hesap no 123456-78", "HESAP_NO", "123456-78"),
    ("hesap no 1234567890", "HESAP_NO", "1234567890"),
    ("<ns:Password>Gizli123!</ns:Password>", "SIFRE", "Gizli123!"),
    ('<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">'
     "Gizli123!</wsse:Password>", "SIFRE", "Gizli123!"),
    ("x?hesap%20no=12345678&y=1", "HESAP_NO", "12345678"),
    ("m%C3%BC%C5%9Fteri%20no%3A%20123456", "MUSTERI_NO", "123456"),
    ("&#351;ifre: Gizli123!", "SIFRE", "Gizli123!"),
])
def test_review_cases(text: str, ent: str, val: str) -> None:
    assert [(s.entity, s.text) for s in engine_for().detected(text)] == [(ent, val)]


def test_no_hyphen_range_as_account() -> None:
    assert engine_for().detected("hesap no: 2 adet, 100-200 TL") == []


def test_decoded_span_never_drops_original() -> None:
    eng = engine_for()
    t = "plaka 34 ABC 123%40x.com?a=1"
    spans = eng.detected(t)
    covered = {i for s in spans for i in range(s.start, s.end)}
    assert set(range(t.index("34"), t.index("?a"))) <= covered


def test_strict_dates_review() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"profile": "strict"}))
    assert [s.text for s in eng.detected("Tarihler: 15.03.1985 20.04.1990")] == ["15.03.1985", "20.04.1990"]
    assert [s.text for s in eng.detected("Not 12.03.1985 12.05 kg")] == ["12.03.1985"]


@pytest.mark.parametrize("text,ents", [
    ("Kart: 5580439705267216–CVV: 920", ["KART", "KART_CVV"]),
    ("Visa 4111 1111 1111 1111–Ayşe Demir", ["KART", "KISI"]),
    ("–4111111111111111", ["KART"]),
    ("müşteri no–3390127", ["MUSTERI_NO"]),
    ("Kart 4111‑1111‑1111‑1111", ["KART"]),
    ("4111111111111111-x", ["KART"]),
    ("Kart: 5580439705267216-CVV: 920", ["KART", "KART_CVV"]),
    ("IBAN: TR33&nbsp;0006&nbsp;1005&nbsp;1978&nbsp;6457&nbsp;8413&nbsp;26", ["IBAN"]),
    ("Kart 4111&nbsp;1111&nbsp;1111&nbsp;1111", ["KART"]),
    ("Tel: 0532&#8209;234&#8209;56&#8209;78", ["TELEFON"]),
    ("q=TR33%C2%A00006%C2%A01005%C2%A01978%C2%A06457%C2%A08413%C2%A026&x=1", ["IBAN"]),
])
def test_dashes_and_encoded_spaces(text: str, ents: list[str]) -> None:
    assert [s.entity for s in engine_for().detected(text)] == ents


@pytest.mark.parametrize("text", ["ref 1234-4111111111111111", "2020–2021 dönemi 4500 TL", "sayfa 12–14"])
def test_dash_no_new_false_positive(text: str) -> None:
    assert engine_for().detected(text) == []
