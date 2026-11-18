#!/usr/bin/env python3
"""Prove, on real pixels, that the mss capture box contains what it must.

Reads a saved 1920x1080 screenshot, finds the target exactly the way the live
program does, rebuilds the capture box from the same roi_for() call, and then
checks every geometric claim instead of asserting it:

  * is the target circle fully inside the box, with how much margin?
  * is the waiting-knife slot fully inside the box?
  * is anything measured (the 0.55R-1.42R bands) cut off by the box edge?

Also writes an annotated PNG so the result can be looked at, not just read.

Run:  python verify_capture_area.py temp/scan_now3.png
"""

from __future__ import annotations

import argparse
import json
import os

import cv2
import numpy as np

import live_track as lt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", nargs="?", default="temp/scan_now3.png")
    ap.add_argument("--out", default="temp/area_check.png")
    args = ap.parse_args()

    full = cv2.imread(args.image)
    if full is None:
        print(f"cannot read {args.image}")
        return 1
    sh, sw = full.shape[:2]

    got = lt.find_target(full, verbose=False)
    if got is None:
        print(f"{args.image}: no target found, cannot verify")
        return 1
    cx, cy, r = got

    cal_path = "measurements/calibration.json"
    cal = json.load(open(cal_path, encoding="utf-8")) if os.path.exists(cal_path) else {}

    bbox = lt.roi_for(cx, cy, r, sw, sh, 1.60, 1.60, 3.05)
    left, top = bbox["left"], bbox["top"]
    bw, bh = bbox["width"], bbox["height"]

    print(f"image            : {args.image}  ({sw}x{sh})")
    print(f"target found     : ({cx:.1f}, {cy:.1f})  r={r:.1f}")
    if cal:
        print(f"calibration.json : ({cal.get('cx', 0):.1f}, {cal.get('cy', 0):.1f}) "
              f"r={cal.get('r', 0):.1f}   taken {cal.get('taken', '?')}")
        print(f"  delta vs now   : dx={cx - cal.get('cx', cx):+.1f}  "
              f"dy={cy - cal.get('cy', cy):+.1f}  dr={r - cal.get('r', r):+.1f}")
    print()
    print(f"capture box      : {bw} x {bh} at ({left}, {top})")
    print(f"  -> {bw * bh} px = {100 * bw * bh / (sw * sh):.2f}% of screen")
    print()

    # ---- margins, in pixels and in R ------------------------------------ #
    def row(label: str, margin_px: float, need_px: float) -> None:
        ok = "OK  " if margin_px >= 0 else "FAIL"
        print(f"  {ok} {label:<26} margin {margin_px:7.1f} px "
              f"({margin_px / r:+6.2f} R)   need >= {need_px:.0f} px")

    print("geometry checks (everything is a multiple of R):")
    row("target left edge inside", cx - r - left, 0)
    row("target right edge inside", (left + bw) - (cx + r), 0)
    row("target top edge inside", cy - r - top, 0)
    row("target bottom edge inside", (top + bh) - (cy + r), 0)

    # the widest thing we measure is the protrusion ring at 1.42 R
    row("protrusion band 1.42R left", (cx - 1.42 * r) - left, 0)
    row("protrusion band 1.42R right", (left + bw) - (cx + 1.42 * r), 0)
    row("protrusion band 1.42R top", (cy - 1.42 * r) - top, 0)
    # knife slot sits at 2.00 R .. 2.80 R below the centre
    row("knife slot top  2.00R", (top + bh) - (cy + 2.00 * r), 0)
    row("knife slot bottom 2.80R", (top + bh) - (cy + 2.80 * r), 0)

    roi = full[top:top + bh, left:left + bw]
    print()
    print(f"sky inside box   : {100 * lt.screen_sky_frac(roi):.1f}%")
    print(f"sky on screen    : {100 * lt.screen_sky_frac(full, downscale=4):.1f}%")

    # ---- annotate -------------------------------------------------------- #
    vis = full.copy()
    cxl, cyl = cx - left, cy - top

    cv2.rectangle(vis, (left, top), (left + bw, top + bh), (255, 0, 255), 3)
    for mult, col, name in ((0.55, (255, 255, 0), "tex in"),
                            (0.92, (255, 255, 0), "tex out"),
                            (0.95, (0, 255, 255), "pro in"),
                            (1.42, (0, 255, 255), "pro out")):
        cv2.circle(vis, (int(cx), int(cy)), int(mult * r), col, 1)
        cv2.putText(vis, f"{mult:.2f}R {name}",
                    (int(cx + mult * r * 0.72), int(cy - mult * r * 0.72)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    cv2.circle(vis, (int(cx), int(cy)), int(r), (0, 0, 255), 2)

    sx0 = int(max(0, cxl - 0.25 * r))
    sx1 = int(min(bw, cxl + 0.25 * r))
    sy0 = int(cyl + 2.00 * r)
    sy1 = int(min(bh, cyl + 2.80 * r))
    cv2.rectangle(vis, (left + sx0, top + sy0), (left + sx1, top + sy1),
                  (0, 255, 0), 2)
    cv2.putText(vis, f"knife slot {sy1 - sy0}px tall", (left + sx0, top + sy0 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

    cv2.putText(vis, f"box {bw}x{bh} @ ({left},{top})  r={r:.1f}",
                (left, max(18, top - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (255, 0, 255), 2, cv2.LINE_AA)

    cv2.imwrite(args.out, vis)
    cv2.imwrite("temp/area_check_crop.png", roi)
    print()
    print(f"annotated screen -> {args.out}")
    print(f"exact crop       -> temp/area_check_crop.png  ({roi.shape[1]}x{roi.shape[0]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
