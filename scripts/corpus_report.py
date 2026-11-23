"""Kalite raporu: varlık bazlı Precision / Recall / F1 / F2 ve CI eşik kontrolü.

    python scripts/corpus_report.py                 # detect + negative fixture'ları
    python scripts/corpus_report.py --external x.jsonl   # dış derlem: {"text": ..., "entities": [{"entity","value"}]}
    python scripts/corpus_report.py --markdown       # README için tablo
    python scripts/corpus_report.py --ner            # NER modu (`[ner]` extra): KISI eşiği F2 ≥ 0.96

Çıkış kodu 1: kalite eşiklerinden biri tutmadı.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matriks_pii.config import TurkishPIIConfig  # noqa: E402
from matriks_pii.engine import PIIEngine  # noqa: E402

DETERMINISTIC = {"TCKN", "VKN", "IBAN", "KART", "TELEFON", "EPOSTA", "IP", "PLAKA", "GIZLI_ANAHTAR", "KONUM"}
THRESHOLDS = {"deterministic_p": 1.0, "deterministic_r": 1.0, "KISI_f2": 0.92, "KISI_r": 0.90, "negative_fp": 0}


def f_beta(p: float, r: float, beta: float) -> float:
    if p == 0 and r == 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r)


def evaluate(cases: list[dict], engines: dict[str, PIIEngine], base: dict | None = None) -> tuple[dict[str, Counter], int, list[str]]:
    stats: dict[str, Counter] = defaultdict(Counter)
    fp_neg = 0
    errors: list[str] = []
    for c in cases:
        conf = {**(base or {}), **(c.get("config") or {})}
        key = json.dumps(conf, sort_keys=True)
        if key not in engines:
            engines[key] = PIIEngine(TurkishPIIConfig.build(conf))
        eng = engines[key]
        got = Counter((s.entity, s.text) for s in eng.detected(c["text"]))
        exp = Counter((e["entity"], e["value"]) for e in c.get("expect", c.get("entities", [])))
        for ent, val in got | exp:
            tp = min(got[(ent, val)], exp[(ent, val)])
            stats[ent]["tp"] += tp
            stats[ent]["fp"] += got[(ent, val)] - tp
            stats[ent]["fn"] += exp[(ent, val)] - tp
        if not exp and got:
            fp_neg += 1
        if got != exp:
            errors.append(c.get("id", "?"))
    return stats, fp_neg, errors


def table(stats: dict[str, Counter], markdown: bool) -> str:
    rows = []
    for ent in sorted(stats):
        s = stats[ent]
        p = s["tp"] / (s["tp"] + s["fp"]) if s["tp"] + s["fp"] else 1.0
        r = s["tp"] / (s["tp"] + s["fn"]) if s["tp"] + s["fn"] else 1.0
        rows.append((ent, s["tp"], s["fp"], s["fn"], p, r, f_beta(p, r, 1), f_beta(p, r, 2)))
    if markdown:
        out = ["| Varlık | TP | FP | FN | P | R | F1 | F2 |", "|---|---|---|---|---|---|---|---|"]
        out += [f"| {e} | {tp} | {fp} | {fn} | {p:.3f} | {r:.3f} | {f1:.3f} | {f2:.3f} |" for e, tp, fp, fn, p, r, f1, f2 in rows]
    else:
        out = [f"{'Varlık':<18}{'TP':>6}{'FP':>6}{'FN':>6}{'P':>8}{'R':>8}{'F1':>8}{'F2':>8}"]
        out += [f"{e:<18}{tp:>6}{fp:>6}{fn:>6}{p:>8.3f}{r:>8.3f}{f1:>8.3f}{f2:>8.3f}" for e, tp, fp, fn, p, r, f1, f2 in rows]
    return "\n".join(out)


def load_fixture_dir(sub: str) -> list[dict]:
    out: list[dict] = []
    for f in sorted((ROOT / "tests" / "fixtures" / sub).glob("*.yaml")):
        out.extend(yaml.safe_load(f.read_text(encoding="utf-8")) or [])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--external", help="JSONL: her satır {text, entities:[{entity,value}]}")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--ner", action="store_true", help="name_detection.ner_backend=hf ile ölç (KISI F2 eşiği 0.96)")
    a = ap.parse_args()
    base = {"name_detection": {"ner_backend": "hf"}} if a.ner else None
    kisi_f2 = 0.96 if a.ner else THRESHOLDS["KISI_f2"]
    engines: dict[str, PIIEngine] = {}
    if a.external:
        cases = [json.loads(x) for x in Path(a.external).read_text(encoding="utf-8").splitlines() if x.strip()]
        stats, _, _ = evaluate(cases, engines, base)
        print(table(stats, a.markdown))
        return 0
    det, neg = load_fixture_dir("detect"), load_fixture_dir("negative")
    stats, _, errs = evaluate(det, engines, base)
    _, fp_neg, neg_errs = evaluate(neg, engines, base)
    print(f"Pozitif/karışık senaryo: {len(det)}  Negatif senaryo: {len(neg)}")
    print(table(stats, a.markdown))
    print(f"\nNegatif sette yanlış pozitif içeren senaryo: {fp_neg}")
    ok = True
    for ent in DETERMINISTIC & set(stats):
        s = stats[ent]
        if s["fp"] or s["fn"]:
            ok = False
            print(f"EŞİK: {ent} deterministik ama FP={s['fp']} FN={s['fn']}")
    k = stats.get("KISI", Counter())
    if k:
        p = k["tp"] / max(1, k["tp"] + k["fp"])
        r = k["tp"] / max(1, k["tp"] + k["fn"])
        if f_beta(p, r, 2) < kisi_f2 or r < THRESHOLDS["KISI_r"]:
            ok = False
            print(f"EŞİK: KISI F2={f_beta(p, r, 2):.3f} R={r:.3f}")
    if fp_neg > THRESHOLDS["negative_fp"]:
        if a.ner:
            # negatif tuzaklar sözlük modu içindir (ör. NEG-329..335 gerçek yabancı adlar; NER'in amacı bunları yakalamak)
            print("NER modunda negatif set bilgi amaçlıdır; eşik yalnız sözlük modunda uygulanır.")
        else:
            ok = False
    if errs or neg_errs:
        print("Hatalı senaryolar:", ", ".join((errs + neg_errs)[:50]))
    print("SONUÇ:", "GEÇTİ" if ok else "KALDI")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
