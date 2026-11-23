"""Kademeli yayın kapı raporu: denetim izinden (audit JSONL, değersiz) gölge mod ve canary aşamalarını değerlendirir.

Operasyonel kapılar (CHANGELOG "Kademeli yayın", docs/RUNBOOK.md):
  1. gölge mod (dry_run): would_mask / would_block sayımları beklentiyle uyumlu, guardrail hatası yok
  2. canary: oturum kaybı oranı ≤ %1, guardrail hatası yok, KISI oranı gölge moda göre ±%15 içinde

Kullanım:
  python scripts/rollout_report.py audit/*.jsonl                       # tek dönem özeti
  python scripts/rollout_report.py canary/*.jsonl --baseline shadow/*.jsonl --max-change 0.15
  python scripts/rollout_report.py audit/*.jsonl --expect beklenen.json   # {"KISI": 120, "TCKN": 40, ...}
  --guardrail AD (filtre), --json (makine okunur), çıkış kodu: kapı ihlalinde 1.

Rapor yalnız sayım içerir; denetim izinde zaten değer yoktur.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Period:
    requests: int = 0
    dry_run: int = 0
    live: int = 0
    counts: Counter[str] = field(default_factory=Counter)  # gölge: would_mask, canlı: entities
    logged: Counter[str] = field(default_factory=Counter)
    blocked: Counter[str] = field(default_factory=Counter)
    failures: int = 0
    post_calls: int = 0
    session_missing: int = 0
    durations: list[float] = field(default_factory=list)
    keys: Counter[str] = field(default_factory=Counter)

    def rate(self, ent: str) -> float:
        return self.counts[ent] / self.requests if self.requests else 0.0

    def p95(self) -> float:
        if not self.durations:
            return 0.0
        d = sorted(self.durations)
        return d[min(len(d) - 1, int(0.95 * len(d)))]


def load(paths: list[str], guardrail: str | None = None) -> Period:
    p = Period()
    files = sorted({f for pat in paths for f in (glob.glob(pat) or [pat])})
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r: dict[str, Any] = json.loads(line)
                if guardrail and r.get("guardrail") != guardrail:
                    continue
                ev = r.get("event", "pre_call")
                if r.get("session_missing"):
                    p.session_missing += 1
                if ev.startswith("post_call"):
                    p.post_calls += 1
                if r.get("status") == "guardrail_failed_to_respond" and not r.get("session_missing"):
                    p.failures += 1
                if ev != "pre_call":
                    continue
                p.requests += 1
                p.keys[r.get("api_key_hash") or "-"] += 1
                p.durations.append(float(r.get("duration_ms") or 0.0))
                p.logged.update(r.get("logged") or {})
                if r.get("dry_run"):
                    p.dry_run += 1
                    p.counts.update(r.get("would_mask") or {})
                    if r.get("would_block"):
                        p.blocked[r["would_block"]] += 1
                else:
                    p.live += 1
                    p.counts.update(r.get("entities") or {})
                    if r.get("blocked"):
                        p.blocked[r["blocked"]] += 1
    return p


def evaluate(cur: Period, base: Period | None, expect: dict[str, int] | None, max_change: float,
             max_missing: float) -> list[str]:
    """Kapı ihlallerini döndürür (boş liste = geçti)."""
    bad: list[str] = []
    if cur.requests == 0:
        bad.append("denetim izinde pre_call kaydı yok")
    if cur.failures:
        bad.append(f"guardrail hatası: {cur.failures}")
    if cur.post_calls and cur.session_missing / cur.post_calls > max_missing:
        bad.append(f"oturum kaybı oranı {cur.session_missing / cur.post_calls:.3%} > {max_missing:.1%}")
    if expect is not None:
        for ent in sorted(set(expect) | set(cur.counts)):
            if cur.counts[ent] != expect.get(ent, 0):
                bad.append(f"{ent}: beklenen {expect.get(ent, 0)}, görülen {cur.counts[ent]}")
    if base is not None and base.requests:
        for ent in sorted(set(base.counts) | set(cur.counts)):
            b, c = base.rate(ent), cur.rate(ent)
            if ent == "KISI" or base.counts[ent] >= 20:  # az örnekli varlıklarda oran gürültülüdür
                change = abs(c - b) / b if b else (1.0 if c else 0.0)
                if change > max_change:
                    bad.append(f"{ent} istek başına oran {b:.3f} → {c:.3f} (değişim {change:.1%} > {max_change:.0%})")
    return bad


def summary(p: Period) -> dict[str, Any]:
    return {
        "requests": p.requests, "dry_run": p.dry_run, "live": p.live, "post_calls": p.post_calls,
        "session_missing": p.session_missing, "failures": p.failures, "p95_ms": round(p.p95(), 3),
        "api_keys": len(p.keys), "counts": dict(sorted(p.counts.items())), "logged": dict(sorted(p.logged.items())),
        "blocked": dict(sorted(p.blocked.items())),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--baseline", nargs="*")
    ap.add_argument("--expect")
    ap.add_argument("--guardrail")
    ap.add_argument("--max-change", type=float, default=0.15)
    ap.add_argument("--max-session-missing", type=float, default=0.01)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cur = load(a.paths, a.guardrail)
    base = load(a.baseline, a.guardrail) if a.baseline else None
    expect = json.load(open(a.expect, encoding="utf-8")) if a.expect else None
    bad = evaluate(cur, base, expect, a.max_change, a.max_session_missing)
    if a.json:
        print(json.dumps({"current": summary(cur), "baseline": summary(base) if base else None, "violations": bad},
                         ensure_ascii=False, indent=2))
    else:
        s = summary(cur)
        print(f"istek {s['requests']} (gölge {s['dry_run']}, canlı {s['live']}), post_call {s['post_calls']}, "
              f"oturum kaybı {s['session_missing']}, hata {s['failures']}, p95 {s['p95_ms']} ms, anahtar {s['api_keys']}")
        print(f"{'varlık':<18}{'sayı':>8}{'istek başına':>14}" + (f"{'taban':>10}" if base else ""))
        for ent in sorted(set(cur.counts) | (set(base.counts) if base else set())):
            row = f"{ent:<18}{cur.counts[ent]:>8}{cur.rate(ent):>14.3f}"
            print(row + (f"{base.rate(ent):>10.3f}" if base else ""))
        if s["logged"]:
            print("LOG (maskelenmeyen özel nitelikli):", s["logged"])
        if s["blocked"]:
            print("BLOCK:", s["blocked"])
        print("SONUÇ:", "GEÇTİ" if not bad else "KALDI")
        for b in bad:
            print("  -", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
