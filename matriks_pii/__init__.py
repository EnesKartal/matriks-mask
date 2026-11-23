"""matriks-pii: KVKK uyum süreçlerini destekleyen, Türkçe ve geri çevrilebilir PII maskeleme guardrail'i."""

from __future__ import annotations

from typing import Any

from .config import TurkishPIIConfig
from .engine import PIIEngine
from .revert import Reverter, StreamingReverter
from .session import MaskSession


def _pkg_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover
        return "0.0.0+local"
    for dist in ("matriks-mask", "matriks-pii"):  # dağıtım adı 0.4.0'dan itibaren matriks-mask; içe aktarma adı aynı
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "0.0.0+local"


__version__ = _pkg_version()

__all__ = ["MaskSession", "PIIEngine", "Reverter", "StreamingReverter", "TurkishPIIConfig", "TurkishPIIGuardrail", "__version__"]


def __getattr__(name: str) -> Any:
    if name == "TurkishPIIGuardrail":  # litellm yalnız guardrail kullanılırken gerekli
        from .guardrail import TurkishPIIGuardrail

        return TurkishPIIGuardrail
    raise AttributeError(name)
