#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_track.py  --  live MSS + OpenCV telemetry for the rotating target.

WHAT THIS IS
------------
An OBSERVER. It does not click, it does not press space, it does not touch the
game. It watches, measures, draws an overlay, and records everything to disk.

That order is deliberate. You cannot tune a throw you cannot see.

WHAT IT MEASURES
----------------
1. Target centre + radius on the real screen (auto-located, or given by hand).
2. Rotation angle, continuously unwrapped, and omega in deg/s.
3. Which angular cells are blocked, and where the free gaps are (0.25 deg).
4. The predicted "ghost gap" -- where a chosen gap will be T seconds from now.
5. A corridor motion signal between the target and the waiting knife.
6. A rolling buffer of raw frames, dumped to disk on a hotkey.

WHAT IT CANNOT DO
-----------------
It cannot measure the click->launch delay. There is no click. That number needs
an actuator, and an actuator needs a button you have decided to press. Separate
step, separate decision.

USAGE
-----
    python live_track.py                  # auto-locate the target and run
    python live_track.py --bench 5        # 5-second timing benchmark, no preview
    python live_track.py --cx 960 --cy 420 --r 230    # manual calibration
    python live_track.py --no-preview --duration 30   # headless logging

HOTKEYS (when the preview window has focus)
-------------------------------------------
    q / ESC   quit
    c         re-run auto-location
    d / F9    dump the frame ring buffer + a log slice to recordings/
    r         reset the omega history
    + / -     change the assumed flight time T by 5 ms (ghost-gap lead)
    p         pause / resume drawing

EVERYTHING IS WRITTEN TO THE PROJECT DRIVE. NOTHING TOUCHES C:.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import os
import sys
import time

# --------------------------------------------------------------------------- #
# Keep every byte on the project drive. Must happen before cv2 / mss import.
# --------------------------------------------------------------------------- #
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
import ctypes                                                 # noqa: E402

try:
    import mss                                                # noqa: E402
except ImportError:
    print("ERROR: mss is not installed.  pip install mss")
    raise SystemExit(2)

from find_speed import circular_lag, signature_from_polar     # noqa: E402

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #
N_THETA = 1440              # 0.25 deg per cell -- the bot grid, not the 60-line grid
N_RING = 32

TEX_IN, TEX_OUT = 0.55, 0.92      # wood texture: works while the target is wooden
PRO_IN, PRO_OUT = 0.95, 1.42      # protrusions: works on ANY target skin
OCC_IN_FRAC = 0.36                # 0.95 + 0.36*0.47 = 1.12R, matching the offline scan

MIN_RUN_DEG = 3.0
MAX_OBJ_DEG = 60.0
MIN_CONF = 0.30
MIN_SHARP = 0.04

IMPACT_GAME_DEG = 180.0           # the knife always arrives here (0 = up, clockwise)
DEFAULT_FLIGHT_T = 0.150          # assumed click->stick time for the ghost lead

RING_FRAMES = 40                  # ~40 x 400 x 400 x 3 bytes ~= 19 MB. RAM is tight.
PREVIEW_PERIOD = 1.0 / 25.0       # draw at 25 Hz; measurement never waits on drawing


# --------------------------------------------------------------------------- #
# Geometry helpers.  All maps are built in ROI-LOCAL coordinates.
# --------------------------------------------------------------------------- #
def build_geometry(cx_l: float, cy_l: float, r: float) -> dict:
    """Precompute remap grids once. Rebuild only when the calibration changes."""
    th = np.arange(N_THETA, dtype=np.float32) * (2.0 * math.pi / N_THETA)
    cos_t = np.cos(th)[:, None]
    sin_t = np.sin(th)[:, None]

    def grids(rin: float, rout: float) -> tuple:
        rr = np.linspace(r * rin, r * rout, N_RING).astype(np.float32)
        mx = (cx_l + rr[None, :] * cos_t).astype(np.float32)
        my = (cy_l + rr[None, :] * sin_t).astype(np.float32)
        return mx, my

    return {
        "r": float(r),
        "tex": grids(TEX_IN, TEX_OUT),
        "pro": grids(PRO_IN, PRO_OUT),
        "th": th,
    }


def polar(img: np.ndarray, mx: np.ndarray, my: np.ndarray) -> np.ndarray:
    return cv2.remap(img, mx, my, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)


def polar_to_game(a_deg: float) -> float:
    """Polar convention (+x = 0, clockwise) -> game convention (up = 0, clockwise)."""
    return (a_deg + 90.0) % 360.0


def runs_of(occ: np.ndarray, min_deg: float, max_deg: float):
    n = occ.size
    d = np.diff(np.r_[int(occ[-1]), occ.astype(int), int(occ[0])])
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    step = 360.0 / n
    out = []
    for s, e in zip(starts, ends):
        w = ((e - s) % n) * step
        if min_deg <= w <= max_deg:
            out.append((s * step, w))
    return out


def gaps_of(occ: np.ndarray, min_deg: float):
    n = occ.size
    d = np.diff(np.r_[int(occ[-1]), occ.astype(int), int(occ[0])])
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    step = 360.0 / n
    out = []
    for e, s in zip(ends[:-1], starts[1:]):
        w = ((s - e) % n) * step
        if w >= min_deg:
            out.append((e * step, w))
    return out


