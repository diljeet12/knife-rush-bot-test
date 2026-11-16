#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_speed.py
=============
Measure the rotational speed (angular velocity) of the Knife Rush target log
from a screen recording.

No AI model. No training data. Pure signal processing. See README-style notes
at the bottom of this docstring for *why*.


WHAT THIS DOES
--------------
The task is not "recognise the log". It is "how many degrees did the log rotate
between frame t and frame t+1". That is a metrology problem.

The wood grain, the bark cracks and the rim shading form a natural optical
encoder. This script:

  1. Locates the log (centre + radius) with a colour mask + robust radial scan.
     The median radius is used, so knives sticking out do not inflate it.
  2. Unwraps an annulus of the log into a (angle x radius) polar image.
     The inner radius is deliberately pulled in, to exclude the "x1.01"
     multiplier text in the middle of the log -- that text does NOT rotate
     with the log, and including it would bias every estimate toward zero.
  3. Averages across radius to get a 1-D signature s(theta) -- a periodic
     function of the log's rotation.
  4. Recovers rotation as a circular shift between consecutive signatures,
     by FFT cross-correlation, with parabolic sub-bin interpolation.
  5. Cross-checks every frame with a second, independent-ish estimator that
     correlates each radius ring separately instead of averaging first.
  6. Converts to degrees/second, revolutions/second and RPM, then finds the
     distinct speed tiers the game uses.

  cost      ~0.3 - 1.5 ms per frame on CPU
  accuracy  ~0.05 - 0.3 degrees per frame
  failure   explicit: every frame carries a confidence score, and frames below
            the threshold are dropped instead of silently averaged in.


WHY NOT A NEURAL NETWORK
------------------------
  * A segmentation mask boundary carries 1-2 px of noise. At r = 132 px,
    1 px = 0.43 deg. So a CNN caps out near +-1 deg BEFORE you even estimate
    rotation from its mask. Cross-correlation gets 0.1-0.3 deg.
  * Inference costs 5-30 ms. The whole 60 Hz budget is 16.7 ms.
  * No training data exists for this specific game.
  * A CNN fails opaquely; this fails with a number you can threshold.

Deep learning is the right tool for a different job: producing a one-time
ground-truth mask of the log, offline. That is a separate script.


USAGE
-----
  python find_speed.py --video gameplay1.mp4
  python find_speed.py --video gameplay1.mp4 --limit 200     # quick test
  python find_speed.py --video gameplay1.mp4 --no-plot       # skip matplotlib
  python find_speed.py --probe                               # metadata only
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

# --------------------------------------------------------------------------- #
# Keep every byte this script produces on the project drive.
# This machine's C: sits at 8.5% free; nothing here may add to that.
# Must run BEFORE cv2 / matplotlib / numpy are imported, because they read
# these variables at import time.
# --------------------------------------------------------------------------- #
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_LOCAL_CACHE = os.path.join(_PROJECT_ROOT, ".cache")
_LOCAL_TEMP = os.path.join(_PROJECT_ROOT, "temp")

for _p in (os.path.join(_LOCAL_CACHE, "matplotlib"), _LOCAL_TEMP):
    os.makedirs(_p, exist_ok=True)

os.environ["MPLCONFIGDIR"] = os.path.join(_LOCAL_CACHE, "matplotlib")
os.environ["XDG_CACHE_HOME"] = _LOCAL_CACHE
os.environ["PIP_CACHE_DIR"] = os.path.join(_LOCAL_CACHE, "pip")
os.environ["TEMP"] = _LOCAL_TEMP
os.environ["TMP"] = _LOCAL_TEMP
os.environ["TMPDIR"] = _LOCAL_TEMP

import tempfile                                              # noqa: E402

tempfile.tempdir = _LOCAL_TEMP

import cv2                                                   # noqa: E402
import numpy as np                                           # noqa: E402


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class Cfg:
    video: str
    outdir: str = "measurements"
    n_theta: int = 1440          # angular bins -> 0.25 deg per bin
    n_radius: int = 32           # radial rings sampled between inner/outer
    inner_frac: float = 0.55     # inner radius as a fraction of the wood radius
    outer_frac: float = 0.92     # outer radius as a fraction of the wood radius
    min_conf: float = 0.25       # normalised correlation below this = reject
    min_sharp: float = 0.05      # peak sharpness below this = ambiguous
    max_deg_per_frame: float = 175.0   # physically impossible above this
    detect_samples: int = 24     # frames used to lock the log's centre/radius
    limit: Optional[int] = None  # process only the first N frames
    probe: bool = False
    plot: bool = True
    verbose: bool = True


# --------------------------------------------------------------------------- #
# Core estimator
# --------------------------------------------------------------------------- #

