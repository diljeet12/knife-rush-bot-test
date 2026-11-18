"""Read the multiplier the game prints in the CENTRE OF THE LOG.

Why this and not the panel digits
---------------------------------
The bottom panel prints CASHOUT in ~14 px type and greys it out when idle. The
log centre prints the multiplier on the wood in ~35 px bold white type with a
dark outline, and it is shown while the round runs. Measured on a live 1920x1080
frame: 5 glyphs, digit height 35-36 px. That is 2.5x the panel size and it is
the number the player actually watches, so it is the one worth reading.

Layout is FIXED
---------------
The game always prints 'xN.NN': an 'x', ONE integer digit (1 or 2 -- the ladder
tops out at 2.70), a dot, and two decimals. So the glyph ORDER is known and
only three digits need classifying. Colour and position do the rest:
    glyph 0 = 'x'      short and wide, ~26 px tall
    glyph 1 = integer  tall, ~35 px
    glyph 2 = '.'      tiny, ~9 px
    glyph 3 = decimal  tall
    glyph 4 = decimal  tall

WHAT THE NUMBER MEANS  (measured, and it is not what it looks like)
------------------------------------------------------------------
The log prints the rung you reach AFTER the NEXT hit -- not what you hold now.
Proof from a live frame: log showed x1.56 while CASHOUT was $155.40 and BET was
$105, and 155.40 / 105 = 1.48, with the gold ladder knife sitting on x1.48.
So:
    cash-out value  = CASHOUT / BET  = the gold knife's rung
    log number      = the NEXT rung after that one
Consequences that matter:
  * x1.01 on the log means nothing is banked yet -- it is the round-start idle
    state, which is exactly the "back at the start" signal.
  * to cash out at a target, compare CASHOUT/BET (or the log one rung behind),
    never the raw log number.

This is why the reader is a LOGGING tool first. Reading the log gives position
along the ladder and round starts; the value actually held has to be taken one
rung behind it.

Segmentation
------------
The fill is white (V>205, S<55 after HSV). The outline is dark brown and the
wood is orange, so both fall outside that range and the glyphs separate without
any morphology. Verified on a live frame: exactly 5 components, no merges.

Status
------
Segmentation: PROVEN on live pixels.
Classification: needs a template bank, which is harvested from real play (see
harvest()). The bank is small -- ten digits -- and once populated every read is
exact. read_multiplier() returns None rather than guessing when a glyph does
not match, because a wrong multiplier is worse than no multiplier.
"""

from __future__ import annotations

import os
import numpy as np
import cv2

# The confirmed ladder, verified by decoding a full run: every value decoded
# in order, with no illegal reading, from 1.01 up to 1.42.
LADDER = [1.00, 1.01, 1.03, 1.06, 1.10, 1.15, 1.19, 1.24, 1.30, 1.35, 1.42,
          1.48, 1.56, 1.65, 1.75, 1.85, 1.98, 2.12, 2.28, 2.47, 2.70]

# Values the game was SEEN to display, in order, beyond the ruler above:
#   x2.96  x3.28  x3.70  x4.11  x4.64  x5.39
# These were read off the log during a real run and confirmed by eye. They are
# NOT proven contiguous -- there may be rungs between them that the run never
# landed on -- so they are kept separate and never used for snapping.
WITNESSED_BEYOND = [2.96, 3.28, 3.70, 4.11, 4.64, 5.39]

GLYPH_W, GLYPH_H = 20, 30          # normalised template size
WHITE_V, WHITE_S = 205, 55         # measured on live pixels
MIN_AREA = 12


def centre_box(cx: float, cy: float, r: float):
    """The strip of log centre that holds the number, in units of r.

    +-0.50r horizontally and +-0.26r vertically was measured to contain the
    whole string with margin, and it scales with the log, unlike fixed pixels.
    """
    return (int(cx - 0.50 * r), int(cy - 0.26 * r),
            int(cx + 0.50 * r), int(cy + 0.26 * r))


def centre_crop(frame, cx, cy, r):
    x0, y0, x1, y1 = centre_box(cx, cy, r)
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(frame.shape[1], x1); y1 = min(frame.shape[0], y1)
    return frame[y0:y1, x0:x1, :]


