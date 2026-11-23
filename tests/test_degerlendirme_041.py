"""0.4.1: dış değerlendirmenin ikinci raporundan çıkan düzeltmeler (kısmi maskeleme, adlar, "… Adı:" etiketi,
köşeli parantez, form "+", strict tarih etiketleri)."""

from __future__ import annotations

import pytest
from conftest import engine_for

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.engine import PIIEngine
from matriks_pii.revert import Reverter, StreamingReverter
from matriks_pii.session import MaskSession


def _mask(text: str, override: dict | None = None) -> tuple[str, MaskSession, PIIEngine]:
    eng = engine_for(override)
    s = MaskSession(eng.cfg)
    return eng.mask_text(text, s)[0], s, eng


@pytest.mark.parametrize("text,masked", [
    ("Müşteri no 4455-667788", "Müşteri no <MUSTERI_NO_1>"),
    ("Poliçe no 2024-00123456-7", "Poliçe no <POLICE_NO_1>"),
    ("MKK sicil no 1234567-8", "MKK sicil no <MKK_SICIL_1>"),
    ("hesap no 0012345/678", "hesap no <HESAP_NO_1>"),
    ("Poliçe no 1234567, 2024-01-15 tarihli", "Poliçe no <POLICE_NO_1>, 2024-01-15 tarihli"),
    ("hesap no 12345678 - 9 adet", "hesap no <HESAP_NO_1> - 9 adet"),
])
def test_no_partial_id(text: str, masked: str) -> None:
    assert _mask(text)[0] == masked


@pytest.mark.parametrize("text,masked", [
    ("Alıcı: İrem DUMAN", "Alıcı: <KISI_1>"),
    ("Alıcı: Ayşe KORKMAZ", "Alıcı: <KISI_1>"),
    ("Ahmet AVCI geldi", "<KISI_1> geldi"),
    ("Zeynep ÇİFTÇİ", "<KISI_1>"),
    ('To: "İrem DUMAN" <irem@example.com>', 'To: "<KISI_1>" <<EPOSTA_1>>'),
    ("Alıcı: Levent Bozkurt ve Defne Demirci", "Alıcı: <KISI_1> ve <KISI_2>"),
    ("Hesap Adı: Levent Bozkurt", "Hesap Adı: <KISI_1>"),
])
def test_names(text: str, masked: str) -> None:
    assert _mask(text)[0] == masked


@pytest.mark.parametrize("text", [
    "Ürün Adı: Kalem Seti", "Proje Adı: Kartal", "Şube Adı: Levent", "Cihaz Adı: SRV-IST-01",
    "Kullanıcı Adı: ademir", "Çan Çanakkale", "Kartal İstanbul", "Ahmet YAZDI",
])
def test_no_false_person(text: str) -> None:
    got = [s for s in engine_for().detected(text) if s.entity == "KISI"]
    assert not got or text == "Ahmet YAZDI" and [s.text for s in got] == ["Ahmet"]


def test_angle_brackets_kept_on_revert() -> None:
    text = "Kime: Ayşe Demir <ayse.demir@example.com>, cc: ali@example.org"
    masked, s, eng = _mask(text)
    assert masked == "Kime: <KISI_1> <<EPOSTA_1>>, cc: <EPOSTA_2>"
    r = Reverter(s.map, s.entities, eng.cfg, wrapped=s.wrapped)
    assert r.revert(masked) == text
    # LLM'in kendiliğinden çift parantezli yazdığı (istekte parantezsiz) yer tutucu eskisi gibi tek değere döner
    assert r.revert("<<EPOSTA_2>>") == "ali@example.org"
    # akış: parça parça
    sr = StreamingReverter(Reverter(s.map, s.entities, eng.cfg, wrapped=s.wrapped), 48)
    out = "".join(sr.feed(masked[k : k + 3]) for k in range(0, len(masked), 3)) + sr.flush()
    assert out == text
    # Redis serileştirmesi
    assert MaskSession.from_dict(eng.cfg, s.to_dict()).wrapped == {"<EPOSTA_1>"}


@pytest.mark.parametrize("text,ent", [
    ("form?tel=0532+123+45+67&ad=x", "TELEFON"),
    ("q?iban=TR33+0006+1005+1978+6457+8413+26", "IBAN"),
])
def test_form_plus(text: str, ent: str) -> None:
    masked, s, eng = _mask(text)
    assert [e for e in s.entities.values()] == [ent]
    assert Reverter(s.map, s.entities, eng.cfg).revert(masked, final=True) == text