# --------------------------------------------------------------------------- #
# Screen location of the target
# --------------------------------------------------------------------------- #
def auto_locate(full: np.ndarray, verbose: bool = True):
    """Find the target without assuming its colour.

    The target is the largest compact non-sky object in the upper part of the
    screen. Works on the wooden log AND on the red/white bullseye, because it
    never tests for wood -- it tests for 'not sky' and then for roundness.
    """
    h, w = full.shape[:2]
    b = full[:, :, 0].astype(np.int16)
    g = full[:, :, 1].astype(np.int16)
    r = full[:, :, 2].astype(np.int16)
    sky = (b > r + 25) & (b > 90)
    obj = (~sky).astype(np.uint8)

    # Ignore the bottom HUD / terrain band and the extreme edges.
    obj[int(h * 0.80):, :] = 0
    obj[:, :int(w * 0.03)] = 0
    obj[:, int(w * 0.97):] = 0

    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))

    n, labels, stats, cents = cv2.connectedComponentsWithStats(obj, 8)
    if n <= 1:
        return None

    best, best_score = None, -1.0
    for i in range(1, n):
        x, y, bw, bh, area = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                              stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT],
                              stats[i, cv2.CC_STAT_AREA])
        if bw < 80 or bh < 80:
            continue
        aspect = min(bw, bh) / max(bw, bh)
        if aspect < 0.75:
            continue
        fill = area / float(bw * bh)
        if fill < 0.55:
            continue
        # favour big, round, well-filled blobs; penalise anything near the edges
        score = area * aspect * fill
        if score > best_score:
            best_score = score
            best = (i, x, y, bw, bh)

    if best is None:
        return None

    i, x, y, bw, bh = best
    cx = x + bw / 2.0
    cy = y + bh / 2.0
    r0 = 0.5 * (bw + bh) / 2.0

    # Radial refine: cast rays, stop where sky begins. The median defeats the
    # handful of rays that run through a protruding knife.
    radii = []
    for k in range(720):
        a = k * (2.0 * math.pi / 720.0)
        ca, sa = math.cos(a), math.sin(a)
        hit = None
        for d in range(int(r0 * 0.6), int(r0 * 1.6)):
            px, py = int(cx + d * ca), int(cy + d * sa)
            if px < 1 or py < 1 or px >= w - 1 or py >= h - 1:
                break
            if sky[py, px]:
                hit = d
                break
        if hit is not None:
            radii.append(hit)
    if len(radii) < 200:
        return None
    r = float(np.median(radii))

    if verbose:
        print(f"[locate] centre ({cx:.1f}, {cy:.1f})  radius {r:.1f}  "
              f"({len(radii)}/720 rays)")
    return float(cx), float(cy), r


def refine_circle(full: np.ndarray, cx: float, cy: float, r0: float,
                  n_rays: int = 720):
    """Sharpen a rough (centre, radius) against the actual target edge.

    Hough reported r=106.9 for a target it had measured at r=124.5 a minute
    earlier -- 15% off. Every annulus in this program is a multiple of R, so a
    15% radius error drags the occupancy scan down into the wood and every
    angle then reads 'knife'.

    Rays leave the centre and stop at the first sky pixel. Rays crossing a
    protruding knife travel further, so the MEDIAN is the rim. The edge points
    are then fed to a least-squares circle fit, which corrects the centre as
    well as the radius.
    """
    h, w = full.shape[:2]
    b = full[:, :, 0].astype(np.int16)
    rc = full[:, :, 2].astype(np.int16)
    sky = (b > rc + 25) & (b > 90)

    lo = int(max(4, r0 * 0.55))
    hi = int(min(min(w, h) * 0.5, r0 * 1.70))
    if hi <= lo:
        return float(cx), float(cy), float(r0)

    pts, radii = [], []
    for k in range(n_rays):
        a = k * (2.0 * math.pi / n_rays)
        ca, sa = math.cos(a), math.sin(a)
        for d in range(lo, hi):
            px, py = int(cx + d * ca), int(cy + d * sa)
            if px < 1 or py < 1 or px >= w - 1 or py >= h - 1:
                break
            if sky[py, px]:
                radii.append(d)
                pts.append((px, py))
                break
    if len(radii) < 120:
        return float(cx), float(cy), float(r0)

    rr = float(np.median(radii))
    keep = [p for p, d in zip(pts, radii) if abs(d - rr) < 0.10 * rr]
    if len(keep) >= 60:
        P = np.asarray(keep, dtype=np.float64)
        A = np.c_[2.0 * P[:, 0], 2.0 * P[:, 1], np.ones(len(P))]
        rhs = (P ** 2).sum(axis=1)
        try:
            sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
            cx2, cy2 = float(sol[0]), float(sol[1])
            r2 = math.sqrt(max(1.0, sol[2] + cx2 ** 2 + cy2 ** 2))
            if (abs(cx2 - cx) < 0.15 * r0 and abs(cy2 - cy) < 0.15 * r0
                    and 0.80 * rr < r2 < 1.25 * rr):
                return cx2, cy2, r2
        except Exception:                                      # noqa: BLE001
            pass
    return float(cx), float(cy), rr


def sky_annulus_frac(full: np.ndarray, cx: float, cy: float,
                     r: float, n: int = 180) -> float:
    """Fraction of the ring just outside a candidate that is sky-coloured.

    This is the guard against false positives. HoughCircles will happily
    invent a circle on a screenshot of an editor -- it found one at (145, 219)
    r=90 with 0.7% sky on screen. A real target floats on open sky, so the
    annulus around it reads blue. Anything else is not the target.
    """
    ang = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    rs = np.array([1.08, 1.18, 1.28, 1.38])
    xs = (cx + r * np.outer(rs, np.cos(ang))).astype(np.int32)
    ys = (cy + r * np.outer(rs, np.sin(ang))).astype(np.int32)
    h, w = full.shape[:2]
    ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    if ok.sum() == 0:
        return 0.0
    px = full[ys[ok], xs[ok]]
    b = px[:, 0].astype(np.int16)
    rc = px[:, 2].astype(np.int16)
    return float((((b > rc + 25) & (b > 90))).mean())


def screen_sky_frac(full: np.ndarray) -> float:
    b = full[:, :, 0].astype(np.int16)
    rc = full[:, :, 2].astype(np.int16)
    return float(((b > rc + 25) & (b > 90)).mean())


