"""Tanıyıcı kayıt defteri."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .address import AddressRecognizer
from .base import AnalysisContext, Recognizer, Span
from .contextual import ContextualIdRecognizer, DenyListRecognizer, DobRecognizer, ExtraRegexRecognizer
from .location import LocationRecognizer
from .number_words import NumberWordsRecognizer
from .numeric import CardRecognizer, IbanRecognizer, TcknRecognizer, VknRecognizer
from .person import PersonRecognizer
from .phone import PhoneRecognizerFactory
from .secrets import SecretRecognizer
from .simple import EmailRecognizer, IpRecognizer, PlateRecognizer
from .special_category import SpecialCategoryRecognizer

if TYPE_CHECKING:
    from ..config import TurkishPIIConfig

__all__ = ["AnalysisContext", "Recognizer", "Span", "build_recognizers"]


def build_recognizers(cfg: TurkishPIIConfig) -> list[Recognizer]:
    """Faz 1 sırası önemlidir: IBAN ilk çalışır (dışlama bölgelerini doldurur)."""
    recs: list[Recognizer] = [
        SecretRecognizer(),  # anahtarlar içinde rakam/harf dizileri başka varlık sanılmasın diye önce
        IbanRecognizer(),
        CardRecognizer(),
        TcknRecognizer(),
        VknRecognizer(),
        PhoneRecognizerFactory.build(cfg),
        EmailRecognizer(),
        IpRecognizer(),
        PlateRecognizer(),
        LocationRecognizer(),
        ContextualIdRecognizer(),
        DobRecognizer(),
        AddressRecognizer(),
        NumberWordsRecognizer(),
    ]
    if cfg.name_detection.lexicon:
        recs.append(PersonRecognizer())
    if cfg.name_detection.ner_backend == "hf":
        from .ner_hf import HFNerRecognizer

        recs.append(HFNerRecognizer(cfg))
    if cfg.deny_list:
        recs.append(DenyListRecognizer(cfg))
    if cfg.extra_regex:
        recs.append(ExtraRegexRecognizer(cfg))
    recs.append(SpecialCategoryRecognizer())
    return recs
