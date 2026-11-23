"""Sözlük üretimi için ham kaynakları scripts/_raw/ altına indirir (yalnız geliştirme; kurulumda gerekmez).

    python scripts/fetch_raw.py
    python scripts/build_name_lists.py && python scripts/build_common_words.py && python scripts/build_geo.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parent / "_raw"
SOURCES = {
    # mkozturk/trnames (MIT) — ad/soyad ve kümülatif olasılık
    "male_first.csv": "https://raw.githubusercontent.com/mkozturk/trnames/main/trnames/male_first.csv",
    "female_first.csv": "https://raw.githubusercontent.com/mkozturk/trnames/main/trnames/female_first.csv",
    "all_last.csv": "https://raw.githubusercontent.com/mkozturk/trnames/main/trnames/all_last.csv",
    "LICENSE_trnames": "https://raw.githubusercontent.com/mkozturk/trnames/main/LICENSE",
    # hermitdave/FrequencyWords (kod MIT, veri CC BY-SA 4.0) — Türkçe sözcük sıklığı
    "tr_50k.txt": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/tr/tr_50k.txt",
    # ubeydeozdmr/turkiye-api (MIT) — il/ilçe/mahalle/posta kodu (2025)
    "provinces.json": "https://raw.githubusercontent.com/ubeydeozdmr/turkiye-api/main/datasets/2025/provinces.json",
    "districts.json": "https://raw.githubusercontent.com/ubeydeozdmr/turkiye-api/main/datasets/2025/districts.json",
    "neighborhoods.json": "https://raw.githubusercontent.com/ubeydeozdmr/turkiye-api/main/datasets/2025/neighborhoods.json",
    "LICENSE_turkiye_api": "https://raw.githubusercontent.com/ubeydeozdmr/turkiye-api/main/LICENSE",
}


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        dest = RAW / name
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - sabit, güvenilir kaynak
            dest.write_bytes(r.read())
        print(f"{name}: {dest.stat().st_size} bayt")


if __name__ == "__main__":
    main()
