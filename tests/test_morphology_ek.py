"""Türkçe ek onarımı tablo testi (TDK: kesme işareti, büyük ünlü uyumu istisnaları, ünsüz benzeşmesi)."""

from __future__ import annotations

import pytest

from matriks_pii.text_utils import tr_lower
from matriks_pii.tr_morphology import generate, parse_suffix, repair_suffix

CASES = [
    # damak l'si (TDK: alkolü, helalimiz) — adlarda: Kemal'e, Celal'i
    ("Halil", "a", "e"), ("Kemal", "a", "e"), ("Kemal", "ın", "in"), ("Celal", "ı", "i"), ("Cemal", "dan", "den"),
    ("Bilal", "a", "e"), ("Nihal", "a", "e"), ("İkbal", "a", "e"), ("İclal", "a", "e"), ("Resul", "a", "e"),
    ("Kemâl", "a", "e"), ("usûl", "u", "ü"), ("Mustafa Kemal", "a", "e"),
    # düzenli ünlü/ünsüz uyumu
    ("Gül", "a", "e"), ("Ufuk", "e", "a"), ("Emel", "a", "e"), ("Ayşe", "e", "ye"), ("Ali", "e", "ye"),
    ("Mehmet", "de", "te"), ("Zeynep", "de", "te"), ("Umut", "ın", "un"), ("Fatma", "la", "yla"),
    ("Yılmaz", "in", "ın"), ("Öztürk", "ın", "ün"), ("Can", "in", "ın"), ("Çelik", "ın", "in"), ("Gökhan", "i", "ı"),
    ("Oğuz", "i", "u"), ("Burak", "i", "ı"), ("Tuba", "ye", "ya"), ("Deniz", "ı", "i"), ("Hakan", "e", "a"),
    ("Nur", "e", "a"), ("Yusuf", "e", "a"), ("Hüseyin", "a", "e"), ("Ömer", "a", "e"), ("Osman", "e", "a"),
    ("Selin", "a", "e"), ("Melis", "a", "e"), ("Kadıköy", "da", "de"), ("Ankara", "de", "da"), ("Metin", "a", "e"),
    ("Saadet", "a", "e"), ("Şükrü", "a", "ye"),
    # büyük harf değer
    ("AHMET", "in", "İN"), ("AYŞE", "e", "YE"), ("YILMAZ", "in", "IN"),
    # kopula / rivayet / iyelik / -ki + belirtme
    ("Ahmet", "ydi", "ti"), ("Ali", "ymış", "ymiş"), ("Ayşe", "sı", "si"), ("Ahmet", "dekini", "tekini"),
    ("Ali", "dı", "ydi"), ("Zeynep", "mış", "miş"),
    # rakamla biten değerler (okunuşa göre)
    ("No: 6", "de", "da"), ("No: 5", "de", "te"), ("100", "da", "de"), ("1000", "a", "e"), ("20", "a", "ye"),
    ("17291716060", "in", "ın"), ("30", "e", "a"), ("0532 123 45 67", "ı", "yi"), ("1111", "a", "e"),
    ("TR33 0006 1005 1978 6457 8413 26", "den", "dan"), ("40", "e", "a"), ("90", "a", "a"), ("3", "te", "te"),
    # noktalama ile biten değer: aynen
    ("Cad.", "de", "de"),
]


@pytest.mark.parametrize(("word", "given", "expected"), CASES)
def test_repair_table(word: str, given: str, expected: str) -> None:
    assert repair_suffix(word, given) == expected


@pytest.mark.parametrize("name", ["Ahmet", "Ayşe", "Kemal", "Ufuk", "Celal", "Öztürk", "Gül", "Ali", "Umut", "AHMET"])
@pytest.mark.parametrize("cls", ["GEN", "DAT", "ACC", "LOC", "ABL", "INS", "PLU", "COP", "P1S", "P3S", "PAST", "EVID", "EQU"])
def test_generate_fixed_point(name: str, cls: str) -> None:
    """Doğru eki yeniden onarmak onu değiştirmez (sabit nokta)."""
    sfx = generate(cls, name)
    if not parse_suffix(sfx):
        pytest.skip(f"tek harfli ek ayrıştırılmaz: {name}+{sfx}")
    assert tr_lower(repair_suffix(name, sfx)) == tr_lower(sfx)
