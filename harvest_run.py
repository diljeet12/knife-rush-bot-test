"""Record every distinct multiplier the game shows, while the bot plays.

Why a separate process
----------------------
autoplay.py is the validated actuator and must not grow calibration code. This
watcher only reads pixels and writes files; it never sends input, so it cannot
interfere with the run.

How the labels become ground truth
----------------------------------
The log centre always prints 'xN.NN' and starts a round at x1.01. As hits land
the value only ever moves FORWARD along the confirmed ladder, so the order in
which new values appear IS the ladder order. That means the harvest labels
itself: the 1st distinct value is the round-start rung, the 2nd is the next
rung, and so on. A human then reads the saved crops to confirm the mapping
matches the ruler, which is a one-minute check rather than an OCR project.

Output
------
temp/harvest/state_000.png ..   one crop per distinct value, in first-seen order
temp/harvest/index.csv          order, first/last time seen, frame count
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import time
import numpy as np
import cv2
import mss

import live_track as lt
import multiplier_reader as mr


def signature(glyphs):
    """Coarse identity of a reading: glyph shapes, not their absolute position.

    Positions move by a pixel or two as the log wobbles, so they are excluded;
    a couple of stray antialiasing pixels are tolerated by the 0.45 threshold
    inside segment().
    """
    if not glyphs:
        return None
    h = hashlib.blake2b(digest_size=8)
    for g in glyphs:
        h.update(bytes([g["w"], g["h"]]))
        h.update(np.packbits(g["mask"]).tobytes())
    return h.hexdigest()


def main() -> int:
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--duration", type=float, default=80.0)
    ap_.add_argument("--fps", type=float, default=8.0)
    ap_.add_argument("--out", default="temp/harvest")
    args = ap_.parse_args()

    os.makedirs(args.out, exist_ok=True)
    sct = mss.MSS()
    mon = sct.monitors[1]
    grab = lambda: np.array(sct.grab(mon))[:, :, :3].copy()

    seen = {}          # signature -> state index
    order = []         # state index -> dict
    t0 = time.perf_counter()
    nframes = 0
    nmiss = 0
    period = 1.0 / args.fps
    next_t = t0

    while True:
        now = time.perf_counter()
        if now - t0 > args.duration:
            break
        if now < next_t:
            time.sleep(min(0.01, next_t - now))
            continue
        next_t = now + period
        nframes += 1

        frame = grab()
        got = lt.find_target(frame, verbose=False)
        if got is None:
            nmiss += 1
            continue
        cx, cy, r = got
        crop = mr.centre_crop(frame, cx, cy, r)
        glyphs = mr.segment(crop)
        sig = signature(glyphs)
        if sig is None:
            nmiss += 1
            continue
        t = time.perf_counter() - t0
        if sig not in seen:
            idx = len(order)
            seen[sig] = idx
            path = os.path.join(args.out, f"state_{idx:03d}.png")
            cv2.imwrite(path, crop)
            order.append({"idx": idx, "first": t, "last": t, "count": 1,
                          "layout": mr.describe(glyphs), "path": path})
        else:
            o = order[seen[sig]]
            o["last"] = t
            o["count"] += 1

    with open(os.path.join(args.out, "index.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "first_s", "last_s", "frames", "layout", "path"])
        for o in order:
            w.writerow([o["idx"], round(o["first"], 2), round(o["last"], 2),
                        o["count"], o["layout"], o["path"]])

    print(f"frames sampled : {nframes}  ({nframes/max(args.duration,1e-9):.1f} fps)")
    print(f"frames skipped : {nmiss}")
    print(f"distinct values: {len(order)}")
    for o in order:
        print(f"  state {o['idx']:2d}  first {o['first']:6.2f}s  "
              f"seen {o['count']:4d}x  {o['layout']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
