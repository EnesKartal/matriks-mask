"""mkozturk/trnames (MIT) CSV'lerinden ad/soyad sözlüklerini, FrequencyWords tr_50k'dan tr_words.txt'yi üretir.

Ad/soyad dosyaları yalnız trnames verisinden üretilir; sözcük listesiyle kesişim pakette tutulmaz.

CSV şeması: `name,quantile` / `lastname,quantile` (kümülatif olasılık, ASCII büyük harf).
Çıktı: ASCII katlanmış küçük harf, satır başına bir ad, sıralı.

Kullanım: python scripts/build_name_lists.py [--raw scripts/_raw] [--max-quantile-first 0.999] [--max-quantile-last 0.995]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "matriks_pii" / "data"

HEADER = "# Kaynak: github.com/mkozturk/trnames (MIT). ASCII katlanmış küçük harf. scripts/build_name_lists.py ile üretildi.\n"


def read_q(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if row:
                out.setdefault(row[0].strip().lower(), float(row[1]))
    return out


def read(path: Path, max_q: float) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if not row:
                continue
            name, q = row[0].strip().lower(), float(row[1])
            if q > max_q:
                break
            if len(name) >= 2 and name.isascii() and name.isalpha():
                out.append(name)
    return out


def _fold(s: str) -> str:
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return s.translate(str.maketrans("ıçğöşüâîû", "icgosuaiu"))


def words_ordered(path: Path, top: int) -> list[str]:
    seen: dict[str, None] = {}
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= top:
                break
            w = _fold(line.split()[0])
            if len(w) >= 2 and w.isalpha():
                seen.setdefault(w, None)
    return list(seen)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "scripts" / "_raw"))
    ap.add_argument("--max-quantile-first", type=float, default=0.999)
    ap.add_argument("--max-quantile-last", type=float, default=0.995)
    ap.add_argument("--rare-first", type=float, default=0.9, help="bu eşiğin üstü seyrek ad")
    ap.add_argument("--rare-last", type=float, default=0.8, help="bu eşiğin üstü seyrek soyad")
    ap.add_argument("--popular-first", type=float, default=0.8)
    ap.add_argument("--words-top", type=int, default=50000)
    a = ap.parse_args()
    raw = Path(a.raw)
    fq = read_q(raw / "male_first.csv")
    for k, v in read_q(raw / "female_first.csv").items():
        fq[k] = min(v, fq.get(k, 1.0))
    lq = read_q(raw / "all_last.csv")
    first_all = set(read(raw / "male_first.csv", a.max_quantile_first) + read(raw / "female_first.csv", a.max_quantile_first))
    last_all = set(read(raw / "all_last.csv", a.max_quantile_last))
    # Yalnız trnames'ten: tüm adlar/soyadlar ve "sık" olanlar (kümülatif olasılık eşiğinin altında kalanlar).
    # Seyrek olup aynı zamanda Türkçe sözcük olan adlar/soyadlar (Telefon, Arı, Sağlam) pakette dosya olarak
    # tutulmaz; matriks_pii/data/__init__.py bunları çalışma anında tr_words.txt ile hesaplar.
    first = sorted(first_all)
    last = sorted(last_all)
    frequent_first = sorted(n for n in first_all if fq.get(n, 1.0) <= a.rare_first)
    frequent_last = sorted(n for n in last_all if lq.get(n, 1.0) <= a.rare_last)
    (DATA / "frequent_first_names_tr.txt").write_text(HEADER + "\n".join(frequent_first) + "\n", encoding="utf-8")
    (DATA / "frequent_last_names_tr.txt").write_text(HEADER + "\n".join(frequent_last) + "\n", encoding="utf-8")
    popular = sorted(n for n, q in fq.items() if q <= a.popular_first)
    (DATA / "popular_first_names_tr.txt").write_text(HEADER + "\n".join(popular) + "\n", encoding="utf-8")
    hdr_w = (
        "# Kaynak: github.com/hermitdave/FrequencyWords tr_50k (Hermit Dave; OpenSubtitles 2018). "
        "Türkçe karakterler katlanmış, sıklık değerleri yok.\n"
        "# Lisans: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). "
        "Bu dosya proje Apache-2.0 lisansının dışındadır; THIRD_PARTY_NOTICES.md.\n"
    )
    (DATA / "tr_words.txt").write_text(hdr_w + "\n".join(words_ordered(raw / "tr_50k.txt", a.words_top)) + "\n", encoding="utf-8")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "first_names_tr.txt").write_text(HEADER + "\n".join(first) + "\n", encoding="utf-8")
    (DATA / "last_names_tr.txt").write_text(HEADER + "\n".join(last) + "\n", encoding="utf-8")
    print(f"first={len(first)} last={len(last)}")


if __name__ == "__main__":
    main()