@pytest.mark.parametrize("text", ["a+b=c", "C++ ve x+y", "1+1=2 işlemi"])
def test_form_plus_no_false_positive(text: str) -> None:
    assert engine_for().detected(text) == []


def test_strict_other_dates() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"profile": "strict"}))
    assert eng.detected("Fatura tarihi 15.03.2024, sözleşme 01.02.2023") == []
    assert eng.detected("Sözleşme tarihi: 01.02.2023") == []
    assert [s.entity for s in eng.detected("Doğum tarihi 12.03.1985")] == ["DOGUM_TARIHI"]
    assert [s.entity for s in eng.detected("Not: 12.03.1985")] == ["DOGUM_TARIHI"]


@pytest.mark.parametrize("text,masked", [
    ("Hesap No/TCKN: 12345678/17291716060", "Hesap No/TCKN: <HESAP_NO_1>/<TCKN_1>"),
    ("Müşteri No / Tel: 445566/05322345678", "Müşteri No / Tel: <MUSTERI_NO_1>/<TELEFON_1>"),
    ("müşteri no 12345/ali2@example.com", "müşteri no <MUSTERI_NO_1>/<EPOSTA_1>"),
    ("hesap no 12345678/05.11.1985 doğumlu", "hesap no <HESAP_NO_1>/<DOGUM_TARIHI_1> doğumlu"),
    ("GET /api?email=ayse.demir%2Bbanka%40gmail.com&x=1", "GET /api?email=<EPOSTA_1>&x=1"),
    ("GET /api?email=ayse.demir+banka%40gmail.com", "GET /api?email=<EPOSTA_1>"),
    ("redirect=https://x.com/?u=ali+veli%40example.com", "redirect=https://x.com/?u=<EPOSTA_1>"),
    ("Dosya adı: Ahmet_Yilmaz_CV.pdf", "Dosya adı: <KISI_1>_<KISI_2>_CV.pdf"),
])
def test_fable_041(text: str, masked: str) -> None:
    assert _mask(text)[0] == masked


@pytest.mark.parametrize("text", [
    "Kargo Konya Akşehir şubesinden çıktı.", "Teslimat adresi Mersin Anamur", "Şube: Aydın Söke",
    "Fatih Beyoğlu arası metro", "Kartal Pendik arası 10 km",
])
def test_place_pairs_not_person(text: str) -> None:
    assert [s for s in engine_for().detected(text) if s.entity == "KISI"] == []


def test_strict_label_needs_date_word() -> None:
    eng = PIIEngine(TurkishPIIConfig.build({"profile": "strict"}))
    assert [s.entity for s in eng.detected("Başvuru sahibi: 12.03.1985")] == ["DOGUM_TARIHI"]


def test_cli_typo() -> None:
    from matriks_pii.cli import main

    assert main(["selftset", "--config", "x.yaml"]) == 2


@pytest.mark.parametrize("text,masked", [
    ("hesap no 12345678/05 Kasım 1985 doğumlu", "hesap no <HESAP_NO_1>/<DOGUM_TARIHI_1> doğumlu"),
    ("Müşteri no 123456/15 Mart 1990 doğumlu Ayşe Demir", "Müşteri no <MUSTERI_NO_1>/<DOGUM_TARIHI_1> doğumlu <KISI_1>"),
    ("İrem DUMAN 17291716060", "<KISI_1> <TCKN_1>"),
    ("Alıcı: İrem DUMAN 0532 234 56 78", "Alıcı: <KISI_1> <TELEFON_1>"),
    ("Levent Bozkurt'tan gelen talep", "<KISI_1>'tan gelen talep"),
    ("Defne Demirci'den e-posta geldi", "<KISI_1>'den e-posta geldi"),
])
def test_fable_041_round2(text: str, masked: str) -> None:
    assert _mask(text)[0] == masked


@pytest.mark.parametrize("text", [
    "ad=Ayşe+Demir kaydı; Ayşe Demir ile görüşüldü", "tel=0532+123+45+67; tel 0532 123 45 67",
])
def test_form_plus_separate_placeholder_roundtrip(text: str) -> None:
    masked, s, eng = _mask(text)
    assert len(s.map) == 2
    assert Reverter(s.map, s.entities, eng.cfg).revert(masked, final=True) == text


@pytest.mark.parametrize("text", [
    "Seyhan Çukurova ilçelerinde", "Çınar Kayapınar hattında", "Kartal Maltepe sahil yolu", "Fatih Bağcılar tramvay hattı",
])
def test_place_context_inflected(text: str) -> None:
    assert [s for s in engine_for().detected(text) if s.entity == "KISI"] == []
