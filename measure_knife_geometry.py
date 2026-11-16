#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_knife_geometry.py
=========================
Measure the ANGLULAR geometry of the target: how wide a stuck knife really is,
and how big the free gaps are once a level is busy.

WHY THIS MATTERS
----------------
The whole feasibility of the bot rests on one number:

    safe_window = (gap_width - knife_width) / omega

Every degree of knife width you over-estimate costs you milliseconds of window.
Earlier planning assumed a 16 deg knife. That assumption was never measured.

METHOD
------
Sample an annulus OUTSIDE the target -- r in [1.12R, 1.45R]. In that ring there
is nothing but sky and the objects sticking out of the target (knife blades,
handles, apples). The background is blue-dominant; every obstacle is not.

    is_background = (B > R + 25) and (B > 90)

This is appearance-independent: it works on the wooden target AND on the red
bullseye variant, because it never looks at the target itself.

Angular width is then scaled back to the impact radius r = R, since a radial
object subtends a WIDER angle closer to the centre.

Everything stays on the project drive.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_LOCAL_CACHE = os.path.join(_PROJECT_ROOT, ".cache")
_LOCAL_TEMP = os.path.join(_PROJECT_ROOT, "temp")
for _p in (os.path.join(_LOCAL_CACHE, "matplotlib"), _LOCAL_TEMP):
    os.makedirs(_p, exist_ok=True)
os.environ["MPLCONFIGDIR"] = os.path.join(_LOCAL_CACHE, "matplotlib")
os.environ["TEMP"] = _LOCAL_TEMP
os.environ["TMP"] = _LOCAL_TEMP

import cv2                                                    # noqa: E402
import numpy as np                                            # noqa: E402

from find_speed import detect_target                          # noqa: E402

N_THETA = 1440          # 0.25 deg per bin
RING_IN = 1.12
RING_OUT = 1.45
MIN_RUN_DEG = 1.5       # anything narrower is speckle, not an object
MAX_OBJ_DEG = 60.0      # wider than this = the scan failed, not a knife


def polar(f: np.ndarray, cx: float, cy: float, rin: float, rout: float):
    th = np.arange(N_THETA) * (2.0 * math.pi / N_THETA)
    rr = np.linspace(rin, rout, 24)
    mx = (cx + rr[None, :] * np.cos(th)[:, None]).astype(np.float32)
    my = (cy + rr[None, :] * np.sin(th)[:, None]).astype(np.float32)
    p = cv2.remap(f, mx, my, cv2.INTER_LINEAR,
                  borderMode=cv2.BORDER_REPLICATE).astype(np.int16)
    b, g, r = p[:, :, 0], p[:, :, 1], p[:, :, 2]
    background = (b > r + 25) & (b > 90)
    return (~background).mean(axis=1) > 0.5          # bool[N_THETA]


def runs_of(occ: np.ndarray, min_deg: float):
    """Return [(start_deg, width_deg), ...] for each contiguous occupied run."""
    n = len(occ)
    d = np.diff(np.r_[int(occ[-1]), occ.astype(int), int(occ[0])])
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    out = []
    for s, e in zip(starts, ends):
        w = ((e - s) % n) * (360.0 / n)
        if w >= min_deg:
            out.append((s * 360.0 / n, w))
    return out