def hough_candidates(full: np.ndarray) -> list:
    """Every plausible circle, largest first. Validation happens in the
    caller, which knows what a target actually looks like."""
    h, w = full.shape[:2]
    scale = 900.0 / max(w, h)
    small = cv2.resize(full, (int(w * scale), int(h * scale)),
                       interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (9, 9), 2)
    rmin, rmax = int(40 * scale), int(340 * scale)

    out = []
    for p2 in (75, 60, 48, 38, 30):
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.5,
                                   minDist=int(small.shape[1] * 0.30),
                                   param1=120, param2=p2,
                                   minRadius=rmin, maxRadius=rmax)
        if circles is None:
            continue
        for c in np.asarray(circles[0], dtype=np.float32):
            if c[1] > small.shape[0] * 0.82:
                continue
            out.append((float(c[0] / scale), float(c[1] / scale),
                        float(c[2] / scale)))
        if out:
            break
    out.sort(key=lambda t: -t[2])
    return out


def auto_locate_candidates(full: np.ndarray) -> list:
    got = auto_locate(full, verbose=False)
    return [got] if got is not None else []


def find_target(full: np.ndarray, verbose: bool = True):
    """Locate the target and refuse anything that is not floating on sky."""
    total_sky = screen_sky_frac(full)
    rejected = []
    for name, finder in (("hough", hough_candidates),
                         ("blob", auto_locate_candidates)):
        for raw in finder(full):
            cx, cy, r = refine_circle(full, raw[0], raw[1], raw[2])
            sky = sky_annulus_frac(full, cx, cy, r)
            if sky < 0.35:
                rejected.append(f"{name} ({cx:.0f},{cy:.0f}) r={r:.0f} "
                                f"sky={100 * sky:.0f}%")
                continue
            if verbose:
                print(f"[locate] accepted {name} ({cx:.1f}, {cy:.1f}) "
                      f"r={r:.1f} -- {100 * sky:.0f}% sky around it, "
                      f"screen {100 * total_sky:.0f}% sky")
                if abs(r - raw[2]) > 0.04 * r:
                    print(f"[locate]   radius corrected {raw[2]:.1f} -> {r:.1f} "
                          f"({100.0 * (r - raw[2]) / raw[2]:+.0f}%)")
            return cx, cy, r
    if verbose:
        if rejected:
            print(f"[locate] rejected {len(rejected)} candidate(s):")
            for line in rejected[:4]:
                print(f"[locate]   {line}")
        print(f"[locate] screen is {100 * total_sky:.1f}% sky; "
              f"the game looks like 40-60%")
    return None


def hough_locate(full: np.ndarray, verbose: bool = True):
    """Kept for the earlier single-shot callers; validated like everything else."""
    return find_target(full, verbose)


def _vk_pressed(vk: int, prev: dict) -> bool:
    """Edge-detect a global key press.

    The overlay is click-through (WS_EX_TRANSPARENT) so it can never take
    keyboard focus while the game has it. Polling GetAsyncKeyState is the only
    way the user can command a tool that is deliberately not focusable.
    """
    try:
        now = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:                                          # noqa: BLE001
        return False
    was = prev.get(vk, False)
    prev[vk] = now
    return now and not was


VK_F8, VK_F9, VK_F10 = 0x77, 0x78, 0x79


class Hud:
    """Click-through transparent overlay drawn straight onto the game.

    Two rules, both forced by the measurement physics:

    1. NEVER draw between 0.92R and 1.42R. That band is what the occupancy
       scan reads; ink there would be measured as a knife.
    2. Ink inside the capture box is BLUE-dominant (B > R + 25) so that even
       if it is photographed, the sky mask files it as background, not as an
       obstacle.

    Status text and the live dot sit OUTSIDE the capture rectangle, where they
    cannot be photographed at all.
    """

    KEY = "#ff00ff"       # magenta = transparent key colour
    INK = "#00d8ff"       # cyan-blue: reads as 'sky' to the mask
    GO = "#31ff6b"
    BAD = "#ff3b3b"

    def __init__(self, sw: int, sh: int, enabled: bool = True,
                 use_wda: bool = True):
        self.ok = False
        self.closed = False
        if not enabled:
            self.closed = True
            return
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.overrideredirect(True)
            self.root.geometry(f"{sw}x{sh}+0+0")
            self.root.attributes("-topmost", True)
            self.root.attributes("-transparentcolor", self.KEY)
            self.canvas = tk.Canvas(self.root, width=sw, height=sh,
                                    bg=self.KEY, highlightthickness=0, bd=0)
            self.canvas.pack()
            self.root.update_idletasks()

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            GWL_EXSTYLE = -20
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, ex | 0x80000 | 0x20 | 0x08000000)
                # LAYERED | TRANSPARENT | NOACTIVATE : clicks pass through and
                # it never steals focus from the game.
            try:
                if use_wda:
                    ok = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
                    print("[hud] display affinity WDA_EXCLUDEFROMCAPTURE: "
                          f"{'accepted' if ok else 'REFUSED'}")
                else:
                    print("[hud] display affinity disabled "
                          "(--no-wda): the overlay WILL be captured")
            except Exception as exc:                           # noqa: BLE001
                print(f"[hud] display affinity failed ({exc})")
            self.ok = True
            print("[hud] overlay active (click-through, lines over the game)")
        except Exception as exc:                               # noqa: BLE001
            print(f"[hud] unavailable ({exc}) -- no overlay")

    def verify(self, sct, mon: dict) -> bool:
        """Prove the key colour is actually transparent before trusting it.

        If -transparentcolor silently fails, this window becomes an opaque
        magenta sheet covering the entire game -- the worst possible outcome.
        Photograph a corner we never draw in and check it is not magenta.
        """
        if not self.ok or self.closed:
            return True
        try:
            self.root.update()
            time.sleep(0.10)
            reg = {"left": mon["left"] + 4, "top": mon["top"] + 4,
                   "width": 16, "height": 16}
            raw = sct.grab(reg)
            px = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(-1, 4)[:, :3]
            b = float(px[:, 0].mean())
            g = float(px[:, 1].mean())
            r = float(px[:, 2].mean())
            if b > 200 and r > 200 and g < 80:
                print("[hud] WARNING: transparency FAILED -- the overlay is an")
                print("      opaque magenta sheet. Disabling it so you can still")
                print("      see the game. Tell me and I will fix the mechanism.")
                self.close()
                return False
            print(f"[hud] transparency verified (corner rgb "
                  f"{r:.0f},{g:.0f},{b:.0f})")
            return True
        except Exception as exc:                               # noqa: BLE001
            print(f"[hud] verify skipped ({exc})")
            return True

    def draw(self, cx: float, cy: float, r: float, bbox: dict, d: dict) -> None:
        if not self.ok or self.closed:
            return
        c = self.canvas
        ink = self.INK
        try:
            c.delete("all")
            x0, y0 = bbox["left"], bbox["top"]
            x1, y1 = x0 + bbox["width"], y0 + bbox["height"]

            c.create_rectangle(x0, y0, x1, y1, outline=ink, width=2)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=ink, width=2)

            for a, _w in d["obs"]:
                pa = math.radians(a)
                c.create_line(cx + r * 1.44 * math.cos(pa),
                              cy + r * 1.44 * math.sin(pa),
                              cx + r * 1.50 * math.cos(pa),
                              cy + r * 1.50 * math.sin(pa), fill=ink, width=2)
            for a, w in d["gaps"]:
                pa = math.radians(a)
                c.create_text(cx + r * 1.54 * math.cos(pa),
                              cy + r * 1.54 * math.sin(pa),
                              text=f"{w:.0f}", fill=ink,
                              font=("Consolas", 9, "bold"))
            if d["spokes"]:
                for kk in range(60):
                    pa = math.radians(kk * 6.0 - 90.0)
                    c.create_line(cx + r * 1.44 * math.cos(pa),
                                  cy + r * 1.44 * math.sin(pa),
                                  cx + r * 1.55 * math.cos(pa),
                                  cy + r * 1.55 * math.sin(pa), fill=ink)
                    c.create_text(cx + r * 1.62 * math.cos(pa),
                                  cy + r * 1.62 * math.sin(pa),
                                  text=f"L{kk + 1}", fill=ink,
                                  font=("Consolas", 7))

            if d["alive"]:
                dot_y = y0 - 30 if y0 > 60 else y1 + 22
                c.create_oval(x0 + 4, dot_y - 5, x0 + 14, dot_y + 5,
                              fill=self.GO, outline="")
                c.create_text(x0 + 20, dot_y, anchor="w",
                              text=f"LIVE {d['fps']:.1f}fps  w {d['omega']:.0f}d/s"
                                   f"  conf {d['conf']:.2f}  gap {d['gap']:.0f}",
                              fill=self.GO, font=("Consolas", 10, "bold"))
                c.create_text(x0 + 4, dot_y + 16, anchor="w",
                              text=f"capturing {bbox['width']}x{bbox['height']}"
                                   f"  (this box)",
                              fill="#c8c8c8", font=("Consolas", 9))
            self.root.update()
        except Exception:                                       # noqa: BLE001
            pass

    def close(self) -> None:
        if self.ok and not self.closed:
            self.closed = True
            try:
                self.root.destroy()
            except Exception:                                   # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# Preview window