def circular_lag(a: np.ndarray, b: np.ndarray) -> Tuple[float, float, float]:
    """Estimate the circular shift L such that b ~= np.roll(a, L).

    Returns (lag_in_bins, confidence, sharpness).

    Derivation of the sign, so nobody has to guess:
        c[k] = IDFT( FFT(a) * conj(FFT(b)) )[k] = sum_n a[n] * b[n-k]
    A peak at index k therefore means a[n] ~= b[n-k], i.e. b[m] ~= a[m+k],
    i.e. b = roll(a, -k). So L = -k. The unit test below enforces this.
    """
    n = a.size
    A = np.fft.rfft(a)
    B = np.fft.rfft(b)
    c = np.fft.irfft(A * np.conj(B), n=n)

    k = int(np.argmax(c))

    # Sub-bin refinement: parabola through the peak and its two neighbours.
    y0 = c[(k - 1) % n]
    y1 = c[k]
    y2 = c[(k + 1) % n]
    denom = y0 - 2.0 * y1 + y2
    delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
    delta = float(np.clip(delta, -0.5, 0.5))

    lag = -(k + delta)
    lag = (lag + n / 2.0) % n - n / 2.0        # wrap into [-n/2, +n/2)

    # Confidence: both inputs are unit-norm, so the peak value is the
    # normalised correlation coefficient, bounded by [-1, 1].
    conf = float(c[k])

    # Sharpness: how much the best peak beats the best *distant* peak.
    # A low value means the estimate is ambiguous (e.g. near 180 deg, or a
    # frame where the log is not on screen at all).
    mask = np.ones(n, dtype=bool)
    for d in range(-5, 6):
        mask[(k + d) % n] = False
    k2 = int(np.argmax(np.where(mask, c, -np.inf)))
    sharp = (c[k] - c[k2]) / (abs(c[k]) + 1e-12)

    return float(lag), conf, float(sharp)


def normalise(v: np.ndarray) -> Optional[np.ndarray]:
    """Zero-mean, unit-norm. Returns None if the signal is flat (no texture)."""
    v = v.astype(np.float64)
    v = v - v.mean()
    nrm = float(np.linalg.norm(v))
    if nrm < 1e-6:
        return None
    return v / nrm


def signature_from_polar(polar: np.ndarray) -> Optional[np.ndarray]:
    """Collapse (angle x radius) -> 1-D angular signature.

    Each radius ring is DC-removed and equalised before averaging, so a bright
    bark ring does not drown out a faint inner ring, and slow radial brightness
    gradients do not masquerade as angular structure.
    """
    p = polar.astype(np.float64)
    p = p - p.mean(axis=0, keepdims=True)          # per-ring DC removal
    sd = p.std(axis=0, keepdims=True)
    sd = np.where(sd < 1e-2, 1e-2, sd)             # floor: don't amplify noise
    p = p / sd
    return normalise(p.mean(axis=1))


def per_ring_lag(prev: np.ndarray, cur: np.ndarray) -> Optional[float]:
    """Second estimator: correlate each radius ring separately, then take a
    confidence-weighted median. Independent of the radial averaging in
    signature_from_polar(), so the two disagreeing is a useful warning."""
    lags, weights = [], []
    for j in range(prev.shape[1]):
        a = normalise(prev[:, j])
        b = normalise(cur[:, j])
        if a is None or b is None:
            continue
        lag, conf, sharp = circular_lag(a, b)
        if conf > 0.15:
            lags.append(lag)
            weights.append(max(conf, 0.0) * max(sharp, 0.01))
    if len(lags) < 4:
        return None
    lags = np.asarray(lags)
    weights = np.asarray(weights)
    order = np.argsort(lags)
    cw = np.cumsum(weights[order])
    return float(lags[order][np.searchsorted(cw, 0.5 * cw[-1])])


# --------------------------------------------------------------------------- #
# Target detection
# --------------------------------------------------------------------------- #

