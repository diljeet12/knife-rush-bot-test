"""Grab the screen with MSS and save downscaled PNGs.

Why this exists: the overlay is drawn on top of the game, so a plain screen
grab shows the game AND the HUD lines together. That is the only way to check
that the box, the target circle and the ticks actually sit where the game
draws the target -- the captured ROI on its own cannot tell you that.

    python shot.py [outdir] [count] [gap_seconds] [scale]
    python shot.py temp/shots 1 0 0.5
"""
import os
import sys
import time

import cv2
import mss
import numpy as np


def main() -> int:
    outdir = sys.argv[1] if len(sys.argv) > 1 else "temp/shots"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    gap = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    scale = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
    os.makedirs(outdir, exist_ok=True)

    sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
    mon = sct.monitors[1]
    for i in range(count):
        img = np.array(sct.grab(mon))[:, :, :3].copy()
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                           interpolation=cv2.INTER_AREA)
        path = os.path.join(outdir, f"shot_{i:02d}.png")
        cv2.imwrite(path, small)
        print(f"wrote {path}  ({w}x{h} -> {small.shape[1]}x{small.shape[0]})")
        if i + 1 < count:
            time.sleep(gap)
    sct.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
