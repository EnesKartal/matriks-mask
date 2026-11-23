r"""LLM'in bozduğu yer tutucu biçimleri: markdown kaçışı ("<KISI\_1>", "\<KISI_1\>") ve numarasız genel biçim
("<TCKN_...>"; etikette tek değer varsa o değer). Test ortamında görülen vakalar."""

from __future__ import annotations

import pytest

from matriks_pii.config import TurkishPIIConfig
from matriks_pii.revert import Reverter
from matriks_pii.streaming import StreamingReverter

CFG = TurkishPIIConfig.build({})
MAP = {"<KISI_1>": "Ayşe Demir", "<TCKN_1>": "17291716060", "<KISI_2>": "Ali Can"}
ENTS = {"<KISI_1>": "KISI", "<TCKN_1>": "TCKN", "<KISI_2>": "KISI"}


@pytest.mark.parametrize(("llm", "expect"), [
    (r"<KISI\_1> aradı", "Ayşe Demir aradı"),
    (r"\<KISI_1\> aradı", "Ayşe Demir aradı"),
    (r"\<KISI\_1\> aradı", "Ayşe Demir aradı"),
    (r"\[KISI_1\] aradı", "Ayşe Demir aradı"),
    (r"KISI\_1 aradı", "Ayşe Demir aradı"),
    ("numaranız (<TCKN_...>)", "numaranız (17291716060)"),
    ("numaranız <TCKN_…>", "numaranız 17291716060"),
    ("numaranız <TCKN_X>", "numaranız 17291716060"),
    ("numaranız <TCKN_N>", "numaranız 17291716060"),
    ("<TCKN_...>'yi doğruladım", "17291716060'ı doğruladım"),
    ("<KISI_...> kim?", "<KISI_...> kim?"),          # iki KISI var: hangisi bilinemez
    ("<TELEFON_...> yok", "<TELEFON_...> yok"),      # etikette değer yok
    ("TCKN_... alanı", "TCKN_... alanı"),            # parantezsiz genel biçim metin olabilir
    ("dosya a\b yolu", "dosya a\b yolu"),
])
def test_variants(llm: str, expect: str) -> None:
    assert Reverter(MAP, ENTS, CFG).revert(llm) == expect


def test_generic_counts_unresolved_when_ambiguous() -> None:
    r = Reverter(MAP, ENTS, CFG)
    r.revert("<KISI_...>")
    assert r.stats.unresolved == 1 and r.stats.replaced == 0


@pytest.mark.parametrize("size", [1, 2, 3, 5, 8])
def test_streaming_variants_every_split(size: int) -> None:
    text = r"Numara (\<TCKN\_1\>) ve <TCKN_...> ile <KISI\_2>."
    sr = StreamingReverter(Reverter(MAP, ENTS, CFG))
    out = "".join(sr.feed(text[i:i + size]) for i in range(0, len(text), size)) + sr.flush()
    assert out == "Numara (17291716060) ve 17291716060 ile Ali Can."
