"""Özellik tabanlı testler (hypothesis): gidiş-dönüş, idempotans, sızıntısızlık, sağlamlık."""

from __future__ import annotations

from conftest import engine_for
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from matriks_pii.recognizers.checksums import luhn_complete, make_iban, make_tckn, make_vkn
from matriks_pii.revert import Reverter, StreamingReverter
from matriks_pii.session import MaskSession
from matriks_pii.tr_morphology import repair_suffix

ENG = engine_for({"suffix_repair": False, "entities": {"KART": {"action": "MASK", "restore": True}}})
SET = settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])

seed9 = st.integers(100_000_000, 999_999_999).map(str)
tckn = seed9.map(make_tckn)
vkn = seed9.map(make_vkn).filter(lambda v: v[0] != "5")
iban = st.integers(10**15, 10**16 - 1).map(lambda n: make_iban(str(n)))
troy = st.integers(0, 10**10).map(lambda n: luhn_complete("9792" + str(n).rjust(11, "0"), 16))

TEMPLATES = [
    "TC kimlik numaram {v}, teşekkürler.",
    "Vergi No: {w} ve IBAN {i}.",
    "Kart {c} ile ödeme; kimlik {v}!",
    "{v}\n{i}\n{c}",
    '{{"tckn": "{v}", "iban": "{i}"}}',
    "Müşteri ({v}) — IBAN: {i}; kart: {c}.",
]
filler = st.text(alphabet="abcçdefgğhıijklmnoöprsştuüvyz ,.;:!?()ÇĞİÖŞÜ", max_size=40)


def _roundtrip(text: str) -> tuple[str, MaskSession]:
    s = MaskSession(ENG.cfg)
    s.reserve_existing([text])
    to_mask, _, _ = ENG.actionable(ENG.analyze(text))
    return ENG.mask(text, to_mask, s), s


@SET
@given(st.sampled_from(TEMPLATES), tckn, vkn, iban, troy, filler, filler)
def test_mask_revert_roundtrip(tpl: str, v: str, w: str, i: str, c: str, pre: str, post: str) -> None:
    text = pre + " " + tpl.format(v=v, w=w, i=i, c=c) + " " + post
    masked, s = _roundtrip(text)
    for secret in (v, i, c):
        if secret in text:
            assert secret not in masked
    assert Reverter(s.map, s.entities, ENG.cfg, reserved=s.reserved).revert(masked) == text


@SET
@given(st.sampled_from(TEMPLATES), tckn, vkn, iban, troy)
def test_mask_idempotent(tpl: str, v: str, w: str, i: str, c: str) -> None:
    masked, _ = _roundtrip(tpl.format(v=v, w=w, i=i, c=c))
    again, _ = _roundtrip(masked)
    assert again == masked


@SET
@given(st.text(max_size=300))
def test_never_raises_on_random_text(t: str) -> None:
    masked, s = _roundtrip(t)
    assert Reverter(s.map, s.entities, ENG.cfg, reserved=s.reserved).revert(masked) == t


@settings(max_examples=300, deadline=None)
@given(st.sampled_from(TEMPLATES), tckn, vkn, iban, troy, st.lists(st.integers(1, 9), min_size=1, max_size=40))
def test_stream_equals_full(tpl: str, v: str, w: str, i: str, c: str, sizes: list[int]) -> None:
    masked, s = _roundtrip(tpl.format(v=v, w=w, i=i, c=c))
    full = Reverter(s.map, s.entities, ENG.cfg).revert(masked, final=True)
    sr = StreamingReverter(Reverter(s.map, s.entities, ENG.cfg), 48)
    out, k, j = "", 0, 0
    while k < len(masked):
        n = sizes[j % len(sizes)]
        out += sr.feed(masked[k : k + n])
        k += n
        j += 1
    assert out + sr.flush() == full


NAMES = ["Ayşe", "Ahmet", "Mehmet", "Ali", "Zeynep", "Umut", "Kadıköy", "Ufuk", "Gül", "Özge", "Emre", "Buğra"]
CASES = ["ın", "ya", "yı", "da", "dan", "la", "lar", "ki"]


@settings(max_examples=500, deadline=None)
@given(st.sampled_from(NAMES), st.sampled_from(NAMES), st.sampled_from(CASES))
def test_repair_suffix_consistent(a: str, b: str, sfx: str) -> None:
    # A için üretilmiş eki B'ye uyarlayıp tekrar A'ya uyarlamak A'nın doğru ekini verir
    sa = repair_suffix(a, sfx)
    sb = repair_suffix(b, sa)
    assert repair_suffix(a, sb) == sa
