"""Tanıyıcı temel tipleri."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..text_utils import fold_text, fre, sentence_spans

if TYPE_CHECKING:
    from ..config import TurkishPIIConfig


EXTENDED_SUFFIX = "+uzatma"  # bitişik parçalarla uzatılmış aday (recognizer adına eklenir)


@dataclass(frozen=True, order=True)
class Span:
    start: int
    end: int
    entity: str
    text: str
    score: float
    recognizer: str
    normalized: str

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class AnalysisContext:
    cfg: TurkishPIIConfig
    text: str
    casefolded: str
    sentences: list[tuple[int, int]]
    exclusion_zones: list[tuple[int, int]] = field(default_factory=list)
    prior_spans: list[Span] = field(default_factory=list)
    _sent_starts: list[int] | None = None
    _prior_starts: list[int] | None = None

    @classmethod
    def build(cls, cfg: TurkishPIIConfig, text: str) -> AnalysisContext:
        cf = fold_text(text)  # Türkçe küçük harf + ASCII katlama; desenler `fre` ile katlanmış derlenir
        if len(cf) != len(text):  # güvenlik ağı; uzunluk korunmalı
            cf = "".join(c if len(fold_text(c)) != 1 else fold_text(c) for c in text)
        return cls(cfg=cfg, text=text, casefolded=cf, sentences=sentence_spans(text))

    def add_exclusion(self, start: int, end: int) -> None:
        bisect.insort(self.exclusion_zones, (start, end))

    def in_exclusion(self, start: int, end: int) -> bool:
        """Sıralı bölge listesinde O(log n): [start, end) ile kesişen bölge var mı?"""
        z = self.exclusion_zones
        if not z:
            return False
        i = bisect.bisect_left(z, (end, end))  # başlangıcı end'den küçük olanlar aday
        j = i - 1
        while j >= 0:
            s, e = z[j]
            if e > start:
                return True
            if s < start - 4096:  # bölgeler kısa (≤ 40 kr); çok gerisine bakmaya gerek yok
                break
            j -= 1
        return False

    def sentence_of(self, pos: int) -> tuple[int, int]:
        if self._sent_starts is None:
            self._sent_starts = [s for s, _ in self.sentences]
        i = bisect.bisect_right(self._sent_starts, pos) - 1
        if 0 <= i < len(self.sentences):
            s, e = self.sentences[i]
            if s <= pos < e:
                return s, e
        return 0, len(self.text)

    def prior_in(self, lo: int, hi: int, entities: frozenset[str]) -> bool:
        """[lo, hi) aralığıyla kesişen, verilen türde bir faz-1 span'i var mı? (prior_spans ayrık ve sıralı)"""
        if self._prior_starts is None or len(self._prior_starts) != len(self.prior_spans):
            self._prior_starts = [s.start for s in self.prior_spans]
        i = max(0, bisect.bisect_left(self._prior_starts, lo) - 1)
        while i < len(self.prior_spans) and self.prior_spans[i].start < hi:
            sp = self.prior_spans[i]
            if sp.end > lo and sp.entity in entities:
                return True
            i += 1
        return False

    def has_context(self, start: int, end: int, pattern: re.Pattern[str], window: int | None = None) -> bool:
        w = self.cfg.context_window if window is None else window
        lo, hi = max(0, start - w), min(len(self.text), end + w)
        seg = self.casefolded[lo:start] + " " + self.casefolded[end:hi]
        return pattern.search(seg) is not None

    def context_before(self, start: int, pattern: re.Pattern[str], window: int | None = None) -> bool:
        w = self.cfg.context_window if window is None else window
        return pattern.search(self.casefolded[max(0, start - w) : start]) is not None


class Recognizer:
    name: str = "base"
    entities: tuple[str, ...] = ()
    phase: int = 1

    def find(self, text: str, ctx: AnalysisContext) -> list[Span]:  # pragma: no cover - arayüz
        raise NotImplementedError


def ctx_re(*words: str) -> re.Pattern[str]:
    """Bağlam kelimeleri için sözcük sınırlı desen (katlanmış `casefolded` metinde aranır)."""
    alts = "|".join(sorted(words, key=len, reverse=True))
    return fre(rf"(?<![0-9a-z])(?:{alts})(?![a-z])")


def ctx_prefix_re(*words: str) -> re.Pattern[str]:
    """Kelime başında eşleşen (çekim ekine izin veren) bağlam deseni."""
    alts = "|".join(sorted(words, key=len, reverse=True))
    return fre(rf"(?<![0-9a-z])(?:{alts})")
