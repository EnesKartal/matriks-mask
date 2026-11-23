"""Kurum/pazar/marka adları listesini (data/org_names_tr.txt) üretir.

Kaynaklar:
1. Elle derlenmiş liste: mevcut `org_names_tr.txt` içeriği (BIST pazar/endeks adları, kamu kurumları, bankalar,
   markalar, ülke ve tarihî kişi adları; bölüm yorumları korunur). Elle eklenen satırlar asla silinmez.
2. İsteğe bağlı KAP şirket unvanları: `scripts/_raw/kap_companies.txt` (satır başına bir unvan; kap.org.tr
   "Şirketler" sayfasından elle dışa aktarılır — sitenin otomatik taranması kullanım koşullarına takılabildiği için
   indirme yapılmaz). Unvandan hukuki ekler atılır ("A.Ş.", "SANAYİ VE TİCARET" ...) ve yalnız ilk 1–3 sözcüğünde
   bir ad/soyad geçen unvanlar eklenir (ör. "KOÇ HOLDİNG A.Ş." → "koç holding"); amaç kişi adı tanıyıcısının
   şirket unvanlarını kişi sanmasını önlemektir, tüm şirketleri listelemek değildir.

Kullanım: python scripts/build_org_names.py [--kap scripts/_raw/kap_companies.txt] [--check]
`--check`: dosyayı yazmaz; üretilecek içerik mevcut dosyadan farklıysa çıkış kodu 1 (CI için).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii import data  # noqa: E402
from matriks_pii.text_utils import fold_key, tr_lower  # noqa: E402

OUT = ROOT / "matriks_pii" / "data" / "org_names_tr.txt"
KAP_DEFAULT = ROOT / "scripts" / "_raw" / "kap_companies.txt"
KAP_HEADER = "# KAP şirket unvanları (build_org_names.py --kap ile üretilir)"

_LEGAL = re.compile(
    r"\b(?:t\.?\s?a\.?\s?ş\.?|a\.?\s?ş\.?|ltd\.?|şti\.?|limited|şirketi|anonim|sanayi|sanayii|ticaret|ve|tic\.?|san\.?|"
    r"yatırım ortaklığı|gayrimenkul|holding a\.?ş\.?)\b.*$"
)


def kap_titles_to_names(titles: list[str]) -> list[str]:
    firsts, lasts = data.first_names(), data.last_names()
    out: set[str] = set()
    for title in titles:
        t = " ".join(tr_lower(title).replace(",", " ").split())
        words = t.split()
        if not words:
            continue
        # "koç holding a.ş." → "koç holding"; "zorlu enerji elektrik üretim a.ş." → "zorlu enerji".
        # Tek sözcük asla eklenmez: "doğan" listeye girerse Doğan adı her yerde bastırılır.
        stem = _LEGAL.sub("", " ".join(words[:2])).strip()
        if len(stem.split()) < 2:
            continue
        w1, w2 = (fold_key(w) for w in stem.split()[:2])
        # ilk sözcük ad/soyad, ikincisi sektör sözcüğü olmalı ("kılıç deniz" bir kişi adı da olabilir → eklenmez)
        if (w1 in firsts or w1 in lasts) and w2 not in firsts and w2 not in lasts:
            out.add(stem)
    return sorted(out)


def build(kap: Path | None) -> str:
    lines = OUT.read_text(encoding="utf-8").splitlines()
    # mevcut otomatik KAP bölümü yeniden üretilir; elle bölümler aynen kalır
    if KAP_HEADER in lines:
        lines = lines[: lines.index(KAP_HEADER)]
    while lines and not lines[-1].strip():
        lines.pop()
    curated: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            curated.append(s)
            continue
        key = " ".join(tr_lower(s).split())
        if key not in seen:
            seen.add(key)
            curated.append(key)
    out = curated
    if kap is not None and kap.exists():
        titles = [t for t in kap.read_text(encoding="utf-8").splitlines() if t.strip()]
        extra = [n for n in kap_titles_to_names(titles) if n not in seen]
        if extra:
            out = curated + ["", KAP_HEADER] + extra
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kap", type=Path, default=KAP_DEFAULT)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = build(a.kap)
    current = OUT.read_text(encoding="utf-8")
    if a.check:
        sys.exit(0 if text == current else 1)
    OUT.write_text(text, encoding="utf-8")
    n = sum(1 for ln in text.splitlines() if ln and not ln.startswith("#"))
    print(f"{OUT.name}: {n} ifade" + ("" if a.kap.exists() else " (KAP listesi yok; yalnız elle derlenmiş liste)"))


if __name__ == "__main__":
    main()