# --------------------------------------------------------------------------- #
class Preview:
    """Tkinter preview.

    WHY NOT cv2.imshow: the OpenCV wheel on this machine is built without
    HighGUI, so imshow() raises 'The function is not implemented'. Tk + PIL is
    already installed and works. The window is refreshed at ~25 Hz and is
    deliberately independent of the capture rate -- drawing must never throttle
    measurement.
    """

    def __init__(self, scale: float = 0.6, pos=None, enabled: bool = True):
        self.ok = False
        self.key = None
        self.scale = scale
        self.pos = pos
        self.closed = False
        self.item = None
        if not enabled:
            self.closed = True
            return
        try:
            import tkinter as tk
            from PIL import Image, ImageTk
            self.tk, self.Image, self.ImageTk = tk, Image, ImageTk

            self.root = tk.Tk()
            self.root.title("knife-rush telemetry    [q]uit [c]alib [d]ump [r]eset [+/-]T [p]review")
            self.canvas = tk.Canvas(self.root, width=360, height=270,
                                    highlightthickness=0, bg="black")
            self.canvas.pack()
            self.root.bind("<Key>", self._on_key)
            self.root.protocol("WM_DELETE_WINDOW", self.close)
            self.ok = True
        except Exception as exc:                                  # noqa: BLE001
            print(f"[preview] unavailable ({exc}) -- running headless")

    def _on_key(self, event) -> None:
        self.key = event.keysym

    def show(self, vis):
        if not self.ok or self.closed:
            return None
        h, w = vis.shape[:2]
        s = self.scale
        small = cv2.resize(vis, (max(1, int(w * s)), max(1, int(h * s))),
                           interpolation=cv2.INTER_NEAREST)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        photo = self.ImageTk.PhotoImage(self.Image.fromarray(rgb))
        if self.item is None:
            self.item = self.canvas.create_image(0, 0, anchor="nw", image=photo)
            self.canvas.config(width=rgb.shape[1], height=rgb.shape[0])
            where = f"+{int(self.pos[0])}+{int(self.pos[1])}" if self.pos else ""
            self.root.geometry(f"{rgb.shape[1]}x{rgb.shape[0]}{where}")
        else:
            self.canvas.itemconfig(self.item, image=photo)
        self.canvas.image = photo
        self.root.update()
        k, self.key = self.key, None
        return k

    def close(self) -> None:
        if self.ok and not self.closed:
            self.closed = True
            try:
                self.root.destroy()
            except Exception:                                     # noqa: BLE001
                pass


