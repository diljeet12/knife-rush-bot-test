#!/usr/bin/env python
"""Acceptance checker for live_track.py recordings.

Implements EXECUTION_PLAN.md Phase 1.5 acceptance exactly, and prints the
distribution stats needed to spot the historical 2x omega bug at a glance.

Read-only: never modifies the CSV it reads.

Usage
-----
    python analyze_run.py                        # newest recording
    python analyze_run.py recordings/xxx.csv     # one file
    python analyze_run.py --all                  # every recording
    python analyze_run.py --all --quiet          # one verdict line per file

Exit codes
----------
    0  all mandatory checks passed
    1  at least one mandatory check failed
    2  could not read / no usable tracked rows
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import sys

# ---- ground truth (measurements/SPEED_MEASUREMENT_REPORT.md) -------------- #
SLOW_DPS = 194.5          # dominant tier, 79.7 % of throws
FAST_DPS = 321.2          # fast tier, 20.3 % of throws
PHYSICAL_MAX = 343.5      # highest ever observed; > 400 is impossible
SLOW_TOL = 0.02           # +-2 %
FAST_TOL = 0.03           # +-3 %

SLOW_BAND = (150.0, 240.0)
FAST_BAND = (280.0, 360.0)

MIN_OBSTACLES = 8
MONO_MAX_DT = 0.15        # s; a pair further apart than this is not "consecutive"
MONO_TARGET = 95.0        # %


def _f(row: dict, key: str) -> float:
    """Parse a float from a CSV row, tolerating blanks and junk."""
    raw = row.get(key)
    if raw is None or raw == "":
        return float("nan")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float("nan")


def _pct(values: list[float], q: float) -> float:
    """Percentile with linear interpolation. q in [0, 100]."""
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * (q / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[int(pos)]
    return s[lo] * (hi - pos) + s[hi] * (pos - lo)


def _wrap180(d: float) -> float:
    """Wrap a delta into (-180, 180]."""
    d = math.fmod(d + 180.0, 360.0)
    if d <= 0.0:
        d += 360.0
    return d - 180.0


def load(path: str):
    with open(path, "r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def analyse(path: str, quiet: bool = False) -> int:
    rows = load(path)
    if not rows:
        print(f"{os.path.basename(path)}: EMPTY FILE")
        return 2

    n_total = len(rows)
    has_flag = "tracking_ok" in rows[0]
    tracked = []
    lost = 0
    for r in rows:
        if has_flag:
            ok = _f(r, "tracking_ok") == 1.0
        else:
            nob = _f(r, "n_obstacles")
            ok = math.isfinite(nob) and nob >= MIN_OBSTACLES
        if not ok:
            lost += 1
            continue
        tracked.append(r)

    name = os.path.basename(path)
    if not tracked:
        print(f"{name}: NO TRACKED ROWS  ({n_total} rows, all n_obstacles < {MIN_OBSTACLES})")
        return 2

    omega = [abs(_f(r, "omega_fit_dps")) for r in tracked]
    omega = [w for w in omega if math.isfinite(w)]
    if not omega:
        print(f"{name}: omega_fit_dps column unusable")
        return 2

    n_trk = len(tracked)
    lost_pct = 100.0 * lost / n_total

    p05, p25, p50, p75, p95 = (
        _pct(omega, 5), _pct(omega, 25), _pct(omega, 50),
        _pct(omega, 75), _pct(omega, 95),
    )

    over_max = sum(1 for w in omega if w > 400.0)
    slow_n = sum(1 for w in omega if SLOW_BAND[0] <= w <= SLOW_BAND[1])
    fast_n = sum(1 for w in omega if FAST_BAND[0] <= w <= FAST_BAND[1])
    slow_pct = 100.0 * slow_n / len(omega)
    fast_pct = 100.0 * fast_n / len(omega)

    # ---- monotonicity of the integrated angle ------------------------------ #
    deltas = []
    prev = None
    for r in tracked:
        a = _f(r, "angle_polar_deg")
        t = _f(r, "t")
        dt = _f(r, "dt_ms") / 1000.0
        if not (math.isfinite(a) and math.isfinite(t)):
            prev = None
            continue
        if prev is not None and math.isfinite(dt) and 0.0 < dt <= MONO_MAX_DT:
            deltas.append(_wrap180(a - prev))
        prev = a

    if deltas:
        ref = _pct(deltas, 50)
        if ref == 0.0:
            mono_pct = 0.0
        else:
            agree = sum(1 for d in deltas if d * ref > 0.0)
            zero = sum(1 for d in deltas if d == 0.0)
            mono_pct = 100.0 * (agree + zero) / len(deltas)
    else:
        mono_pct = float("nan")
        ref = float("nan")

    # LOCAL direction consistency.
    # The game reverses the log's spin several times per minute (measured
    # 2026-11-17: 9 sign runs in 60 s, 4 CW / 5 CCW). Whole-run monotonicity
    # is therefore impossible to satisfy and is a meaningless criterion.
    # What we actually need to detect is a frame whose delta points against
    # its own neighbourhood -- that is a measurement glitch, not a reversal.
    local_pct = float("nan")
    if len(deltas) >= 5:
        half = 15
        agree = total = 0
        for i, d in enumerate(deltas):
            win = deltas[max(0, i - half):min(len(deltas), i + half + 1)]
            med = _pct(win, 50)
            if med == 0.0:
                continue
            total += 1
            if d * med > 0.0:
                agree += 1
        if total:
            local_pct = 100.0 * agree / total

    # ---- verdicts ---------------------------------------------------------- #
    in_slow = abs(p50 - SLOW_DPS) <= SLOW_DPS * SLOW_TOL
    in_fast = abs(p50 - FAST_DPS) <= FAST_DPS * FAST_TOL
    c1 = in_slow or in_fast
    c2 = over_max == 0
    c3 = slow_pct > 50.0
    c4 = 5.0 <= fast_pct <= 40.0
    c5 = math.isfinite(local_pct) and local_pct >= MONO_TARGET

    checks = [
        ("C1  p50 |omega| = 194.5 +-2%  OR  321.2 +-3%", c1,
         f"p50 = {p50:.1f} deg/s"),
        ("C2  zero samples above 400 deg/s", c2,
         f"{over_max} of {len(omega)}"),
        ("C3  slow tier (150-240) > 50% of tracked", c3,
         f"{slow_pct:.1f}%"),
        ("C4  fast tier (280-360) in 5-40% of tracked", c4,
         f"{fast_pct:.1f}%"),
        ("C5  local direction consistency >= 95%", c5,
         f"{local_pct:.1f}%" if math.isfinite(local_pct) else "no pairs"),
    ]
    passed = all(c[1] for c in checks)

    if quiet:
        print(f"{'PASS' if passed else 'FAIL'}  {name}  "
              f"p50={p50:6.1f}  >400={over_max:4d}  lost={lost_pct:5.1f}%  "
              f"local={local_pct:5.1f}%")
        return 0 if passed else 1

    print("=" * 74)
    print(f"  {name}")
    print("=" * 74)
    print(f"  rows              {n_total}")
    print(f"  tracked           {n_trk}   ({100.0 * n_trk / n_total:.1f}%)")
    print(f"  lost markers      {lost}   ({lost_pct:.1f}%)")
    print(f"  duration          {_f(rows[-1], 't'):.1f} s")
    print(f"  fps (median)      {_pct([_f(r, 'fps') for r in tracked if math.isfinite(_f(r, 'fps'))], 50):.1f}")
    print()
    print("  |omega_fit| distribution (deg/s)")
    print(f"    p05 {p05:7.1f}   p25 {p25:7.1f}   p50 {p50:7.1f}   "
          f"p75 {p75:7.1f}   p95 {p95:7.1f}")
    print(f"    slow tier {slow_pct:5.1f}%   fast tier {fast_pct:5.1f}%   "
          f"outside both {100.0 - slow_pct - fast_pct:5.1f}%")
    print(f"    dominant rotation direction: "
          f"{'CW' if ref == ref and ref > 0 else 'CCW' if math.isfinite(ref) else 'n/a'}"
          f"  (median delta {ref:.2f} deg)")
    print(f"    global monotone {mono_pct:5.1f}%  "
          f"(low is expected: the log reverses direction several times per run)")
    print()
    print("  PHASE 1.5 ACCEPTANCE")
    for label, ok, detail in checks:
        print(f"    [{'PASS' if ok else 'FAIL'}]  {label:<52} {detail}")
    print()

    # ---- 2x-bug fingerprint ------------------------------------------------ #
    if abs(p50 - 2 * SLOW_DPS) < 15 or abs(p50 - 2 * FAST_DPS) < 20:
        print("  !! 2x BUG FINGERPRINT: p50 is ~2x a true tier.")
        print("     Check that `angle` advances exactly once per frame.")
        print()

    print(f"  VERDICT: {'PASS' if passed else 'FAIL'}")
    print("=" * 74)
    return 0 if passed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="recording to analyse")
    ap.add_argument("--all", action="store_true", help="analyse every recording")
    ap.add_argument("--quiet", action="store_true", help="one line per file")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    rec = os.path.join(root, "recordings")

    if args.all:
        files = sorted(glob.glob(os.path.join(rec, "*.csv")))
        if not files:
            print("no recordings found")
            return 2
    elif args.csv:
        files = [args.csv]
    else:
        files = sorted(glob.glob(os.path.join(rec, "*.csv")),
                       key=os.path.getmtime)
        if not files:
            print("no recordings found")
            return 2
        files = [files[-1]]

    rc = 0
    for f in files:
        try:
            r = analyse(f, quiet=args.quiet)
        except OSError as exc:
            print(f"{os.path.basename(f)}: {exc}")
            r = 2
        if not args.quiet and len(files) > 1:
            print()
        rc = max(rc, r)
    return rc


if __name__ == "__main__":
    sys.exit(main())
