"""Fixture öz-tutarlılığı: kimlikler, değerlerin metinde geçmesi, checksum'lar, gidiş-dönüş."""

from __future__ import annotations

import html
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import yaml
from conftest import FIX, engine_for, load_cases

from matriks_pii.recognizers.checksums import card_valid, iban_valid, tckn_valid, vkn_valid
from matriks_pii.revert import Reverter
from matriks_pii.session import MaskSession

ALL = {sub: load_cases(sub) for sub in ("detect", "negative", "revert", "streaming")}


def test_counts() -> None:
    assert len(ALL["detect"]) >= 487
    assert len(ALL["negative"]) == 595
    assert len(ALL["revert"]) >= 40 and len(ALL["streaming"]) >= 20


def test_ids_unique_and_prefixed() -> None:
    ids = [c["id"] for sub in ALL.values() for _, c in sub]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    assert not dup, dup
    for _, c in ALL["negative"]:
        assert c["id"].startswith("NEG-")
    for _, c in ALL["detect"]:
        assert re.fullmatch(r"[A-Z]+-\d{3}", c["id"])


def test_files_utf8_no_bom() -> None:
    for f in Path(FIX).rglob("*.yaml"):
        raw = f.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f
        raw.decode("utf-8")
        assert yaml.safe_load(raw.decode("utf-8")) is not None


def test_expected_values_in_text_and_checksums() -> None:
    for _, c in ALL["detect"]:
        for e in c["expect"]:
            assert e["value"] in c["text"], (c["id"], e)
            if "invalid_checksum" in c.get("tags", []):
                continue
            # tam genişlik rakam (NFKC), gruplu TCKN noktası, etiketli TR'siz IBAN da doğrulanır
            raw = html.unescape(unquote(unquote(e["value"])))  # URL/HTML kodlu değerler (kodlu_ek.yaml)
            digits = re.sub(r"[\s\-.]" if e["entity"] == "TCKN" else r"[\s\-]", "", unicodedata.normalize("NFKC", raw))
            if e["entity"] == "IBAN" and digits[:1].isdigit():
                digits = "TR" + digits
            if e["entity"] == "TCKN" and c.get("config", {}).get("tckn_require_checksum", True):
                assert tckn_valid(digits), c["id"]
            elif e["entity"] == "VKN":
                assert vkn_valid(digits), c["id"]
            elif e["entity"] == "IBAN":
                assert iban_valid(digits), c["id"]
            elif e["entity"] == "KART":
                assert card_valid(digits), c["id"]


def test_negative_numbers_fail_checksums() -> None:
    for _, c in ALL["negative"]:
        t = c["text"]
        for m in re.finditer(r"(?<![0-9])[1-9][0-9]{10}(?![0-9])", t):
            assert not tckn_valid(m.group()), c["id"]


def test_masked_roundtrip() -> None:
    for _, c in ALL["detect"]:
        if "masked" not in c or "surface_variants" in c.get("tags", []):
            continue
        eng = engine_for({**(c.get("config") or {}), "suffix_repair": False})
        s = MaskSession(eng.cfg)
        s.reserve_existing([c["text"]])
        to_mask, _, _ = eng.actionable(eng.analyze(c["text"]))
        masked = eng.mask(c["text"], to_mask, s)
        if any(not eng.cfg.restore(x.entity) for x in to_mask):
            continue
        assert Reverter(s.map, s.entities, eng.cfg, reserved=s.reserved).revert(masked) == c["text"], c["id"]


def test_no_real_person_data_marker() -> None:
    assert "sentetik" in (Path(FIX) / "README.md").read_text(encoding="utf-8")