def roi_for(cx: float, cy: float, r: float, sw: int, sh: int,
            pad_x: float = 1.60, pad_up: float = 1.60,
            pad_down: float = 3.05) -> dict:
    """The capture box, in ABSOLUTE screen coordinates.

    Shape is deliberately narrow and tall:

        horizontal  +-1.60 R   nothing exists past 1.42 R (protrusion ring)
        above       + 1.60 R   nothing above the target either
        below       + 3.05 R   the waiting knife spans 2.24 R .. 2.86 R

    The old value of 2.35 R below the centre chopped the waiting knife in half,
    which would have silently broken any launch/flight measurement.
    """
    x0 = int(max(0, cx - pad_x * r))
    x1 = int(min(sw, cx + pad_x * r))
    y0 = int(max(0, cy - pad_up * r))
    y1 = int(min(sh, cy + pad_down * r))
    return {"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}


def place_preview(bbox: dict, sw: int, sh: int, scale: float):
    """Put the preview window somewhere that does NOT overlap the capture box.

    If it overlaps, MSS screenshots the preview of the game instead of the game.
    That is a feedback loop, and it is the kind of bug that looks like 'the
    tracker is drunk' rather than 'the window is in the way'.
    """
    pw = int(bbox["width"] * scale)
    ph = int(bbox["height"] * scale)
    m = 10
    x0, y0 = bbox["left"], bbox["top"]
    x1, y1 = x0 + bbox["width"], y0 + bbox["height"]

    def free(x: int, y: int) -> bool:
        if x < 0 or y < 0 or x + pw > sw or y + ph > sh:
            return False
        return (x + pw <= x0) or (x >= x1) or (y + ph <= y0) or (y >= y1)

    for cand in ((x1 + m, y0), (x0 - pw - m, y0),
                 (x0, y1 + m), (x0, y0 - ph - m),
                 (sw - pw - m, sh - ph - m)):
        if free(*cand):
            return cand
    return max(0, sw - pw - m), max(0, sh - ph - m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cx", type=float, default=None)
    ap.add_argument("--cy", type=float, default=None)
    ap.add_argument("--r", type=float, default=None)
    ap.add_argument("--preview", action="store_true",
                    help="also open the captured-image preview window "
                         "(off by default: the HUD draws on the game instead)")
    ap.add_argument("--no-hud", action="store_true",
                    help="do not draw the overlay on the game")
    ap.add_argument("--no-wda", action="store_true",
                    help="do not hide the overlay from screen capture "
                         "(needed to screenshot-check the overlay geometry)")
    ap.add_argument("--hud-fps", type=float, default=30.0,
                    help="overlay redraw rate (default 30)")
    ap.add_argument("--bench", type=float, default=None,
                    help="run N seconds with no preview and report timings")
    ap.add_argument("--duration", type=float, default=0.0,
                    help="stop after N seconds (0 = run until quit)")
    ap.add_argument("--flight-t", type=float, default=DEFAULT_FLIGHT_T)
    ap.add_argument("--outdir", default="recordings")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--wait", type=float, default=90.0,
                    help="seconds to wait for the target to appear (0 = give up at once)")
    ap.add_argument("--preview-scale", type=float, default=0.6)
    ap.add_argument("--ring", type=int, default=20,
                    help="frames kept in the dump ring buffer (RAM scales with r^2)")
    ap.add_argument("--pad-x", type=float, default=1.60,
                    help="ROI half-width, in units of R")
    ap.add_argument("--pad-up", type=float, default=1.60,
                    help="ROI above centre, in units of R")
    ap.add_argument("--pad-down", type=float, default=3.05,
                    help="ROI below centre, in units of R (waiting knife needs 2.86)")
    ap.add_argument("--max-fps", type=float, default=60.0,
                    help="cap the loop rate; 0 = uncapped (will peg a core)")
    args = ap.parse_args()
    args.no_preview = not args.preview

    os.makedirs(args.outdir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")

    if args.bench:
        args.no_preview = True
        args.no_hud = True
        args.duration = args.bench

    sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
    mon = sct.monitors[1]
    sw, sh = mon["width"], mon["height"]
    print(f"[screen] {sw} x {sh}")

    # ---- calibration ----------------------------------------------------- #
    if args.cx is not None and args.cy is not None and args.r is not None:
        cx, cy, r = args.cx, args.cy, args.r
        print(f"[locate] manual centre ({cx:.1f}, {cy:.1f}) radius {r:.1f}")
    else:
        deadline = time.time() + args.wait
        last_note = 0.0
        cx = cy = r = None
        while True:
            full = np.array(sct.grab(mon))[:, :, :3].copy()
            got = find_target(full, verbose=False)
            if got is not None:
                cx, cy, r = got
                print(f"[locate] centre ({cx:.1f}, {cy:.1f})  radius {r:.1f}")
                b_ = full[:, :, 0].astype(np.int16)
                r_ = full[:, :, 2].astype(np.int16)
                sky_pct = 100.0 * float(((b_ > r_ + 25) & (b_ > 90)).mean())
                print(f"[locate] screen is {sky_pct:.1f}% sky "
                      f"(game frames run 40-60%)")
                break
            now = time.time()
            if args.wait <= 0 or now > deadline:
                b_ = full[:, :, 0].astype(np.int16)
                r_ = full[:, :, 2].astype(np.int16)
                sky_pct = 100.0 * float(((b_ > r_ + 25) & (b_ > 90)).mean())
                print("ERROR: could not locate the target automatically.")
                find_target(full, verbose=True)
                print(f"       screen is only {sky_pct:.1f}% sky -- the game target")
                print("       does not appear to be visible.")
                print("       Alternatively pass --cx --cy --r from a screenshot.")
                return 2
            if now - last_note > 4.0:
                last_note = now
                print(f"[wait] looking for the target... "
                      f"{int(deadline - now)}s left")
            time.sleep(0.6)

    with open(os.path.join(_PROJECT_ROOT, "measurements", "calibration.json"),
              "w", encoding="utf-8") as fh:
        json.dump({"cx": cx, "cy": cy, "r": r,
                   "screen": [sw, sh], "taken": stamp}, fh, indent=2)

    # ---- ROI ------------------------------------------------------------- #
    bbox = roi_for(cx, cy, r, sw, sh, args.pad_x, args.pad_up, args.pad_down)
    x0, y0 = bbox["left"], bbox["top"]
    print(f"[roi] {bbox['width']} x {bbox['height']} at ({x0}, {y0})  "
          f"= {100.0 * bbox['width'] * bbox['height'] / (sw * sh):.1f}% of screen")

    # A still picture of exactly what will be captured, drawn on the full screen.
    # Written BEFORE the preview window exists, so it cannot photograph itself.
    try:
        snap = np.array(sct.grab(mon))[:, :, :3].copy()
        cv2.rectangle(snap, (bbox["left"], bbox["top"]),
                      (bbox["left"] + bbox["width"], bbox["top"] + bbox["height"]),
                      (0, 255, 0), 2)
        for label, org in (("CAPTURE ROI", (bbox["left"] + 8, bbox["top"] + 22)),):
            cv2.putText(snap, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
            cv2.putText(snap, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imwrite(os.path.join(_PROJECT_ROOT, "measurements", "tracking_area.png"),
                    snap)
        print("[roi] wrote measurements/tracking_area.png")
    except Exception as exc:                                      # noqa: BLE001
        print(f"[roi] snapshot skipped ({exc})")

    preview = Preview(args.preview_scale,
                      place_preview(bbox, sw, sh, args.preview_scale),
                      enabled=not args.no_preview)
    hud = Hud(sw, sh, enabled=not args.no_hud, use_wda=not args.no_wda)
    hud.verify(sct, mon)

    cxl, cyl = cx - x0, cy - y0
    geo = build_geometry(cxl, cyl, r)
    mx_tex, my_tex = geo["tex"]
    mx_pro, my_pro = geo["pro"]

    # corridor between the target and the waiting knife
    cor_y0 = int(cyl + r * 1.02)
    cor_y1 = int(min(bbox["height"], cyl + r * 1.95))
    cor_x0 = int(max(0, cxl - 0.22 * r))
    cor_x1 = int(min(bbox["width"], cxl + 0.22 * r))

    # ---- state ----------------------------------------------------------- #
    prev_tex = prev_pro = None
    angle = 0.0
    angle_hist = collections.deque(maxlen=120)     # (t, angle)
    last_t = None
    flight_t = args.flight_t
    ring = collections.deque(maxlen=max(1, args.ring))
    rows = []
    fps_t0 = time.perf_counter()
    fps_n = 0
    fps_shown = 0.0
    last_show = 0.0
    show_spokes = False
    last_hud = 0.0
    hk = {}
    hud_period = 1.0 / max(1.0, args.hud_fps)
    omega_fit = 0.0
    t_start = time.perf_counter()

    csv_path = os.path.join(args.outdir, f"live_{stamp}.csv")
    csv_fh = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(csv_fh)
    writer.writerow(["t", "dt_ms", "fps", "angle_polar_deg", "dtheta_deg",
                     "omega_inst_dps", "omega_fit_dps", "conf_tex", "sharp_tex",
                     "conf_pro", "n_obstacles", "widest_gap_deg",
                     "widest_gap_game_deg", "corridor_motion"])

    timings = collections.defaultdict(list)
    _where = ("overlay on the game" if hud.ok else "headless")
    if preview.ok and not args.no_preview:
        _where += " + preview window"
    print(f"[run] {_where}.  F10 stop | F9 dump | F8 spokes")

    try:
        while True:
            t_now = time.perf_counter()
            if args.duration and t_now - t_start > args.duration:
                break

            t_a = time.perf_counter()
            raw = sct.grab(bbox)
            frame = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(
                raw.height, raw.width, 4)[:, :, :3].copy()
            t_b = time.perf_counter()

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            t_c = time.perf_counter()

            p_tex = polar(gray, mx_tex, my_tex)
            p_pro = polar(gray, mx_pro, my_pro)
            t_d = time.perf_counter()

            sig_tex = signature_from_polar(p_tex)
            sig_pro = signature_from_polar(p_pro)

            dtheta = 0.0
            conf_tex = sharp_tex = 0.0
            conf_pro = 0.0
            if prev_tex is not None and sig_tex is not None and prev_tex is not None:
                lag, conf_tex, sharp_tex = circular_lag(prev_tex, sig_tex)
                dtheta = lag * (360.0 / N_THETA)

            if prev_pro is not None and sig_pro is not None:
                lag2, conf_pro, _ = circular_lag(prev_pro, sig_pro)
                # protrusion ring is the fallback when the texture is flat
                # (bullseye skin has no angular texture at all)
                if conf_tex < MIN_CONF and conf_pro > conf_tex:
                    dtheta = lag2 * (360.0 / N_THETA)
                    conf_tex = conf_pro

            if sig_tex is not None:
                prev_tex = sig_tex
            if sig_pro is not None:
                prev_pro = sig_pro

            good = (conf_tex >= MIN_CONF and sharp_tex >= MIN_SHARP
                    and abs(dtheta) < 90.0)
            if not good:
                dtheta = 0.0            # never integrate garbage into the angle
            angle = (angle + dtheta) % 360.0

            dt = (t_now - last_t) if last_t else 0.0
            last_t = t_now
            omega_inst = (dtheta / dt) if dt > 1e-6 and good else 0.0

            angle_hist.append((t_now, angle))
            if len(angle_hist) >= 8 and good:
                # least-squares slope of unwrapped angle over the last ~0.35 s
                t_arr = np.array([a[0] for a in angle_hist])
                a_arr = np.array([a[1] for a in angle_hist])
                keep = t_arr >= t_arr[-1] - 0.35
                t_arr, a_arr = t_arr[keep], a_arr[keep]
                if t_arr.size >= 6:
                    # unwrap before fitting
                    un = np.unwrap(np.radians(a_arr))
                    A = np.column_stack([t_arr - t_arr[0], np.ones_like(t_arr)])
                    slope = np.linalg.lstsq(A, un, rcond=None)[0][0]
                    omega_fit = math.degrees(float(slope))

            # ---- occupancy / gaps ---------------------------------------- #
            # Build the sky test ONCE on the small ROI, then remap the 1-channel
            # mask. Remapping a 3-channel image here costs 3x for no benefit.
            b_ch, _, r_ch = cv2.split(frame)
            sky_u8 = ((cv2.subtract(b_ch, r_ch) > 25) & (b_ch > 90)).astype(np.uint8)
            p_sky = cv2.remap(sky_u8, mx_pro, my_pro, cv2.INTER_NEAREST,
                              borderMode=cv2.BORDER_REPLICATE)
            occ_full = (p_sky == 0).mean(axis=1) > 0.5

            i0 = int(N_RING * OCC_IN_FRAC)
            occ = occ_full[i0:]           # only the outer part of the PRO ring
            obs = runs_of(occ, MIN_RUN_DEG, MAX_OBJ_DEG)
            gaps = gaps_of(occ, MIN_RUN_DEG)
            widest = max(gaps, key=lambda g: g[1]) if gaps else (0.0, 0.0)
            t_e = time.perf_counter()

            # ---- corridor motion ----------------------------------------- #
            cor = frame[cor_y0:cor_y1, cor_x0:cor_x1]
            if cor.size:
                cb = cor[:, :, 0].astype(np.int16)
                cr = cor[:, :, 2].astype(np.int16)
                corridor = float((~((cb > cr + 25) & (cb > 90))).mean())
            else:
                corridor = 0.0

            ring.append(frame.copy())

            fps_n += 1
            if t_now - fps_t0 >= 0.5:
                fps_shown = fps_n / (t_now - fps_t0)
                fps_n = 0
                fps_t0 = t_now

            rows.append((round(t_now - t_start, 4), round(dt * 1000.0, 2),
                         round(fps_shown, 1), round(polar_to_game(angle), 2),
                         round(dtheta, 3), round(omega_inst, 1),
                         round(omega_fit, 1), round(conf_tex, 3),
                         round(sharp_tex, 3), round(conf_pro, 3), len(obs),
                         round(widest[1], 2),
                         round(polar_to_game(widest[0] + widest[1] / 2.0), 2),
                         round(corridor, 4)))
            if len(rows) >= 60:
                writer.writerows(rows)
                csv_fh.flush()
                rows.clear()

            for k, v in (("grab", t_b - t_a), ("gray", t_c - t_b),
                         ("polar", t_d - t_c), ("analyse", t_e - t_d)):
                timings[k].append(v)

            # ---- preview (Tk; this OpenCV has no HighGUI) ------------------ #
            key = None
            if preview.ok and not args.no_preview:
                now_p = time.perf_counter()
                if now_p - last_show >= PREVIEW_PERIOD:
                    last_show = now_p
                    vis = frame.copy()
                    green, cyan, red, yellow = ((0, 255, 0), (255, 200, 0),
                                                (0, 0, 255), (0, 255, 255))
                    cv2.circle(vis, (int(cxl), int(cyl)), int(r), green, 2)
                    cv2.circle(vis, (int(cxl), int(cyl)), int(r * PRO_IN), cyan, 1)
                    cv2.circle(vis, (int(cxl), int(cyl)), int(r * PRO_OUT), cyan, 1)
                    cv2.line(vis, (int(cxl), int(cyl)),
                             (int(cxl), int(cyl + r * 1.55)), (0, 0, 255), 1)

                    for a, w in obs:
                        mid = math.radians(a + w / 2.0)
                        for kk in (PRO_IN, PRO_OUT):
                            p = (int(cxl + r * kk * math.cos(mid)),
                                 int(cyl + r * kk * math.sin(mid)))
                            cv2.circle(vis, p, 2, red, -1)

                    for a, w in gaps:
                        mid = math.radians(a + w / 2.0)
                        pt = (int(cxl + r * 1.48 * math.cos(mid)),
                              int(cyl + r * 1.48 * math.sin(mid)))
                        is_best = (w == widest[1])
                        cv2.putText(vis, f"{w:.0f}", pt, cv2.FONT_HERSHEY_SIMPLEX,
                                    0.45, green if is_best else yellow,
                                    2 if is_best else 1)

                    # ghost gap: where the widest gap will be T seconds from now
                    if widest[1] > 0 and abs(omega_fit) > 5.0:
                        ghost = widest[0] + widest[1] / 2.0 + omega_fit * flight_t
                        gm = math.radians(ghost)
                        p1 = (int(cxl + r * 0.98 * math.cos(gm)),
                              int(cyl + r * 0.98 * math.sin(gm)))
                        p2 = (int(cxl + r * 1.5 * math.cos(gm)),
                              int(cyl + r * 1.5 * math.sin(gm)))
                        cv2.line(vis, p1, p2, (255, 0, 255), 2)
                        cv2.putText(vis, "ghost", (p2[0] + 3, p2[1]),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1)

                    # ---- capture-area indicator ---------------------------
                    # The window edge IS the capture edge. The border is not
                    # decoration: everything inside it is what gets read, and
                    # everything outside it is never looked at.
                    h_vis, w_vis = vis.shape[:2]
                    cv2.rectangle(vis, (0, 0), (w_vis, 60), (0, 0, 0), -1)
                    blink = (int(time.perf_counter() * 2.0) % 2) == 0
                    if blink:
                        cv2.circle(vis, (14, 38), 6, (0, 0, 255), -1)
                    else:
                        cv2.circle(vis, (14, 38), 6, (0, 0, 255), 1)
                    share = 100.0 * bbox["width"] * bbox["height"] / (sw * sh)
                    l1 = (f"{'LIVE' if blink else '    '}  {fps_shown:5.1f} fps   "
                          f"w {omega_fit:7.1f} deg/s   conf {conf_tex:0.2f}   "
                          f"obs {len(obs):2d}   gap {widest[1]:5.1f}")
                    l2 = (f"capturing {bbox['width']}x{bbox['height']} at "
                          f"({bbox['left']},{bbox['top']}) = {share:.1f}% of screen"
                          f"    T {flight_t * 1000:.0f} ms")
                    cv2.putText(vis, l1, (28, 24), cv2.FONT_HERSHEY_SIMPLEX,
                                0.45, (255, 255, 255), 1)
                    cv2.putText(vis, l2, (28, 48), cv2.FONT_HERSHEY_SIMPLEX,
                                0.42, (0, 255, 0), 1)

                    if show_spokes:
                        for kk in range(60):
                            pa = math.radians(kk * 6.0 - 90.0)
                            p1 = (int(cxl + r * 1.00 * math.cos(pa)),
                                  int(cyl + r * 1.00 * math.sin(pa)))
                            p2 = (int(cxl + r * 1.50 * math.cos(pa)),
                                  int(cyl + r * 1.50 * math.sin(pa)))
                            cv2.line(vis, p1, p2, (150, 150, 150), 1)
                            lp = (int(cxl + r * 1.56 * math.cos(pa)),
                                  int(cyl + r * 1.56 * math.sin(pa)))
                            cv2.putText(vis, f"L{kk + 1}", lp,
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.28,
                                        (210, 210, 210), 1)

                    cv2.rectangle(vis, (0, 0), (w_vis - 1, h_vis - 1), (0, 255, 0), 3)
                    for bx, by, dx, dy in ((0, 0, 1, 1), (w_vis - 1, 0, -1, 1),
                                           (0, h_vis - 1, 1, -1),
                                           (w_vis - 1, h_vis - 1, -1, -1)):
                        cv2.line(vis, (bx, by), (bx + dx * 26, by), (0, 0, 255), 4)
                        cv2.line(vis, (bx, by), (bx, by + dy * 26), (0, 0, 255), 4)
                    key = preview.show(vis)

            # ---- overlay on the game (the thing actually asked for) ------- #
            if hud.ok and not args.no_hud:
                now_h = time.perf_counter()
                if now_h - last_hud >= hud_period:
                    last_hud = now_h
                    hud.draw(cx, cy, r, bbox, {
                        "obs": obs,
                        "gaps": gaps,
                        "spokes": show_spokes,
                        "alive": (last_t is not None
                                  and (now_h - last_t) < 0.12),
                        "fps": fps_shown,
                        "omega": omega_fit,
                        "conf": max(conf_tex, conf_pro),
                        "gap": widest[1],
                    })

            # ---- global hotkeys ------------------------------------------- #
            # F10 stop, F9 dump the ring buffer, F8 toggle the L1-L60 spokes.
            if key is None:
                if _vk_pressed(VK_F10, hk):
                    print("[keys] F10 -> stop")
                    key = "q"
                elif _vk_pressed(VK_F9, hk):
                    key = "d"
                elif _vk_pressed(VK_F8, hk):
                    key = "l"

            if key is not None:
                if key in ("q", "Escape"):
                    break
                elif key == "c":
                    full = np.array(sct.grab(mon))[:, :, :3].copy()
                    got = find_target(full)
                    if got:
                        cx, cy, r = got
                        bbox = roi_for(cx, cy, r, sw, sh,
                                       args.pad_x, args.pad_up, args.pad_down)
                        x0, y0 = bbox["left"], bbox["top"]
                        cxl, cyl = cx - x0, cy - y0
                        geo = build_geometry(cxl, cyl, r)
                        mx_tex, my_tex = geo["tex"]
                        mx_pro, my_pro = geo["pro"]
                        cor_y0 = int(cyl + r * 1.02)
                        cor_y1 = int(min(bbox["height"], cyl + r * 1.95))
                        cor_x0 = int(max(0, cxl - 0.22 * r))
                        cor_x1 = int(min(bbox["width"], cxl + 0.22 * r))
                        prev_tex = prev_pro = None
                        angle_hist.clear()
                        print(f"[locate] recalibrated ({cx:.1f}, {cy:.1f}) r={r:.1f}")
                elif key == "r":
                    angle_hist.clear()
                    print("[state] omega history reset")
                elif key in ("d", "F9"):
                    d = os.path.join(args.outdir, f"dump_{stamp}_{int(time.time())}")
                    os.makedirs(d, exist_ok=True)
                    for kk, fr in enumerate(ring):
                        cv2.imwrite(os.path.join(d, f"f{kk:03d}.png"), fr)
                    print(f"[dump] {len(ring)} frames -> {d}")
                elif key in ("plus", "equal"):
                    flight_t = min(0.60, flight_t + 0.005)
                elif key == "minus":
                    flight_t = max(0.0, flight_t - 0.005)
                elif key == "p":
                    args.no_preview = not args.no_preview
                elif key == "h":
                    hud.closed = not hud.closed
                    if hud.closed:
                        try:
                            hud.canvas.delete("all")
                            hud.root.update()
                        except Exception:                      # noqa: BLE001
                            pass
                    print(f"[view] overlay {'off' if hud.closed else 'on'}")
                elif key == "l":
                    show_spokes = not show_spokes
                    print(f"[view] L1-L60 spokes {'on' if show_spokes else 'off'}")

            # ---- rate limit -------------------------------------------------- #
            # Without this the loop free-runs and burns a whole core for frames
            # the display never shows. Measurement timestamps are taken at grab
            # time, so sleeping here costs accuracy nothing.
            if args.max_fps > 0:
                budget = 1.0 / args.max_fps
                spent = time.perf_counter() - t_now
                if spent < budget:
                    time.sleep(budget - spent)

    except KeyboardInterrupt:
        pass
    finally:
        if rows:
            writer.writerows(rows)
        csv_fh.close()
        preview.close()
        hud.close()
        sct.close()

    # ---- summary --------------------------------------------------------- #
    print("\n" + "=" * 70)
    print("LIVE TELEMETRY SUMMARY")
    print("=" * 70)
    n = len(timings["grab"])
    if n:
        total = sum(timings["grab"]) + sum(timings["gray"]) + \
            sum(timings["polar"]) + sum(timings["analyse"])
        print(f"frames processed : {n}")
        print(f"mean frame cost  : {1000.0 * total / n:.2f} ms  "
              f"({n / total:.1f} fps theoretical)")
        for k in ("grab", "gray", "polar", "analyse"):
            v = np.array(timings[k]) * 1000.0
            print(f"  {k:<8} mean {v.mean():5.2f} ms   p95 {np.percentile(v, 95):5.2f} ms")
    print(f"log written      : {csv_path}")
    print("\nNote: rotation speed and gap geometry are measured here.")
    print("      The click->launch delay is NOT. That needs an actuator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

