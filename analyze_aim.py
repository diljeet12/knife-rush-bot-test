"""Analyse a throws CSV: what actually predicts a hit, and how far off is the aim.

The point of this file is that "hit / miss" is a one-bit signal and cannot be
tuned against. `land=` and `aimerr=` are the continuous ground truth: where the
knife actually stuck, in degrees, against the impact line at 180.

Usage:
    python analyze_aim.py recordings/throws_XXXXXXXX.csv
"""
from __future__ import annotations

import csv
import math
import re
import statistics
import sys
from collections import Counter


def parse_detail(s: str) -> dict:
    out: dict = {}
    for key in ("hit", "pred_land", "land", "aimerr",
                "press_to_launch_ms", "slot_empty_ms", "press_to_reload_ms"):
        # The (?<!\w) guard stops `land=` from also matching inside
        # `pred_land=`. The \s* absorbs the numeric field padding, which can
        # sit before the sign as well: "{:+5.1f}".format(2.3) -> " +2.3".
        m = re.search(rf"(?<!\w){key}=\s*([-+]?\s*\d+(?:\.\d+)?)", s)
        if m:
            out[key] = float(m.group(1).replace(" ", ""))
    return out


def pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "n/a"


def bucket_report(title: str, pairs, edges) -> None:
    print(f"\n{title}")
    print(f"  {'band':>16s}  {'n':>4s}  {'hits':>4s}  {'rate':>7s}")
    for lo, hi in edges:
        sel = [int(h) for v, h in pairs if lo <= v < hi]
        if sel:
            print(f"  {f'{lo:>6.0f}-{hi:<6.0f}':>16s}  {len(sel):>4d}  "
                  f"{sum(sel):>4d}  {pct(sum(sel), len(sel)):>7s}")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    if not path:
        print("give a throws CSV")
        return 2

    rows = list(csv.DictReader(open(path)))
    landed = [r for r in rows if r["event"] in ("landed", "no_launch_seen")]
    scored = []
    for r in landed:
        d = parse_detail(r["detail"])
        if "hit" not in d:
            continue
        try:
            slack = float(r["slack"])
        except (TypeError, ValueError):
            slack = float("nan")
        try:
            omega = abs(float(r["omega"]))
        except (TypeError, ValueError):
            omega = float("nan")
        try:
            gap = float(r["gap_w"])
        except (TypeError, ValueError):
            gap = float("nan")
        scored.append({"hit": int(d["hit"]), **d, "slack": slack,
                       "omega": omega, "gap": gap})

    print(f"file: {path}")
    print(f"throw events: {sum(1 for r in rows if r['event'] == 'throw')}")
    print(f"landings scored: {len(scored)}  "
          f"hits {sum(s['hit'] for s in scored)}  "
          f"rate {pct(sum(s['hit'] for s in scored), len(scored))}")

    print("\nevents:", dict(Counter(r["event"] for r in rows)))

    both = [s for s in scored if s["hit"] and s.get("land") is not None]
    if both:
        errs = [s["aimerr"] for s in both]
        preds = [s["pred_land"] for s in both if s.get("pred_land") is not None
                 and not math.isnan(s["pred_land"])]
        print(f"\nlanded knives measured: {len(both)}")
        print(f"  aim error  mean {statistics.fmean(errs):+.1f} deg   "
              f"median {statistics.median(errs):+.1f}   "
              f"stdev {statistics.pstdev(errs):.1f}")
        print(f"  |aim error| mean {statistics.fmean(abs(e) for e in errs):.1f} deg   "
              f"max {max(abs(e) for e in errs):.1f}")
        if len(preds) > 2:
            print(f"  predicted landing mean {statistics.fmean(preds):+.1f} deg "
                  f"(ideal 180.0, stdev {statistics.pstdev(preds):.1f})")
        # bias vs spin speed tells us whether t_total is wrong
        for lo, hi in ((0, 140), (140, 200), (200, 260), (260, 400)):
            sel = [s["aimerr"] for s in both if lo <= s["omega"] < hi]
            if sel:
                print(f"  omega {lo:>3d}-{hi:<3d}: n={len(sel):>3d} "
                      f"mean err {statistics.fmean(sel):+6.1f} deg")
    else:
        print("\nno land= measurements yet -- run a newer build to collect them")

    ok = [s for s in scored if not math.isnan(s["slack"])]
    if ok:
        bucket_report("hit rate by predicted slack (margin at impact)",
                      [(s["slack"], s["hit"]) for s in ok],
                      [(-100, 0), (0, 8), (8, 12), (12, 16),
                       (16, 20), (20, 25), (25, 40)])
    ok2 = [s for s in scored if not math.isnan(s["omega"])]
    if ok2:
        bucket_report("hit rate by spin speed |omega| deg/s",
                      [(s["omega"], s["hit"]) for s in ok2],
                      [(0, 140), (140, 200), (200, 260), (260, 400)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
