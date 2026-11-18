#!/usr/bin/env python3
"""Time every stage of find_target() on saved screenshots.

Why this exists: the relocate loop costs ~200 ms per attempt, and I had
guessed *why* twice and been wrong twice. hough_candidates() already
downscales to 900 px, so the obvious theory is dead. This measures instead.

Run:  python bench_locate.py [--repeats 5] [paths...]
"""

from __future__ import annotations

import argparse
import glob
import os
import statistics as st
import time

import cv2

import live_track as lt


def _time(fn, repeats: int):
    """Median seconds per call, plus the value of the last call."""
    times, out = [], None
    for _ in range(repeats):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
    return st.median(times), out


def bench(path: str, repeats: int) -> dict:
    full = cv2.imread(path)
    name = os.path.basename(path)
    res = {"name": name, "shape": full.shape, "ok": False}

    if full is None:
        return res

    t_sky, _ = _time(lambda: lt.screen_sky_frac(full, downscale=4), repeats)
    t_hough, cands = _time(lambda: lt.hough_candidates(full), repeats)
    t_blob, blobs = _time(lambda: lt.auto_locate_candidates(full), repeats)

    t_refine = float("nan")
    if cands:
        c = cands[0]
        t_refine, _ = _time(lambda: lt.refine_circle(full, c[0], c[1], c[2]),
                            repeats)

    t_ann, ann = _time(lambda: lt.sky_annulus_frac(full, 960.0, 400.0, 125.6),
                       repeats)

    t_total, got = _time(lambda: lt.find_target(full, verbose=False), repeats)

    res.update(
        n_cands=len(cands or []),
        n_blobs=len(blobs or []),
        t_sky=t_sky, t_hough=t_hough, t_blob=t_blob, t_refine=t_refine,
        t_ann=t_ann, t_total=t_total, found=got, ann=ann,
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", default=None)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    paths = args.paths or sorted(glob.glob("temp/*.png"))
    # only full-screen grabs: find_target scans the whole monitor
    paths = [p for p in paths
             if cv2.imread(p) is not None
             and cv2.imread(p).shape[1] >= 1800
             and cv2.imread(p).shape[0] >= 1000]

    if not paths:
        print("no full-screen screenshots found (need ~1920x1080 pngs)")
        return 1

    print(f"{'file':<20} {'found':<6} {'total':>9} {'sky_ms':>8} "
          f"{'hough':>8} {'blob':>8} {'refine':>8} {'ann':>7} {'cnd':>4}")
    print("-" * 88)

    rows = []
    for p in paths:
        r = bench(p, args.repeats)
        rows.append(r)
        if "t_total" not in r:
            print(f"{r['name']:<20} unreadable")
            continue
        got = r["found"]
        found = ("yes" if got else "no")
        print(f"{r['name']:<20} {found:<6} "
              f"{1000*r['t_total']:7.1f}ms {1000*r['t_sky']:6.1f} "
              f"{1000*r['t_hough']:7.1f} {1000*r['t_blob']:7.1f} "
              f"{1000*r['t_refine']:7.1f} {1000*r['t_ann']:6.1f} "
              f"{r['n_cands']:4d}")
        if got:
            print(f"{'':<20} -> ({got[0]:.1f}, {got[1]:.1f}) r={got[2]:.1f}")

    # ---- where does the time actually go? ------------------------------- #
    ok = [r for r in rows if "t_total" in r]
    if ok:
        print("\n--- mean share of the measured stages ---")
        stage = {
            "screen_sky_frac": st.mean(r["t_sky"] for r in ok),
            "hough_candidates": st.mean(r["t_hough"] for r in ok),
            "auto_locate_candidates": st.mean(r["t_blob"] for r in ok),
            "refine_circle (1 cand)": st.mean(
                [r["t_refine"] for r in ok if r["t_refine"] == r["t_refine"]]
                or [0.0]),
        }
        total = sum(stage.values()) or 1.0
        for k, v in sorted(stage.items(), key=lambda kv: -kv[1]):
            print(f"  {k:<26} {1000*v:7.1f} ms   {100*v/total:5.1f}%")

        fails = [r for r in ok if not r["found"]]
        if fails:
            print(f"\n--- failure path (n={len(fails)}) ---")
            print(f"  mean total : "
                  f"{1000*st.mean(r['t_total'] for r in fails):.1f} ms")
        good = [r for r in ok if r["found"]]
        if good:
            print(f"\n--- success path (n={len(good)}) ---")
            print(f"  mean total : "
                  f"{1000*st.mean(r['t_total'] for r in good):.1f} ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