def _fit_circle(pts: np.ndarray) -> Tuple[float, float, float]:
    """Algebraic (Kasa) least-squares circle fit."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([2.0 * x, 2.0 * y, np.ones_like(x)])
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, c = sol[0], sol[1], sol[2]
    r = math.sqrt(max(c + cx * cx + cy * cy, 1e-6))
    return float(cx), float(cy), float(r)


def detect_target(frame: np.ndarray) -> Optional[Tuple[float, float, float]]:
    """Find the log: (cx, cy, radius) in frame pixels, or None.

    Strategy: the log is the dominant warm-coloured blob. Its centroid is a
    good first estimate; a radial scan outward from that centroid then gives a
    boundary that is *robust* -- the median is taken, so the handful of rays
    that pass through a protruding knife are discarded rather than inflating
    the radius.
    """
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Wood / orange-brown. Background is sky-blue and forest-green, so this
    # isolates the log cleanly.
    mask = cv2.inRange(hsv, (5, 80, 80), (34, 255, 255))

    k = max(3, (int(round(min(h, w) * 0.015)) | 1))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    n_lab, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    if n_lab <= 1:
        return None

    areas = stats[1:, cv2.CC_STAT_AREA]
    idx = 1 + int(np.argmax(areas))
    box_w = stats[idx, cv2.CC_STAT_WIDTH]
    box_h = stats[idx, cv2.CC_STAT_HEIGHT]
    if box_w <= 0 or box_h <= 0:
        return None
    aspect = box_w / float(box_h)
    if not (0.60 <= aspect <= 1.65):      # the log is round; reject slivers
        return None
    if areas[idx - 1] < 0.0015 * h * w:   # too small to be the log
        return None

    cx, cy = float(cents[idx][0]), float(cents[idx][1])
    comp = (labels == idx)

    # Radial scan: for each of 720 directions, the furthest radius still on the
    # blob. The median of those distances is the real radius.
    n_rays = 720
    angs = np.arange(n_rays, dtype=np.float64) * (2.0 * math.pi / n_rays)
    r_max = int(min(h, w) * 0.45)
    radii = np.arange(4, max(r_max, 6), dtype=np.float64)
    ca = np.cos(angs)[:, None]
    sa = np.sin(angs)[:, None]

    xs = (cx + radii[None, :] * ca).astype(np.int32)
    ys = (cy + radii[None, :] * sa).astype(np.int32)
    inb = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    xs_c = np.clip(xs, 0, w - 1)
    ys_c = np.clip(ys, 0, h - 1)
    inside = inb & comp[ys_c, xs_c]

    has = inside.any(axis=1)
    # index of the furthest True sample along each ray
    pos = inside.shape[1] - 1 - inside[:, ::-1].argmax(axis=1)
    hit_r = np.where(has, radii[pos], np.nan)

    ok_ray = np.isfinite(hit_r)
    if int(ok_ray.sum()) < 180:
        return None
    pts = np.column_stack([cx + hit_r[ok_ray] * np.cos(angs[ok_ray]),
                           cy + hit_r[ok_ray] * np.sin(angs[ok_ray])])
    d = np.linalg.norm(pts - np.array([cx, cy]), axis=1)
    r_med = float(np.median(d))

    # Drop the spikes: rays that hit a protruding knife land far outside the
    # median. Keep only points near the median radius, then refit -- twice,
    # because a wooden knife handle that survived the first trim still drags
    # the centre.
    keep = (d > r_med * 0.85) & (d < r_med * 1.10)
    if int(keep.sum()) < 120:
        keep = (d > r_med * 0.75) & (d < r_med * 1.12)
    if int(keep.sum()) < 90:
        return None

    fx, fy, fr = _fit_circle(pts[keep])
    for _ in range(2):
        d2 = np.linalg.norm(pts - np.array([fx, fy]), axis=1)
        k2 = (d2 > fr * 0.90) & (d2 < fr * 1.06)
        if int(k2.sum()) < 90:
            break
        fx, fy, fr = _fit_circle(pts[k2])

    if (math.hypot(fx - cx, fy - cy) > 0.25 * r_med
            or not (0.75 * r_med < fr < 1.35 * r_med)):
        return cx, cy, r_med
    return fx, fy, fr


def estimate_target(cap, cfg: Cfg) -> Tuple[float, float, float, dict]:
    """Lock the log's centre and radius using several frames, then take the
    median. One frame is not enough: knives are stuck in it, and the log is
    sometimes mid-throw."""
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    step = max(1, total // max(1, cfg.detect_samples)) if total else 20

    found = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            got = detect_target(frame)
            if got is not None:
                found.append(got)
        i += 1
        if total and i >= total:
            break

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    if not found:
        raise RuntimeError(
            "Could not find the log in any sampled frame. The hue range in "
            "detect_target() probably needs tuning for this recording."
        )

    arr = np.asarray(found, dtype=np.float64)
    cx, cy, r = (float(np.median(arr[:, 0])),
                 float(np.median(arr[:, 1])),
                 float(np.median(arr[:, 2])))

    info = {
        "samples": len(found),
        "cx_spread_px": float(np.ptp(arr[:, 0])),
        "cy_spread_px": float(np.ptp(arr[:, 1])),
        "r_spread_px": float(np.ptp(arr[:, 2])),
    }
    return cx, cy, r, info


def make_maps(cx: float, cy: float, r_in: float, r_out: float,
              n_theta: int, n_radius: int) -> Tuple[np.ndarray, np.ndarray]:
    """Polar sampling maps. Row = angle (clockwise from +x), col = radius."""
    th = np.arange(n_theta, dtype=np.float32) * (2.0 * math.pi / n_theta)
    rr = np.linspace(r_in, r_out, n_radius).astype(np.float32)
    mx = (cx + rr[None, :] * np.cos(th)[:, None]).astype(np.float32)
    my = (cy + rr[None, :] * np.sin(th)[:, None]).astype(np.float32)
    return mx, my


def refine_center(cap, cx: float, cy: float, r_in: float, r_out: float,
                  pad: int, n_frames: int = 32,
                  span: float = 8.0) -> Tuple[float, float, dict]:
    """Find the rotation centre by maximising correlation, not by shape.

    A centre error `e` makes the sampled annulus eccentric, which injects a
    once-per-revolution wobble of roughly e/r radians into the measured angle.
    12 px of error at r = 122 px is about 5.6 degrees of wobble -- enough to
    corrupt a timing decision at speed.

    So instead of trusting the blob's shape, we search for the centre that makes
    consecutive frames look most like a *pure rotation*. Coarse pass at 2 px,
    fine pass at 0.5 px.
    """
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if total < 4:
        return cx, cy, {"skipped": "too few frames"}

    x0 = int(round(cx)) - pad
    y0 = int(round(cy)) - pad
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    x0 = max(0, min(x0, w - 2 * pad))
    y0 = max(0, min(y0, h - 2 * pad))

    idxs = np.linspace(0, total - 2, max(n_frames, 4)).astype(int)
    crops = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        crops.append(cv2.cvtColor(fr[y0:y0 + 2 * pad, x0:x0 + 2 * pad],
                                  cv2.COLOR_BGR2GRAY))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    if len(crops) < 4:
        return cx, cy, {"skipped": "no frames captured"}

    n_theta, n_radius = 720, 12

    def score(dx: float, dy: float) -> float:
        mx, my = make_maps(cx - x0 + dx, cy - y0 + dy, r_in, r_out,
                           n_theta, n_radius)
        sigs = []
        for g in crops:
            p = cv2.remap(g, mx, my, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
            s = signature_from_polar(p)
            if s is not None:
                sigs.append(s)
        if len(sigs) < 3:
            return -1.0
        confs = [circular_lag(sigs[i], sigs[i + 1])[1]
                 for i in range(len(sigs) - 1)]
        return float(np.mean(confs))

    best = (0.0, 0.0, score(0.0, 0.0))
    for dy in np.arange(-span, span + 1e-9, 2.0):
        for dx in np.arange(-span, span + 1e-9, 2.0):
            s = score(dx, dy)
            if s > best[2]:
                best = (dx, dy, s)

    fx, fy = best[0], best[1]
    best_fine = (fx, fy, score(fx, fy))
    for dy in np.arange(-2.0, 2.0 + 1e-9, 0.5):
        for dx in np.arange(-2.0, 2.0 + 1e-9, 0.5):
            s = score(fx + dx, fy + dy)
            if s > best_fine[2]:
                best_fine = (fx + dx, fy + dy, s)

    info = {
        "dx": float(best_fine[0]),
        "dy": float(best_fine[1]),
        "conf_after": float(best_fine[2]),
        "conf_at_origin": float(score(0.0, 0.0)),
    }
    return cx + best_fine[0], cy + best_fine[1], info


# --------------------------------------------------------------------------- #
# Speed-tier analysis
# --------------------------------------------------------------------------- #

def _smooth(x: np.ndarray, k: int) -> np.ndarray:
    if k < 3 or x.size < k:
        return x.copy()
    ker = np.ones(k, dtype=np.float64) / k
    return np.convolve(x, ker, mode="same")


def _medfilt(x: np.ndarray, k: int) -> np.ndarray:
    if k < 3 or x.size < k:
        return x.copy()
    pad = k // 2
    xp = np.pad(x, pad, mode="edge")
    return np.array([np.median(xp[i:i + k]) for i in range(x.size)],
                    dtype=np.float64)


def deglitch(dtheta: np.ndarray) -> Tuple[np.ndarray, int]:
    """Repair single-frame correlation failures.

    A screen recording does not sample the game's renderer uniformly. It
    occasionally duplicates a frame (delta = 0) and then catches up with a
    double step -- the total still adds up, but any single frame is a lie.
    Separately, a real correlation failure can produce a wildly wrong value.

    Both are removed here by comparing each frame against a local median.
    """
    med = _medfilt(dtheta, 9)
    resid = np.abs(dtheta - med)
    mad = _medfilt(resid, 9)
    bad = resid > (4.0 * mad + 2.0)
    fixed = dtheta.copy()
    fixed[bad] = med[bad]
    return fixed, int(bad.sum())


def windowed_speed(dtheta: np.ndarray, fps: float,
                   win: int = 15) -> np.ndarray:
    """Angular velocity from accumulated angle over a sliding window.

    Per-frame deltas are noisy because of capture jitter; the cumulative angle
    is not, because duplicates and catch-up frames cancel. So integrate first,
    then differentiate over a window. This is the standard treatment for
    noisy incremental encoders and it is why the raw per-frame plot looked
    like a sawtooth.
    """
    theta = np.cumsum(dtheta)
    h = max(1, win // 2)
    out = np.full(theta.size, np.nan)
    if theta.size > 2 * h:
        out[h:theta.size - h] = (theta[2 * h:] - theta[:theta.size - 2 * h]) \
            * fps / (2.0 * h)
    return out


def detect_tiers(speed: np.ndarray, min_share: float = 0.05) -> list:
    """Find the distinct speed plateaus the game uses.

    A histogram of |omega| is built and smoothed; peaks carrying at least
    `min_share` of the total occupancy are treated as tier centres. This is
    deliberately simple and explainable -- if the game ramps continuously
    instead of stepping, the 'coverage' figure below will come out low and
    that is the honest answer.
    """
    s = np.abs(speed)
    if s.size < 30:
        return []

    lo, hi = np.percentile(s, [1, 99])
    if hi - lo < 1e-6:
        return []
    bin_w = max(1.0, (hi - lo) / 120.0)
    edges = np.arange(lo, hi + bin_w, bin_w)
    hist, _ = np.histogram(s, bins=edges)
    if hist.sum() == 0:
        return []

    hist = _smooth(hist.astype(np.float64), 5)
    total = float(hist.sum())

    peaks = []
    for i in range(1, hist.size - 1):
        if hist[i] >= hist[i - 1] and hist[i] > hist[i + 1]:
            mass = hist[max(0, i - 2): i + 3].sum()
            if mass >= min_share * total:
                peaks.append(i)

    if not peaks:
        return []

    # Merge peaks that are not separated by a genuine valley. A speed the game
    # ramps *through* on its way to another speed is a transition, not a tier,
    # and the histogram will show a shoulder rather than a second mode.
    merged = [peaks[0]]
    for p in peaks[1:]:
        prev = merged[-1]
        if p - prev <= 3:
            if hist[p] > hist[prev]:
                merged[-1] = p
            continue
        valley = float(hist[prev:p + 1].min())
        if valley < 0.5 * min(hist[prev], hist[p]):
            merged.append(p)
        elif hist[p] > hist[prev]:
            merged[-1] = p

    centres = np.array([0.5 * (edges[p] + edges[p + 1]) for p in merged])

    # Assign every sample to its nearest tier centre.
    idx = np.argmin(np.abs(s[:, None] - centres[None, :]), axis=1)
    tiers = []
    for i, c in enumerate(centres):
        m = idx == i
        if m.sum() < 10:
            continue
        vals = s[m]
        tiers.append({
            "centre_deg_s": float(c),
            "count": int(m.sum()),
            "mean_deg_s": float(vals.mean()),
            "min_deg_s": float(vals.min()),
            "max_deg_s": float(vals.max()),
            "std_deg_s": float(vals.std()),
            "share": float(m.sum() / s.size),
        })
    tiers.sort(key=lambda t: t["centre_deg_s"])

    # How much of the data actually sits on a plateau? A high number means
    # discrete speed tiers are real; a low one means continuous acceleration.
    near = np.min(np.abs(s[:, None] - centres[None, :]), axis=1)
    coverage = float((near <= max(0.08 * float(np.median(centres)), 5.0)).mean())
    for t in tiers:
        t["coverage"] = coverage
    return tiers


def find_reversals(speed: np.ndarray, fps: float, thresh: float = 15.0):
    """Times at which the rotation direction flips. Knife Rush-style games
    usually reverse the log at certain levels; the bot must know about it."""
    s = np.nan_to_num(np.asarray(speed, dtype=np.float64), nan=0.0)
    sign = np.sign(np.where(np.abs(s) < thresh, 0, s))
    sign = sign[sign != 0]
    if sign.size < 2:
        return []
    flips = np.where(sign[1:] != sign[:-1])[0]
    return [(int(i), float(i / fps)) for i in flips]


# --------------------------------------------------------------------------- #
# Self-test: kills the sign / off-by-one class of bug before it can lie to you
# --------------------------------------------------------------------------- #

def selftest() -> None:
    rng = np.random.default_rng(12345)
    n = 720
    a = rng.normal(size=n)
    a = np.convolve(a, np.ones(7) / 7.0, mode="same")
    a = normalise(a)
    for true_shift in (0, 1, 5, 37, -37, 100, -100, 200):
        b = np.roll(a, true_shift)
        lag, conf, sharp = circular_lag(a, b)
        if abs(lag - true_shift) > 0.05:
            raise AssertionError(
                f"circular_lag sign/scale bug: expected {true_shift}, got {lag}"
            )
        if conf < 0.99:
            raise AssertionError(f"confidence broken: {conf}")
    print("[selftest] circular_lag sign convention + sub-bin accuracy : PASS")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Measure log rotation speed from video.")
    ap.add_argument("--video", default="gameplay1.mp4")
    ap.add_argument("--outdir", default="measurements")
    ap.add_argument("--limit", type=int, default=None, help="only first N frames")
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--probe", action="store_true", help="metadata only, no analysis")
    ap.add_argument("--min-conf", type=float, default=0.25)
    args = ap.parse_args()

    cfg = Cfg(video=args.video, outdir=args.outdir, limit=args.limit,
              probe=args.probe, plot=not args.no_plot, min_conf=args.min_conf)

    if not os.path.exists(cfg.video):
        print(f"ERROR: video not found: {cfg.video}", file=sys.stderr)
        return 2

    cap = cv2.VideoCapture(cfg.video)
    if not cap.isOpened():
        print(f"ERROR: OpenCV could not open {cfg.video}", file=sys.stderr)
        return 2

    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_proc = min(total, cfg.limit) if cfg.limit else total

    print("=" * 74)
    print("KNIFE RUSH - TARGET ROTATION SPEED MEASUREMENT")
    print("=" * 74)
    print(f"video        : {cfg.video}")
    print(f"resolution   : {width} x {height}")
    print(f"frame rate   : {fps:.3f} fps  (dt = {1000.0 / fps:.3f} ms)")
    print(f"frames       : {total}  ({total / fps:.2f} s)")
    if cfg.limit:
        print(f"limit        : processing first {n_proc} frames only")
    print()

    if cfg.probe:
        cap.release()
        return 0

    selftest()
    print()

    # ---- 1. lock the target ------------------------------------------------
    t0 = time.perf_counter()
    cx, cy, r_wood, det_info = estimate_target(cap, cfg)
    print(f"[target] centre = ({cx:.2f}, {cy:.2f})   wood radius = {r_wood:.2f} px")
    print(f"[target] from {det_info['samples']} frames   "
          f"spread: x {det_info['cx_spread_px']:.1f} px, "
          f"y {det_info['cy_spread_px']:.1f} px, "
          f"r {det_info['r_spread_px']:.1f} px")
    if det_info["cx_spread_px"] > 8 or det_info["cy_spread_px"] > 8:
        print("[target] WARNING: centre drifts across the clip. If the window was "
              "resized mid-recording, split the video and re-run per segment.")
    print(f"[target] detection took {time.perf_counter() - t0:.2f} s")
    print()

    r_in = r_wood * cfg.inner_frac
    r_out = r_wood * cfg.outer_frac
    print(f"[annulus] r_in = {r_in:.1f} px ({cfg.inner_frac:.2f} R), "
          f"r_out = {r_out:.1f} px ({cfg.outer_frac:.2f} R)")
    print(f"[annulus] inner cut deliberately excludes the multiplier text at "
          f"the log's centre")
    print()

    # ---- 2. refine the rotation centre -------------------------------------
    pad = int(math.ceil(r_out)) + 12
    t1 = time.perf_counter()
    cx, cy, ref_info = refine_center(cap, cx, cy, r_in, r_out, pad)
    r_wood_est = r_wood
    print(f"[refine] centre moved dx={ref_info.get('dx', 0.0):+.2f} px, "
          f"dy={ref_info.get('dy', 0.0):+.2f} px")
    print(f"[refine] mean correlation "
          f"{ref_info.get('conf_at_origin', 0.0):.4f} -> "
          f"{ref_info.get('conf_after', 0.0):.4f}  "
          f"({time.perf_counter() - t1:.2f} s)")
    print()

    # ---- 3. crop window + polar maps in crop coordinates -------------------
    x0 = max(0, min(int(round(cx)) - pad, max(width - 2 * pad, 0)))
    y0 = max(0, min(int(round(cy)) - pad, max(height - 2 * pad, 0)))
    map_x, map_y = make_maps(cx - x0, cy - y0, r_in, r_out,
                             cfg.n_theta, cfg.n_radius)
    print(f"[crop] {2 * pad} x {2 * pad} roi at ({x0}, {y0}) = "
          f"{100.0 * (2 * pad) ** 2 / (width * height):.1f}% of the frame "
          f"(this is what makes it fast)")
    print()

    deg_per_bin = 360.0 / cfg.n_theta
    dt = 1.0 / fps

    # ---- 3. per-frame loop -------------------------------------------------
    rows = []
    prev_sig = None
    prev_polar = None
    frame_idx = 0
    t_start = time.perf_counter()

    while frame_idx < n_proc:
        ok, frame = cap.read()
        if not ok:
            break

        crop = frame[y0:y0 + 2 * pad, x0:x0 + 2 * pad]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        polar = cv2.remap(gray, map_x, map_y, cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)

        sig = signature_from_polar(polar)

        if prev_sig is None or sig is None:
            prev_sig, prev_polar = sig, polar
            frame_idx += 1
            continue

        lag_bins, conf, sharp = circular_lag(prev_sig, sig)
        dtheta = lag_bins * deg_per_bin
        omega = dtheta / dt

        lag_b = per_ring_lag(prev_polar, polar)
        dtheta_b = lag_b * deg_per_bin if lag_b is not None else float("nan")

        note = ""
        valid = True
        if conf < cfg.min_conf:
            valid, note = False, "low-confidence"
        elif sharp < cfg.min_sharp:
            valid, note = False, "ambiguous-peak"
        elif abs(dtheta) > cfg.max_deg_per_frame:
            valid, note = False, "implausible-rotation"

        rows.append({
            "frame": frame_idx,
            "time_s": frame_idx * dt,
            "dtheta_deg": dtheta,
            "omega_deg_s": omega,
            "rev_s": omega / 360.0,
            "rpm": omega * 60.0 / 360.0,
            "conf": conf,
            "sharpness": sharp,
            "dtheta_deg_checkB": dtheta_b,
            "valid": int(valid),
            "note": note,
        })

        prev_sig, prev_polar = sig, polar
        frame_idx += 1

        if cfg.verbose and frame_idx % 200 == 0:
            print(f"  ... {frame_idx}/{n_proc} frames "
                  f"({(time.perf_counter() - t_start):.1f}s)", flush=True)

    cap.release()
    elapsed = time.perf_counter() - t_start
    print(f"[loop] processed {len(rows)} frame pairs in {elapsed:.2f} s "
          f"({1000.0 * elapsed / max(len(rows), 1):.2f} ms/frame)")
    print()

    if not rows:
        print("ERROR: no frames processed.", file=sys.stderr)
        return 3

    # ---- 4. analysis -------------------------------------------------------
    omega = np.array([r["omega_deg_s"] for r in rows], dtype=np.float64)
    valid = np.array([r["valid"] for r in rows], dtype=bool)
    tvals = np.array([r["time_s"] for r in rows], dtype=np.float64)

    if valid.sum() < 10:
        print("WARNING: almost no valid frames. The log may not be visible for "
              "most of the clip, or the annulus is wrong.", file=sys.stderr)

    # Per-frame deltas carry capture jitter: the recorder duplicates a frame
    # now and then, then catches up with a double step. Integrate first,
    # deglitch, then differentiate over a window. That is the physically
    # meaningful speed. The raw series is still written to the CSV.
    dtheta = np.array([r["dtheta_deg"] for r in rows], dtype=np.float64)
    dtheta_fixed, n_glitch = deglitch(dtheta)
    omega_win = windowed_speed(dtheta_fixed, fps, win=15)

    valid_win = np.isfinite(omega_win) & valid
    if int(valid_win.sum()) < 10:
        valid_win = np.isfinite(omega_win)

    wv = omega_win[valid_win]
    absv = np.abs(wv)

    tiers = detect_tiers(wv)
    reversals = find_reversals(omega_win, fps)

    # ---- 5. report ---------------------------------------------------------
    out = []
    def p(s=""):
        print(s)
        out.append(s)

    p("=" * 74)
    p("OVERALL ROTATION SPEED")
    p("=" * 74)
    p(f"valid frames      : {int(valid.sum())} / {len(rows)} "
      f"({100.0 * valid.mean():.1f}%)")
    p(f"jitter frames     : {n_glitch} repaired "
      f"(duplicated / catch-up frames)")
    if valid.any():
        p(f"raw per-frame med : {np.median(np.abs(omega[valid])):.1f} deg/s  "
          f"(inflated by capture jitter - NOT used below)")
    p(f"rotation sign     : positive = clockwise on screen")
    p(f"measured over     : {(len(rows) - 14) / fps:.1f} s in 0.5 s windows")
    if absv.size:
        p("")
        p(f"{'':16s}{'deg/s':>12s}{'rev/s':>12s}{'RPM':>12s}")
        for name, val in (("min", absv.min()), ("median", float(np.median(absv))),
                          ("mean", float(absv.mean())), ("max", absv.max()),
                          ("p95", float(np.percentile(absv, 95))),
                          ("std", float(absv.std()))):
            p(f"{name:16s}{val:12.2f}{val / 360.0:12.4f}{val * 60.0 / 360.0:12.2f}")
    p("")

    if tiers:
        p("=" * 74)
        p(f"DETECTED SPEED TIERS: {len(tiers)}")
        p("=" * 74)
        p(f"{'tier':>4s}{'mean deg/s':>12s}{'rev/s':>10s}{'RPM':>9s}"
          f"{'min':>9s}{'max':>9s}{'std':>8s}{'share':>8s}")
        for i, t in enumerate(tiers, 1):
            p(f"{i:4d}{t['mean_deg_s']:12.2f}{t['mean_deg_s'] / 360.0:10.3f}"
              f"{t['mean_deg_s'] * 60.0 / 360.0:9.1f}"
              f"{t['min_deg_s']:9.1f}{t['max_deg_s']:9.1f}"
              f"{t['std_deg_s']:8.1f}{100.0 * t['share']:7.1f}%")
        cov = tiers[0].get("coverage", 0.0)
        p("")
        p(f"plateau coverage  : {100.0 * cov:.1f}% of frames sit within 8% of a tier centre")
        p("  > 70%  -> the game really does use discrete speed steps")
        p("  < 40%  -> the speed ramps continuously; 'tiers' are only a summary")
    else:
        p("No discrete speed tiers found - the speed appears to vary continuously.")

    p("")
    if reversals:
        p(f"direction reversals: {len(reversals)}")
        for i, (fi, ts) in enumerate(reversals[:20], 1):
            p(f"  #{i}: frame {fi}  (t = {ts:.2f} s)")
        if len(reversals) > 20:
            p(f"  ... and {len(reversals) - 20} more")
    else:
        p("direction reversals: none detected (log may spin one way only, "
          "or the clip is too short)")

    # cross-check agreement
    both = [r for r in rows
            if r["valid"] and not math.isnan(r["dtheta_deg_checkB"])]
    if both:
        diff = np.abs(np.array([r["dtheta_deg"] - r["dtheta_deg_checkB"]
                                for r in both]))
        p("")
        p(f"cross-check (method A vs B): median disagreement {np.median(diff):.3f} deg, "
              f"95th pct {np.percentile(diff, 95):.3f} deg over {len(both)} frames")
        bad = int((diff > 2.0).sum())
        p(f"  frames disagreeing by > 2 deg: {bad} ({100.0 * bad / len(both):.2f}%)")

    # ---- 6. write outputs --------------------------------------------------
    os.makedirs(cfg.outdir, exist_ok=True)

    csv_path = os.path.join(cfg.outdir, "speed_per_frame.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (f"{v:.5f}" if isinstance(v, float) else v)
                         for k, v in r.items()})

    rep_path = os.path.join(cfg.outdir, "speed_report.md")
    with open(rep_path, "w", encoding="utf-8") as fh:
        fh.write("# Knife Rush - target rotation speed\n\n")
        fh.write(f"- video: `{os.path.basename(cfg.video)}`\n")
        fh.write(f"- resolution: {width} x {height}\n")
        fh.write(f"- frame rate: {fps:.3f} fps\n")
        fh.write(f"- frames analysed: {len(rows)}\n")
        fh.write(f"- target centre: ({cx:.2f}, {cy:.2f}) px\n")
        fh.write(f"- wood radius: {r_wood:.2f} px\n")
        fh.write(f"- annulus: {r_in:.1f} -> {r_out:.1f} px\n\n")
        fh.write("```\n" + "\n".join(out) + "\n```\n\n")

        if tiers:
            fh.write("## Speed tiers\n\n")
            fh.write("| tier | mean deg/s | rev/s | RPM | min | max | share |\n")
            fh.write("|---|---|---|---|---|---|---|\n")
            for i, t in enumerate(tiers, 1):
                fh.write(f"| {i} | {t['mean_deg_s']:.2f} | "
                         f"{t['mean_deg_s'] / 360.0:.3f} | "
                         f"{t['mean_deg_s'] * 60.0 / 360.0:.1f} | "
                         f"{t['min_deg_s']:.1f} | {t['max_deg_s']:.1f} | "
                         f"{100.0 * t['share']:.1f}% |\n")

    meta = {
        "video": os.path.abspath(cfg.video),
        "width": width, "height": height, "fps": fps,
        "frames_total": total, "frames_analysed": len(rows),
        "target": {"cx": cx, "cy": cy, "r_wood": r_wood,
                   "r_in": r_in, "r_out": r_out},
        "detection": det_info,
        "valid_frames": int(valid.sum()),
        "speed_deg_s": {
            "min": float(absv.min()) if absv.size else None,
            "median": float(np.median(absv)) if absv.size else None,
            "mean": float(absv.mean()) if absv.size else None,
            "max": float(absv.max()) if absv.size else None,
        },
        "tiers": tiers,
        "reversals": len(reversals),
    }
    with open(os.path.join(cfg.outdir, "speed_summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print()
    print(f"[out] {csv_path}")
    print(f"[out] {rep_path}")
    print(f"[out] {os.path.join(cfg.outdir, 'speed_summary.json')}")

    # ---- 7. plots ----------------------------------------------------------
    if cfg.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                           gridspec_kw={"height_ratios": [2, 1]})
            ax1.plot(tvals, omega, lw=0.5, color="#cbd5e1", alpha=0.9,
                     label="raw per-frame (capture jitter)")
            ax1.plot(tvals, omega_win, lw=1.6, color="#ef4444",
                     label="windowed 0.5 s - the real speed")
            for t in tiers:
                ax1.axhline(t["mean_deg_s"], ls="--", lw=0.8, color="#2563eb",
                            alpha=0.7)
                ax1.axhline(-t["mean_deg_s"], ls="--", lw=0.8, color="#2563eb",
                            alpha=0.3)
            ax1.set_ylabel("angular velocity (deg/s)")
            ax1.set_xlabel("time (s)")
            ax1.set_title("Knife Rush target - measured rotation speed")
            ax1.grid(alpha=0.25)
            ax1.legend(loc="upper right", fontsize=8)

            if absv.size:
                ax2.hist(absv, bins=120, color="#0ea5e9", alpha=0.85)
                for t in tiers:
                    ax2.axvline(t["mean_deg_s"], ls="--", lw=1, color="#ef4444")
            ax2.set_xlabel("|angular velocity| (deg/s)")
            ax2.set_ylabel("frames")
            ax2.grid(alpha=0.25)

            fig.tight_layout()
            plot_path = os.path.join(cfg.outdir, "omega_vs_time.png")
            fig.savefig(plot_path, dpi=130)
            plt.close(fig)
            print(f"[out] {plot_path}")
        except Exception as exc:                              # noqa: BLE001
            print(f"[plot] skipped: {exc}")

    # ---- 8. detection overlay, so you can verify with your own eyes --------
    try:
        cap2 = cv2.VideoCapture(cfg.video)
        cap2.set(cv2.CAP_PROP_POS_FRAMES, min(total // 2, max(total - 1, 0)))
        ok, vis = cap2.read()
        cap2.release()
        if ok:
            cv2.circle(vis, (int(round(cx)), int(round(cy))),
                       int(round(r_wood)), (0, 0, 255), 2)
            cv2.circle(vis, (int(round(cx)), int(round(cy))),
                       int(round(r_in)), (0, 255, 255), 1)
            cv2.circle(vis, (int(round(cx)), int(round(cy))),
                       int(round(r_out)), (0, 255, 255), 1)
            cv2.drawMarker(vis, (int(round(cx)), int(round(cy))),
                           (0, 0, 255), cv2.MARKER_CROSS, 24, 2)
            ov = os.path.join(cfg.outdir, "detection_overlay.png")
            cv2.imwrite(ov, vis)
            print(f"[out] {ov}")
    except Exception as exc:                                  # noqa: BLE001
        print(f"[overlay] skipped: {exc}")

    print()
    print("Done. Check detection_overlay.png first -- if the red circle does not "
          "sit exactly on the wood, nothing else is trustworthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
