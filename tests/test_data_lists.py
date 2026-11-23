"""Çalışma anında hesaplanan ad/sözcük kümeleri: boyutlar ve örnekler sabit kalmalı.

"Hem ad hem sözcük" seçimleri pakette dosya olarak tutulmaz (tr_words.txt CC BY-SA 4.0 lisanslıdır);
`matriks_pii.data` bunları ad listeleri ile tr_words.txt'den hesaplar. Bu test, hesaplanan kümelerin
dosya olarak dağıtıldıkları önceki sürümle birebir aynı kaldığını boyut ve örneklerle sabitler.
"""

from __future__ import annotations

from matriks_pii import data


def test_sizes_unchanged() -> None:
    assert len(data.first_names()) == 6978
    assert len(data.last_names()) == 23940
    assert len(data.continuation_last_names()) == 2441
    assert len(data.rare_word_first_names()) == 672
    cw = data.common_words()
    assert len(cw) == 1382
    assert sum(1 for k in cw.values() if k == "strong") == 1204
    assert len(data.tr_words()) == 48395


def test_samples() -> None:
    cont, lasts, cw = data.continuation_last_names(), data.last_names(), data.common_words()
    assert "telefon" in cont and "telefon" not in lasts
    assert "saglam" in lasts and cw["saglam"] == "strong"
    assert {"berlin", "turkiye"} <= data.rare_word_first_names()
    assert cw["deniz"] == "weak" and cw["umut"] == "weak"
    # exclude (yalnızca ad) ve popüler adlar strong kümesine girmez
    assert "ahmet" not in cw and "ali" not in cw


def test_partition() -> None:
    """Soyadlar iki ayrık kümeye bölünür; sözcük-soyadların hepsi sözcük listesinde bulunur."""
    cont, lasts = data.continuation_last_names(), data.last_names()
    assert not cont & lasts
    assert cont <= data.tr_words()
    assert data.rare_word_first_names() <= data.first_names()
    assert "exclude" not in set(data.common_words().values())
