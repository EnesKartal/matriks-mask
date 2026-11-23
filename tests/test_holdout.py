"""Bağımsız değerlendirme kümeleri (tests/fixtures/holdout/) — regresyon eşikleri.

İki küme de uygulama kodunu görmeyen ayrı ajanlar tarafından yazıldı. İlk (kör) ölçümlerden sonra bulunan genel hatalar
düzeltildi; bu yüzden artık "kör" değildir, yalnız gerilemeyi yakalar.

- holdout.jsonl: deterministik varlıklar + KISI eşiği. Özel nitelikli verilerde span sınırları bu kümede yoruma açık
  yazıldığından (ör. "ceza aldı" / "hapis cezası aldı") OZEL_* eşiği uygulanmaz.
- holdout2.jsonl: deterministik varlıklar (GIZLI_ANAHTAR, KONUM dâhil) + KISI + MASK edilen OZEL_* toplam recall eşiği.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from conftest import engine_for

DIR = Path(__file__).parent / "fixtures" / "holdout"
DETERMINISTIC = {"TCKN", "VKN", "IBAN", "KART", "TELEFON", "EPOSTA", "IP", "PLAKA", "GIZLI_ANAHTAR", "KONUM"}


def _stats(name: str) -> dict[str, Counter]:
    eng = engine_for()
    st: dict[str, Counter] = {}
    for line in (DIR / name).read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        got = Counter((s.entity, s.text) for s in eng.detected(c["text"]))
        exp = Counter((e["entity"], e["value"]) for e in c["entities"])
        for ent, val in got | exp:
            tp = min(got[(ent, val)], exp[(ent, val)])
            s = st.setdefault(ent, Counter())
            s["tp"] += tp
            s["fp"] += got[(ent, val)] - tp
            s["fn"] += exp[(ent, val)] - tp
    return st


def _prf(c: Counter) -> tuple[float, float, float]:
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 1.0
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 1.0
    f2 = 5 * p * r / (4 * p + r) if p + r else 0.0
    return p, r, f2


@pytest.mark.parametrize("name", ["holdout.jsonl", "holdout2.jsonl"])
def test_holdout_thresholds(name: str) -> None:
    st = _stats(name)
    for ent in DETERMINISTIC & set(st):
        assert st[ent]["fp"] == 0 and st[ent]["fn"] == 0, (name, ent, dict(st[ent]))
    p, r, f2 = _prf(st["KISI"])
    assert r >= 0.95 and f2 >= 0.95, (name, p, r, f2)


def test_holdout2_special_category_recall() -> None:
    st = _stats("holdout2.jsonl")
    oz: Counter = Counter()
    for ent, c in st.items():
        if ent.startswith("OZEL_"):  # varsayılan profilde OZEL_* MASK
            oz.update(c)
    _, r, _ = _prf(oz)
    assert r >= 0.90, dict(oz)


def test_holdout2_new_entities_present() -> None:
    st = _stats("holdout2.jsonl")
    for ent in ("GIZLI_ANAHTAR", "KONUM", "MKK_SICIL", "POLICE_NO"):
        assert st.get(ent, Counter())["tp"] > 0, ent
