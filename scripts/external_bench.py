"""Dış (üçüncü taraf) Türkçe PII veri setleriyle ölçüm.

Veri setleri (indirme: `python scripts/external_bench.py --download`):
* Werea-co/Werea-KVKK-Bench `pii_synthetic.jsonl` (Apache-2.0, 2.400 satır, karakter offset'li etiketler)
* cagrigungor/turkish-pii-masking-benchmark `benchmark_1000.csv` (CC0, 1.000 satır, metindeki tüm etiketler)

Değerlendirme talimattan bağımsızdır (guardrail kullanıcının "şunu maskeleme" talimatını okumaz): altın etiket
olarak metinde geçen TÜM kişisel veri türleri alınır. Kapsam dışı türler (uyruk, kredi notu, maaş, kullanıcı adı...)
ayrıca raporlanır, P/R hesabına girmez. Varsayılan profil `strict` (tüm KVKK m.6 kategorileri maskelenir).

    python scripts/external_bench.py [--profile strict|balanced] [--markdown]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii.config import TurkishPIIConfig  # noqa: E402
from matriks_pii.engine import PIIEngine  # noqa: E402

EXT = ROOT / "scripts" / "_raw" / "external"
SOURCES = {
    "werea_pii_synthetic.jsonl": "https://huggingface.co/datasets/Werea-co/Werea-KVKK-Bench/resolve/main/pii_synthetic.jsonl",
    "pii_masking_benchmark_1000.csv": "https://huggingface.co/datasets/cagrigungor/turkish-pii-masking-benchmark/resolve/main/benchmark_1000.csv",
}

WEREA_MAP = {
    "PERSON": "KISI", "EMAIL": "EPOSTA", "PHONE_TR": "TELEFON", "ADDRESS": "ADRES", "TCKN": "TCKN", "PASSPORT_TR": "PASAPORT",
    "IBAN_TR": "IBAN", "CREDIT_CARD": "KART", "IPV4": "IP", "VEHICLE_PLATE_TR": "PLAKA", "DATE_OF_BIRTH": "DOGUM_TARIHI",
    "HEALTH_DATA": "OZEL_SAGLIK", "BIOMETRIC_DATA": "OZEL_BIYOMETRIK", "GENETIC_DATA": "OZEL_GENETIK",
    "CRIMINAL_CONVICTION_SECURITY": "OZEL_CEZA", "POLITICAL_OPINION": "OZEL_SIYASI", "RELIGION": "OZEL_DIN",
    "UNION_MEMBERSHIP": "OZEL_UYELIK", "SEXUAL_LIFE": "OZEL_CINSEL",
    # kapsam dışı: DEVICE_ID, FINANCIAL_DATA, LOCATION
}
MASKING_MAP = {
    "AD": "KISI", "ANNE_ADI": "KISI", "BABA_ADI": "KISI", "ANNE_KIZLIK": "KISI", "TCKN": "TCKN", "KART": "KART",
    "EMAIL": "EPOSTA", "PASAPORT_NO": "PASAPORT", "TEL": "TELEFON", "DOGUM_TARIHI": "DOGUM_TARIHI",
    "MUSTERI_NO": "MUSTERI_NO", "ADRES": "ADRES", "PLAKA": "PLAKA", "SASI_NO": "SASI_NO", "IBAN": "IBAN",
    "IP_ADRES": "IP", "MAC_ADRES": "MAC", "KART_SKT": "KART_SKT", "KAN_GRUBU": "OZEL_SAGLIK",
    "KRIPTO_CUZDAN": "KRIPTO_CUZDAN", "SIFRE": "SIFRE", "PIN": "SIFRE", "CVV": "KART_CVV", "SGK_NO": "SGK",
    "CEZA_KAYDI": "OZEL_CEZA", "HESAP_NO": "HESAP_NO", "EHLIYET_NO": "EHLIYET", "ENGEL_DURUMU": "OZEL_SAGLIK",
    "SAGLIK": "OZEL_SAGLIK", "BIYOMETRIK": "OZEL_BIYOMETRIK", "ETNIK_KOKEN": "OZEL_ETNIK", "DIN": "OZEL_DIN",
    "SENDIKA": "OZEL_UYELIK", "IMEI": "IMEI", "DOGUM_YERI": "DOGUM_YERI", "VERGI_NO": "VKN", "POLICE_NO": "POLICE_NO",
    "KONUM": "KONUM",  # bu veri setinde koordinat (cihaz/müşteri kaydı)
    # kapsam dışı: UYRUK, KREDI_NOTU, KULLANICI_ADI, MAAS, CINSIYET, YAS, IMZA, REFERANS, ISYERI,
    # MOTOR_NO, RUHSAT_NO, SOZLESME_NO, CIHAZ_ID, AILE, SICIL_NO
}


def download() -> None:
    EXT.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - sabit, bilinen kaynak
            (EXT / name).write_bytes(r.read())
        print("indirildi:", name)


def _prf(s: Counter) -> tuple[float, float, float]:
    p = s["tp"] / (s["tp"] + s["fp"]) if s["tp"] + s["fp"] else 1.0
    r = s["tp"] / (s["tp"] + s["fn"]) if s["tp"] + s["fn"] else 1.0
    f2 = 5 * p * r / (4 * p + r) if p + r else 0.0
    return p, r, f2


def werea(eng: PIIEngine) -> tuple[dict[str, Counter], int]:
    """Span örtüşmesine göre: altın span ile aynı türde örtüşen tespit = TP."""
    st: dict[str, Counter] = defaultdict(Counter)
    out_of_scope = 0
    for line in (EXT / "werea_pii_synthetic.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        got = [s for s in eng.detected(d["text"]) if eng.cfg.action(s.entity) in ("MASK", "BLOCK")]
        used = set()
        for g in d["entities"]:
            ent = WEREA_MAP.get(g["label"])
            if ent is None:
                out_of_scope += 1
                continue
            hit = next((i for i, s in enumerate(got) if i not in used and s.entity == ent
                        and s.start < g["end"] and g["start"] < s.end), None)
            if hit is None:
                st[ent]["fn"] += 1
            else:
                used.add(hit)
                st[ent]["tp"] += 1
        for i, s in enumerate(got):
            if i not in used:
                st[s.entity]["fp"] += 1
    return st, out_of_scope


def masking_bench(eng: PIIEngine) -> tuple[dict[str, Counter], int, int, int]:
    """Satır bazında tür sayıları: metindeki tüm etiketler (kapsam içi) ↔ tespit edilen türler."""
    st: dict[str, Counter] = defaultdict(Counter)
    oos = rows_exact = n_rows = 0
    with (EXT / "pii_masking_benchmark_1000.csv").open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            n_rows += 1
            # "metindeki_etiketler" tür KÜMESİDİR (aynı türden iki kişi tek [AD] olarak yazılır) → satır bazında küme karşılaştırması
            gold: set[str] = set()
            for t in re.findall(r"\[([A-Z_]+)\]", r["metindeki_etiketler"]):
                ent = MASKING_MAP.get(t)
                if ent is None:
                    oos += 1
                else:
                    gold.add(ent)
            got = {s.entity for s in eng.detected(r["input"]) if eng.cfg.action(s.entity) in ("MASK", "BLOCK")}
            if "OZEL_CEZA_GENIS" in got and "OZEL_CEZA" in gold:  # bizde ceza alt türü
                got = (got - {"OZEL_CEZA_GENIS"}) | {"OZEL_CEZA"}
            for ent in gold | got:
                if ent in gold and ent in got:
                    st[ent]["tp"] += 1
                elif ent in got:
                    st[ent]["fp"] += 1
                else:
                    st[ent]["fn"] += 1
            rows_exact += int(gold == got)
    return st, oos, rows_exact, n_rows


def table(st: dict[str, Counter], md: bool) -> str:
    lines = ["| Varlık | TP | FP | FN | P | R | F2 |", "|---|---|---|---|---|---|---|"] if md else [
        f"{'Varlık':<18}{'TP':>6}{'FP':>6}{'FN':>6}{'P':>8}{'R':>8}{'F2':>8}"]
    tot: Counter = Counter()
    for ent in sorted(st):
        s = st[ent]
        tot.update(s)
        p, r, f2 = _prf(s)
        lines.append(f"| {ent} | {s['tp']} | {s['fp']} | {s['fn']} | {p:.3f} | {r:.3f} | {f2:.3f} |" if md else
                     f"{ent:<18}{s['tp']:>6}{s['fp']:>6}{s['fn']:>6}{p:>8.3f}{r:>8.3f}{f2:>8.3f}")
    p, r, f2 = _prf(tot)
    lines.append(f"| **Toplam (mikro)** | {tot['tp']} | {tot['fp']} | {tot['fn']} | {p:.3f} | {r:.3f} | {f2:.3f} |" if md else
                 f"{'TOPLAM':<18}{tot['tp']:>6}{tot['fp']:>6}{tot['fn']:>6}{p:>8.3f}{r:>8.3f}{f2:>8.3f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--profile", default="strict")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    if a.download or not all((EXT / n).exists() for n in SOURCES):
        download()
    eng = PIIEngine(TurkishPIIConfig.build({"profile": a.profile}))
    st, oos = werea(eng)
    print(f"## Werea-KVKK-Bench pii_synthetic (2.400 satır; kapsam dışı etiket: {oos})\n")
    print(table(st, a.markdown))
    st2, oos2, exact, n = masking_bench(eng)
    print(f"\n## turkish-pii-masking-benchmark (1.000 satır; kapsam dışı etiket: {oos2}; tür çoklu kümesi tam eşleşen satır: {exact}/{n})\n")
    print(table(st2, a.markdown))


if __name__ == "__main__":
    main()
