"""ubeydeozdmr/turkiye-api (MIT) 2025 veri setinden il/ilçe/mahalle/posta kodu sözlüğü üretir.

Girdi: scripts/_raw/{provinces,districts,neighborhoods}.json
  (https://raw.githubusercontent.com/ubeydeozdmr/turkiye-api/main/datasets/2025/<ad>.json)
Çıktı: matriks_pii/data/il_ilce_tr.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii.text_utils import fold_key  # noqa: E402

RAW = ROOT / "scripts" / "_raw"
DATA = ROOT / "matriks_pii" / "data"

# büyük şehirlerde mahalle adı olmayan ama adreste geçen yaygın semtler
SEMTLER = (
    "Levent Nişantaşı Alsancak Caddebostan Bağdat Etiler Maslak Taksim Bebek Ortaköy Moda Suadiye Göztepe Bostancı "
    "Kızılay Çankaya Bahçelievler Mecidiyeköy Şişli Karaköy Eminönü Sirkeci Kozyatağı Ataşehir Kavaklıdere Ümitköy "
    "Bornova Karşıyaka Konak Göztepe Balçova Nilüfer Osmangazi Lara Konyaaltı"
).split()


def main() -> None:
    provinces = json.loads((RAW / "provinces.json").read_text(encoding="utf-8"))
    districts = json.loads((RAW / "districts.json").read_text(encoding="utf-8"))
    neighborhoods = json.loads((RAW / "neighborhoods.json").read_text(encoding="utf-8"))
    by_pid: dict[int, dict] = {}
    for p in provinces:
        by_pid[p["id"]] = {"ad": p["name"], "plaka": p["id"], "ilceler": [], "posta_kodlari": set()}
    for d in districts:
        by_pid[d["provinceId"]]["ilceler"].append(d["name"])
    mahalleler: set[str] = set()
    for n in neighborhoods:
        pc = n.get("postalCode")
        if pc and len(pc) == 5 and pc.isdigit():
            by_pid[n["provinceId"]]["posta_kodlari"].add(pc)
        name = n["name"]
        mahalleler.add(name)
    iller = []
    for pid in sorted(by_pid):
        p = by_pid[pid]
        iller.append(
            {
                "ad": p["ad"],
                "plaka": p["plaka"],
                "ilceler": sorted(set(p["ilceler"])),
                "posta_kodlari": sorted(p["posta_kodlari"]),
            }
        )
    out = {
        "kaynak": "github.com/ubeydeozdmr/turkiye-api datasets/2025 (MIT)",
        "surum": "2025",
        "iller": iller,
        "mahalleler": sorted({fold_key(m) for m in mahalleler}),
        "semtler": sorted(set(SEMTLER)),
    }
    (DATA / "il_ilce_tr.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"il={len(iller)} ilce={sum(len(i['ilceler']) for i in iller)} mahalle={len(out['mahalleler'])} "
          f"posta={sum(len(i['posta_kodlari']) for i in iller)}")


if __name__ == "__main__":
    main()
