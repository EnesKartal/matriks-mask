"""Veri üretim betikleri (scripts/build_*.py) için hafif testler — ağ erişimi gerektirmez."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_org_names  # noqa: E402
import pytest  # noqa: E402

# betik kaynak ağacındaki veri dosyasını okur/yazar; kurulu wheel üzerinde (kaynak ağacı yokken) koşmaz
needs_source = pytest.mark.skipif(not build_org_names.OUT.exists(), reason="kaynak ağacı gerekir (matriks_pii/data)")


@needs_source
def test_org_names_file_is_normalized() -> None:
    # elle derlenmiş liste betiğin ürettiğiyle aynı olmalı (tekrarsız, Türkçe küçük harf)
    assert build_org_names.build(None) == build_org_names.OUT.read_text(encoding="utf-8")


def test_kap_titles_only_two_word_name_plus_sector() -> None:
    got = build_org_names.kap_titles_to_names([
        "KOÇ HOLDİNG A.Ş.", "ZORLU ENERJİ ELEKTRİK ÜRETİM A.Ş.", "DOĞAN ŞİRKETLER GRUBU HOLDİNG A.Ş.",
        "KILIÇ DENİZ ÜRÜNLERİ ÜRETİMİ A.Ş.", "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.", "DOĞAN A.Ş.",
    ])
    assert got == ["doğan şirketler", "koç holding", "zorlu enerji"]


@needs_source
def test_kap_section_appended_and_regenerated(tmp_path: Path) -> None:
    kap = tmp_path / "kap.txt"
    kap.write_text("KOÇ HOLDİNG A.Ş.\nYILMAZ TEKSTİL SANAYİ A.Ş.\n", encoding="utf-8")
    text = build_org_names.build(kap)
    assert build_org_names.KAP_HEADER in text and text.rstrip().endswith("yılmaz tekstil")
    assert text.count(build_org_names.KAP_HEADER) == 1
