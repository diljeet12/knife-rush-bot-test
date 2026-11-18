"""Cluster the digit glyphs harvested from real play, so a human can label them.

Why clustering and not OCR
--------------------------
The label is drawn on the log, so its rendered size drifts (+-10%) as the log
wobbles, and knives stuck in the log occlude it. Exact template matching fails;
normalised-shape clustering does not care about size and simply ignores the
frames that were occluded, because those do not form 5 glyphs at all.

Output
------
temp/digits/clusters.png   one enlarged row per cluster, ID printed on it
temp/digits/labels.json    filled by a human (cluster id -> digit character)

Nothing here guesses a label. It only groups shapes and shows them.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import numpy as np
import cv2

import multiplier_reader as mr

DIST = 0.16          # mean XOR on the 20x30 mask; ~a fifth of the pixels


def valid(glyphs):
    """A well-formed 'xN.NN': 5 glyphs, right kinds, sane sizes.

    Sizes are checked loosely on purpose -- 14x35 to 17x41 were both observed
    live, so a tight box would throw away good frames.
    """
    if len(glyphs) != 5:
        return False
    kinds = []
    for g in glyphs:
        if g["h"] < 14:
            kinds.append("dot")
        elif g["h"] < 30:
            kinds.append("x")
        else:
            kinds.append("digit")
    if kinds != ["x", "digit", "dot", "digit", "digit"]:
        return False
    for g in (glyphs[1], glyphs[3], glyphs[4]):    # digit positions only
        if not (9 <= g["w"] <= 32 and 28 <= g["h"] <= 46):
            return False
    if not (7 <= glyphs[2]["w"] <= 16 and 6 <= glyphs[2]["h"] <= 14):
        return False
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=float, default=DIST,
                    help="max mean-XOR distance to join a cluster")
    ap.add_argument("--tag", default="",
                    help="suffix for output files, to compare thresholds")
    a = ap.parse_args()
    globals()["DIST"] = a.dist
    crops = sorted(glob.glob("temp/harvest/state_*.png"))
    print(f"{len(crops)} harvested states")
    centroids = []      # list of (mask, count)
    glyphs_total = 0
    ok_frames = 0
    per_frame = []      # (path, [cluster ids])
    for p in crops:
        im = cv2.imread(p)
        if im is None:
            continue
        g = mr.segment(im)
        if not valid(g):
            continue
        ok_frames += 1
        ids = []
        for gid in (1, 3, 4):           # the three digit positions
            m = g[gid]["mask"]
            best, bestd = None, 1e9
            for i, (c, _n) in enumerate(centroids):
                d = np.mean(m != c)
                if d < bestd:
                    best, bestd = i, d
            if best is not None and bestd < DIST:
                c, n = centroids[best]
                centroids[best] = (((c * n + m) / (n + 1)).astype(np.uint8), n + 1)
                ids.append(best)
            else:
                centroids.append((m.copy(), 1))
                ids.append(len(centroids) - 1)
            glyphs_total += 1
        per_frame.append((os.path.basename(p), ids))

    print(f"well-formed frames: {ok_frames}  digit glyphs: {glyphs_total}")
    print(f"clusters: {len(centroids)}")
    for i, (c, n) in enumerate(centroids):
        print(f"  cluster {i:2d}: {n:4d} samples")

    os.makedirs("temp/digits", exist_ok=True)
    rows = []
    for i, (c, n) in enumerate(centroids):
        t = (c * 255).astype(np.uint8)
        t = cv2.resize(t, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
        t = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        t = cv2.copyMakeBorder(t, 8, 8, 70, 8, cv2.BORDER_CONSTANT, value=(30, 30, 30))
        cv2.putText(t, f"#{i}", (6, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        cv2.putText(t, f"n={n}", (6, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 1)
        rows.append(t)
    w = max(r.shape[1] for r in rows)
    h = sum(r.shape[0] for r in rows)
    out = np.full((h, w, 3), 30, np.uint8)
    y = 0
    for r in rows:
        out[y:y + r.shape[0], :r.shape[1]] = r
        y += r.shape[0]
    cv2.imwrite("temp/digits/clusters.png", out)
    print("montage -> temp/digits/clusters.png")

    with open("temp/digits/frames.csv", "w", newline="") as f:
        w_ = csv.writer(f)
        w_.writerow(["file", "d1", "d2", "d3"])
        for name, ids in per_frame:
            w_.writerow([name] + ids)
    print("per-frame clusters -> temp/digits/frames.csv")

    # Persist the centroids so the runtime reader can classify without
    # re-clustering: the cluster IDs are only valid with this exact set.
    np.savez_compressed(
        "measurements/digit_templates.npz",
        masks=np.array([c for c, _ in centroids], dtype=np.uint8),
        counts=np.array([n for _, n in centroids], dtype=np.int32),
        dist=np.array([a.dist], dtype=np.float32),
    )
    print(f"templates -> measurements/digit_templates.npz "
          f"({len(centroids)} shapes, dist={a.dist})")


if __name__ == "__main__":
    main()
