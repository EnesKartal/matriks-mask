"""Komut satırı: `matriks-mask` (eski adı `matriks-pii` da çalışır).

    matriks-mask "Ben Ayşe Demir, TCKN 17291716060"          # maskeli metin (= matriks-mask mask "…")
    echo "..." | matriks-mask mask --profile strict          # standart girdiden
    matriks-mask mask --config config.yaml "..."             # LiteLLM config'indeki guardrail ayarlarıyla
    matriks-mask mask --json "..."                           # maskeli metin + tespitler (değersiz)
    matriks-mask selftest --config config.yaml [--quick]     # = python -m matriks_pii.selftest
    matriks-mask keys [--k8s]                                # = python -m matriks_pii.keys

`mask` çıktısı yalnız maskeli metni ve (--json ile) tespitlerin türünü/konumunu içerir; yer tutucu → değer haritası
hiçbir zaman yazdırılmaz. BLOCK aksiyonlu bir varlık bulunursa metin yazdırılmaz, çıkış kodu 2 olur.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

_SUB = ("mask", "selftest", "keys")


def _config(args: argparse.Namespace) -> Any:
    from .config import TurkishPIIConfig

    if not args.config:
        return TurkishPIIConfig.build({"profile": args.profile})
    from .selftest import _LITELLM_KEYS, load_guardrails

    found = [(n, p) for n, p in load_guardrails(args.config) if not args.guardrail or n == args.guardrail]
    if not found:
        raise SystemExit(f"matriks-pii: {args.config} içinde matriks-pii guardrail'i yok")
    cfg, _rest = TurkishPIIConfig.from_kwargs({k: v for k, v in found[0][1].items() if k not in _LITELLM_KEYS})
    return cfg


def _mask(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="matriks-mask mask", description="Metindeki kişisel verileri maskeler.")
    ap.add_argument("text", nargs="?", help="maskelenecek metin (verilmezse standart girdiden okunur)")
    ap.add_argument("--profile", choices=["balanced", "strict", "minimal"], default="balanced")
    ap.add_argument("--config", help="LiteLLM config.yaml (guardrail ayarları buradan okunur; --profile yok sayılır)")
    ap.add_argument("--guardrail", help="config'de birden çok guardrail varsa adı")
    ap.add_argument("--json", action="store_true", help="maskeli metin + tespitler (tür, konum, skor; değer yok)")
    a = ap.parse_args(argv)
    text = a.text if a.text is not None else sys.stdin.read()

    from .engine import PIIEngine
    from .session import MaskSession

    try:
        cfg = _config(a)
    except (ValueError, OSError) as e:  # yapılandırma iletileri değer içermez (config.py)
        print(f"matriks-pii: yapılandırma hatası: {e}", file=sys.stderr)
        return 1
    try:
        masked, spans, blocked, logged = PIIEngine(cfg).mask_text(text, MaskSession(cfg))
    except ValueError as e:  # ör. max_text_chars; ileti değer içermez
        print(f"matriks-pii: {e}", file=sys.stderr)
        return 1
    if blocked:
        print(f"matriks-pii: BLOCK ({', '.join(sorted({s.entity for s in blocked}))}); metin yazdırılmadı", file=sys.stderr)
        return 2
    if a.json:
        out = {
            "masked": masked,
            "entities": [{"entity": s.entity, "start": s.start, "end": s.end, "score": round(s.score, 3)} for s in spans],
            "logged": sorted({s.entity for s in logged}),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(masked if masked.endswith("\n") else masked + "\n")
    return 0


def _utf8_streams() -> None:
    """Türkçe karakterler UTF-8 olmayan konsol/borularda (ör. Windows cp1252) UnicodeEncodeError vermesin."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is not None and (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            try:
                reconf(encoding="utf-8", errors="replace" if stream is sys.stdin else "strict")
            except (ValueError, OSError):  # pragma: no cover
                pass


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in _SUB and argv[0] not in ("-h", "--help", "--version"):
        import difflib

        near = difflib.get_close_matches(argv[0], ("selftest", "keys"), n=1, cutoff=0.75)
        if near and " " not in argv[0]:
            print(f"matriks-mask: bilinmeyen komut '{argv[0]}'; '{near[0]}' mı demek istediniz?", file=sys.stderr)
            return 2
        argv = ["mask", *argv]  # alt komutsuz kullanım: matriks-mask "metin" / matriks-mask --json "metin"
    if not argv or argv[0] not in _SUB:
        ap = argparse.ArgumentParser(prog="matriks-mask", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
        ap.add_argument("command", choices=_SUB)
        ap.add_argument("--version", action="version", version=_version())
        ap.parse_args(argv)  # yardım/sürüm/hata iletisi yazar ve çıkar
        return 2  # pragma: no cover
    cmd, rest = argv[0], argv[1:]
    if cmd == "mask":
        return _mask(rest)
    if cmd == "selftest":
        from .selftest import main as selftest_main

        return selftest_main(rest)
    from .keys import main as keys_main

    keys_main(rest)
    return 0


def _version() -> str:
    from . import __version__

    return __version__


if __name__ == "__main__":
    sys.exit(main())