def segment(crop):
    """Split the white numeral into glyphs, left to right.

    Returns a list of dicts: {x, y, w, h, area, mask} where mask is the glyph
    normalised to GLYPH_W x GLYPH_H and binarised. Ordering is the reading order
    the fixed layout depends on.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    s = hsv[:, :, 1]
    white = ((v > WHITE_V) & (s < WHITE_S)).astype(np.uint8)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(white, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < MIN_AREA:
            continue
        g = white[y:y + h, x:x + w]
        m = cv2.resize(g.astype(np.float32), (GLYPH_W, GLYPH_H),
                       interpolation=cv2.INTER_AREA)
        out.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                    "area": int(area), "mask": (m > 0.45).astype(np.uint8)})
    out.sort(key=lambda d: d["x"])
    return out


def describe(glyphs):
    """Human-readable structure check, independent of classification."""
    kind = []
    for g in glyphs:
        if g["h"] < 14:
            kind.append("dot")
        elif g["h"] < 32:
            kind.append("x")
        else:
            kind.append("digit")
    return " ".join(f"{k}({g['w']}x{g['h']})" for k, g in zip(kind, glyphs))


def harvest(crop, tag, folder):
    """Save every glyph of one capture, named so a human can label it later."""
    os.makedirs(folder, exist_ok=True)
    glyphs = segment(crop)
    saved = []
    for i, g in enumerate(glyphs):
        p = os.path.join(folder, f"{tag}_p{i}.png")
        vis = (g["mask"] * 255).astype(np.uint8)
        cv2.imwrite(p, cv2.resize(vis, None, fx=6, fy=6,
                                  interpolation=cv2.INTER_NEAREST))
        saved.append(p)
    return glyphs, saved


# Every rung we have ever seen printed, in order. The first 21 are confirmed by
# decoding a full run; the tail was witnessed live and may have gaps, so it is
# only used for ordering, never for snapping.
ALL_RUNGS = LADDER + WITNESSED_BEYOND


def current_from_log(value):
    """Convert the number ON THE LOG into the multiplier actually held.

    The log prints the NEXT rung, proven three ways on live pixels:
      * at round start the log reads x1.01 while the gold ladder knife sits on
        x1.00 -- nothing is banked yet;
      * in a live round the log read x1.56 while the gold knife sat on x1.48;
      * the same frame's CASHOUT was $155.40 against a $105 bet, and
        155.40 / 105 = 1.48.
    So the held value is the largest rung strictly below the printed one.
    """
    if value is None:
        return None
    below = [v for v in ALL_RUNGS if v < value - 1e-9]
    return max(below) if below else ALL_RUNGS[0]


def snap(value):
    """Snap a read value to the nearest legal ladder rung, and say how far."""
    if value is None:
        return None, None
    best = min(LADDER, key=lambda v: abs(v - value))
    return best, abs(best - value)


def holes(mask):
    """Count enclosed background regions in a glyph.

    Measured on the harvested centroids, this is perfectly discriminative and
    costs nothing:
        8 -> 2     0, 6, 9 -> 1     everything else -> 0
    It exists because a bold '0' matched the '8' shape at distance 0.07 and was
    read as x1.38 when the screen plainly said x1.30. Shape distance alone
    cannot separate those, because the wrong answer is *close*.
    """
    inv = (1 - mask).astype(np.uint8)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(inv, 4)
    h, w = inv.shape
    interior = 0
    for i in range(1, n):
        x, y, ww, hh, a = stats[i]
        if x == 0 or y == 0 or x + ww >= w or y + hh >= h:
            continue
        if a >= 6:
            interior += 1
    return interior


def find_text(glyphs):
    """Pick the 5 components that actually form 'xN.NN'.

    Necessary because the log RESKINS into a red/white ringed target at higher
    levels, and those white rings pass the same "white text" threshold. It also
    has to survive stray fragments: a 7x15 scrap of ring was seen sitting
    between the '1' and the '.', which defeats any sliding-window approach.

    So the structure is built up from its most reliable part -- the three
    digits, which share a top edge and a height -- and the dot and 'x' are then
    located relative to them. All tests are ratios and offsets, never absolute
    sizes, because the label's rendered size drifts +-10 % as the log wobbles.
    """
    if len(glyphs) < 5:
        return None

    # 1) digits: tall, solid, and sharing a top edge
    tall = [g for g in glyphs
            if 26 <= g["h"] <= 50 and g["w"] <= 34
            and g["area"] / float(g["w"] * g["h"]) >= 0.55]
    if len(tall) < 3:
        return None

    best = None
    for grp in tall:
        same = sorted([g for g in tall
                       if abs(g["y"] - grp["y"]) <= 4
                       and abs(g["h"] - grp["h"]) <= 6],
                      key=lambda g: g["x"])
        for i in range(len(same) - 2):
            trip = same[i:i + 3]
            span = trip[2]["x"] - trip[0]["x"]
            if span > 95:
                continue
            score = (abs(trip[0]["h"] - trip[1]["h"])
                     + abs(trip[1]["h"] - trip[2]["h"]) + span * 0.02)
            if best is None or score < best[0]:
                best = (score, trip)
    if best is None:
        return None
    d1, d2, d3 = best[1]

    # 2) dot: small, sitting between the first two digits, lower than their tops
    dots = [g for g in glyphs
            if 5 <= g["h"] <= 16 and g["w"] <= 18
            and d1["x"] < g["x"] < d2["x"]
            and g["y"] > min(d1["y"], d2["y"])]
    if not dots:
        return None
    dot = max(dots, key=lambda g: g["area"])

    # 3) 'x': shorter than the digits, to the left of the first digit
    xs = [g for g in glyphs
          if g["x"] + g["w"] <= d1["x"] + 3
          and 15 <= g["h"] <= 34 and g["w"] >= 13]
    if not xs:
        return None
    xg = max(xs, key=lambda g: g["area"])

    return [xg, d1, dot, d2, d3]


class Reader:
    """Runtime classifier: crop, segment, match against the saved shapes.

    A read is only returned when every digit position matches a known shape
    within `max_dist`. Anything else (occluded by a knife, mid-animation,
    garbled) returns None with a reason, because acting on a wrong multiplier
    is worse than acting on none.

    Matching is gated on the hole count first, so a one-hole glyph can never
    be read as an 8 no matter how small the pixel distance is.
    """

    def __init__(self, npz="measurements/digit_templates.npz",
                 labels="measurements/digit_labels.json",
                 max_dist: float = 0.16):
        import json
        z = np.load(npz)
        self.masks = z["masks"].astype(np.uint8)
        self.lab = {int(k): v for k, v in json.load(open(labels)).items()}
        self.hole = np.array([holes(m) for m in self.masks], dtype=np.int32)
        self.max_dist = max_dist

    def classify(self, mask):
        """Nearest shape by mean XOR, or (None, distance) if too far."""
        h = holes(mask)
        cand = np.flatnonzero(self.hole == h)
        if len(cand) == 0:                 # never guessed: structure is unknown
            return None, 1.0
        d = np.mean(self.masks[cand] != mask[None, :, :], axis=(1, 2))
        j = int(np.argmin(d))
        if d[j] > self.max_dist:
            return None, float(d[j])
        return self.lab[int(cand[j])], float(d[j])

    def read(self, frame, cx: float, cy: float, r: float):
        """Return (value, reason). value is None when the read is not trusted."""
        crop = centre_crop(frame, cx, cy, r)
        glyphs = segment(crop)
        text = find_text(glyphs)
        if text is None:
            return None, f"no_text({len(glyphs)} blobs)"
        digits = []
        worst = 0.0
        for pos in (1, 3, 4):
            ch, d = self.classify(text[pos]["mask"])
            if ch is None:
                return None, f"unmatched@{pos}(d={d:.3f})"
            digits.append(ch)
            worst = max(worst, d)
        value = int(digits[0]) + int(digits[1] + digits[2]) / 100.0
        return value, f"ok(d={worst:.3f})"


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "temp/round_t200.png"
    im = cv2.imread(src)
    if im is None:
        raise SystemExit(f"cannot read {src}")
    import live_track as lt
    got = lt.find_target(im, verbose=False)
    if got is None:
        raise SystemExit("no log on that image")
    cx, cy, r = got
    crop = centre_crop(im, cx, cy, r)
    glyphs = segment(crop)
    print(f"{src}: log at ({cx:.1f},{cy:.1f}) r={r:.1f}")
    print(f"  glyphs: {len(glyphs)}")
    print(f"  layout: {describe(glyphs)}")
    for i, g in enumerate(glyphs):
        print(f"    p{i}: x={g['x']:3d} y={g['y']:3d} {g['w']:2d}x{g['h']:2d} area={g['area']}")