def gaps_of(occ: np.ndarray, min_deg: float):
    n = len(occ)
    d = np.diff(np.r_[int(occ[-1]), occ.astype(int), int(occ[0])])
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    out = []
    for e, s in zip(ends[:-1], starts[1:]):
        w = ((s - e) % n) * (360.0 / n)
        if w >= min_deg:
            out.append((e * 360.0 / n, w))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="gameplay1.mp4")
    ap.add_argument("--outdir", default="measurements")
    ap.add_argument("--stride", type=int, default=12,
                    help="sample every Nth frame")
    ap.add_argument("--frames", type=int, nargs="*", default=None,
                    help="explicit frame list instead of stride")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # locate the target once
    cx = cy = R = None
    for i in np.linspace(0, total - 2, 25).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if not ok:
            continue
        got = detect_target(f)
        if got:
            cx, cy, R = got
            break
    if cx is None:
        print("ERROR: target not found")
        return 2
    print(f"target: centre ({cx:.2f}, {cy:.2f})  radius {R:.2f} px")

    idxs = args.frames if args.frames else list(range(0, total, args.stride))
    rows = []
    widths_at_R, all_gaps = [], []
    overlay_drawn = False

    for i in idxs:
        if i >= total:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if not ok:
            continue

        occ = polar(f, cx, cy, R * RING_IN, R * RING_OUT)
        obs = runs_of(occ, MIN_RUN_DEG)
        gaps = gaps_of(occ, MIN_RUN_DEG)
        if len(obs) < 3:
            continue
        # A single object cannot span a large fraction of the ring. If one does,
        # the background test failed for this frame (target absent, transition,
        # or the ring landed on terrain). Reject the whole frame rather than let
        # one bad bin destroy the statistics.
        if max(w for _, w in obs) > MAX_OBJ_DEG:
            continue

        r_mean = R * 0.5 * (RING_IN + RING_OUT)
        scale = r_mean / R                      # angle widens as radius shrinks
        widths_R = [w * scale for _, w in obs]
        widths_at_R.extend(widths_R)
        all_gaps.extend(w for _, w in gaps)

        rows.append({
            "frame": i,
            "n_obstacles": len(obs),
            "widths_deg_at_R": ";".join(f"{w:.2f}" for w in sorted(widths_R)),
            "gaps_deg": ";".join(f"{w:.2f}" for w in sorted(g for _, g in gaps)),
            "max_gap_deg": max((g for _, g in gaps), default=0.0),
        })

        if not overlay_drawn and len(obs) >= 8:
            vis = f.copy()
            cv2.circle(vis, (int(round(cx)), int(round(cy))),
                       int(round(R)), (0, 255, 0), 2)
            cv2.circle(vis, (int(round(cx)), int(round(cy))),
                       int(round(R * RING_IN)), (255, 200, 0), 1)
            cv2.circle(vis, (int(round(cx)), int(round(cy))),
                       int(round(R * RING_OUT)), (255, 200, 0), 1)
            for a, w in obs:
                mid = math.radians(a + w / 2.0)
                rr = (RING_IN + RING_OUT) * 0.5 * R
                p1 = (int(cx + R * RING_IN * math.cos(mid)),
                      int(cy + R * RING_IN * math.sin(mid)))
                p2 = (int(cx + R * RING_OUT * math.cos(mid)),
                      int(cy + R * RING_OUT * math.sin(mid)))
                cv2.line(vis, p1, p2, (0, 0, 255), 2)
            for a, w in gaps:
                mid = math.radians(a + w / 2.0)
                rr = R * RING_OUT * 1.08
                p = (int(cx + rr * math.cos(mid)), int(cy + rr * math.sin(mid)))
                cv2.putText(vis, f"{w:.0f}", p, cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 255, 255), 1)
            cv2.putText(vis, f"knife width at R ~ {np.median([w for w in widths_R]):.2f} deg",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 3)
            cv2.putText(vis, f"knife width at R ~ {np.median([w for w in widths_R]):.2f} deg",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)
            cv2.imwrite(os.path.join(args.outdir, "knife_scan_overlay.png"), vis)
            overlay_drawn = True

    cap.release()

    if not rows:
        print("ERROR: nothing measured")
        return 2

    path = os.path.join(args.outdir, "knife_geometry.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(f"[out] {path}  ({len(rows)} frames)")

    w = np.asarray(widths_at_R)
    g = np.asarray(all_gaps)
    print("\n=== KNIFE ANGULAR WIDTH, scaled to impact radius r = R ===")
    print(f"  samples   : {len(w)}")
    print(f"  median    : {np.median(w):.2f} deg")
    print(f"  p10 / p90 : {np.percentile(w, 10):.2f} / {np.percentile(w, 90):.2f} deg")
    print(f"  min / max : {w.min():.2f} / {w.max():.2f} deg")
    print("\n(hint: values near the median are lone knives; the ~2x ones are apples)")

    print("\n=== FREE GAP WIDTHS ===")
    for q in (10, 25, 50, 75, 90, 99):
        print(f"  p{q:<3}  {np.percentile(g, q):6.2f} deg")

    print("\n=== SAFE WINDOW, using median knife width and the widest gap per frame ===")
    kw = float(np.median(w))
    for om in (194.5, 321.2):
        print(f"\n  omega = {om:.1f} deg/s  ({om / 360:.3f} rev/s)")
        for gap in (16, 20, 30, 38, 50, 72):
            win = (gap - kw) / om * 1000.0
            frames = win / (1000.0 / 60.0)
            print(f"    gap {gap:2d} deg -> {win:6.1f} ms  ({frames:4.1f} frames @60Hz)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
