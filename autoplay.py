#!/usr/bin/env python3
"""Autoplay: launch knives with SPACE and measure what actually happens.

WHY THE AIM IS FORMULATED THIS WAY
----------------------------------
Timing error turns into angular error as  omega * dt.  At 340 deg/s a 40 ms
mistake is 13.6 deg; at 60 deg/s the same mistake is 2.4 deg. So slow rotation
is free accuracy, exactly as asked.

The naive formulation "predict when the gap centre reaches the impact line"
divides by omega, so it explodes near a reversal (360/omega -> infinity) --
precisely the moment we most want to throw. This program therefore asks a
different question:

    if I press at t_click, the knife arrives at t_click + t_total.
    Where will the gap be THEN, and does it still cover the impact line?

        err   = angle( centre_now + omega * (t_click + t_total - t_now)
                       - impact )
        slack = gap_width/2 - knife_half - safety - |err|

    slack >= 0  =>  the knife lands inside the gap with margin to spare.

At high omega the answer is "lead the target by omega*t_total". At omega ~ 0
it degenerates to "the gap must already be on the impact line" -- which is
correct, and needs no division by zero anywhere.

WHAT FEEDBACK EXISTS
--------------------
A hit adds one knife to the log, so the obstacle count rises by exactly one.
A miss adds nothing. That is the only feedback, so the program MEASURES the
delay it cannot observe rather than searching for it.

TRIGGER
-------
Space bar (as instructed). --trigger click falls back to a mouse click at a
point derived from the log, if space ever proves unreliable.

SAFETY
------
* Bounds-checked throw point; the GO disc is found from pixels, never guessed.
  If it cannot be found, nothing is clicked.
* --max-throws caps everything. --dry-run presses nothing at all.
* F10 aborts. Cursor is restored on exit. No files outside this project.
* Every action is written to a CSV so any bug is auditable afterwards.

Run:
    python autoplay.py --duration 300              # the real thing
    python autoplay.py --duration 60 --dry-run     # no presses, measure only
"""

from __future__ import annotations

import argparse
import collections
import ctypes
import csv
import math
import os
import random
import time

import cv2
import mss
import numpy as np

import ctypes.wintypes as wintypes

import live_track as lt
import multiplier_reader as mreader

# ------------------------------------------------------------------ consts --- #
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_SPACE = 0x20
VK_F10 = 0x79

KNIFE_FULL_DEG = 8.03          # measured width of a knife in the log
SAFETY_DEG = 2.5               # extra margin, because omega is only estimated
SLACK_HIGH_OMEGA = 8.0         # demand more margin when spinning fast
SLOW_OMEGA = 140.0             # below this we call it "slow" and trust it more
LEAD_S = 0.060                 # fire when the ideal press instant is this near


def rung_index(v):
    """Nearest ladder index for a printed multiplier, or None if off-ladder.

    Used to label a throw as a hit from whether the ladder actually advanced,
    instead of trusting the knife-count counter, which undercounts.
    """
    if v is None:
        return None
    best, bd = None, 1e9
    for i, val in enumerate(mreader.LADDER):
        d = abs(val - v)
        if d < bd:
            best, bd = i, d
    return best if bd <= 0.02 else None


def next_rung(v):
    """Smallest ladder rung strictly above `v` (None at the top of the ladder)."""
    if v is None:
        return None
    above = [x for x in mreader.LADDER if x > v + 1e-9]
    return min(above) if above else None


# ------------------------------------------------------------------- input --- #
def cursor_pos():
    p = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def click_at(x: int, y: int) -> float:
    """Left click at (x, y). Returns the stamp taken at button-down."""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    t = time.perf_counter()
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return t


def press_space() -> float:
    """Press and release space. Returns the stamp taken at key-down, because
    the game reacts to the down edge, not the up edge.

    The up edge is always sent, even if this raises, or a stuck space key would
    scroll the page forever and drag the whole capture region with it.
    """
    down = time.perf_counter()
    ctypes.windll.user32.keybd_event(VK_SPACE, 0, 0, 0)
    try:
        time.sleep(0.004)
    finally:
        ctypes.windll.user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
    return down


def sleep_until(t: float) -> None:
    """Sleep, then spin. time.sleep alone overshoots by up to 15 ms on Windows,
    which is a third of the timing budget at 195 deg/s."""
    while True:
        rem = t - time.perf_counter()
        if rem <= 0.0:
            return
        if rem > 0.0015:
            time.sleep(rem - 0.0012)


def key_down(vk: int) -> bool:
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:                                          # noqa: BLE001
        return False


GA_ROOT = 2


def window_at(x: float, y: float):
    """Top-level window under a screen point (walks up from any child)."""
    pt = wintypes.POINT(int(x), int(y))
    hwnd = ctypes.windll.user32.WindowFromPoint(pt)
    if not hwnd:
        return 0
    return ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def window_title(hwnd: int) -> str:
    try:
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:                                          # noqa: BLE001
        return ""


def foreground_root() -> int:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return (ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd) if hwnd else 0


def focus_window(hwnd: int) -> bool:
    """Bring the game window to the foreground. Returns True if it worked.

    Without this the bot freezes the instant anything else is clicked -- which
    includes the chat window it was started from. Windows normally refuses
    SetForegroundWindow from a background process; attaching to the current
    foreground thread's input queue lifts that restriction. Space is still only
    sent after a confirmed focus change, so a failure here costs a pause, never
    a stray keystroke in another app.
    """
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    if not hwnd or not u.IsWindow(hwnd):
        return False
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)                      # SW_RESTORE
    if u.GetForegroundWindow() == hwnd:
        return True

    # Measured on this PC 2026-11-20: the old single AttachThreadInput attempt
    # returned False in 0 ms and never moved the foreground at all, so the bot
    # could not start while VS Code owned the screen. A thread with no message
    # queue cannot attach to another thread's input queue -- AttachThreadInput
    # fails and SetForegroundWindow then fails silently. Force a queue first,
    # then try three independent ways of stealing the foreground. Each step is
    # checked, so a failure costs milliseconds, never a stray keystroke.
    msg = wintypes.MSG()
    u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # PM_NOREMOVE

    fg = u.GetForegroundWindow()
    t_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
    t_me = k.GetCurrentThreadId()
    try:
        if t_fg and t_fg != t_me:
            u.AttachThreadInput(t_me, t_fg, True)
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.SetFocus(hwnd)
        if t_fg and t_fg != t_me:
            u.AttachThreadInput(t_me, t_fg, False)
    except Exception:                                              # noqa: BLE001
        pass
    if u.GetForegroundWindow() == hwnd:
        return True

    # 2) Alt nudge: once the process has synthesised input itself, Windows
    #    lifts the foreground lock for it. A bare Alt does nothing in-game.
    VK_MENU, KEYUP = 0x12, 0x0002
    try:
        u.keybd_event(VK_MENU, 0, 0, 0)
        u.SetForegroundWindow(hwnd)
        u.keybd_event(VK_MENU, 0, KEYUP, 0)
    except Exception:                                              # noqa: BLE001
        pass
    if u.GetForegroundWindow() == hwnd:
        return True

    # 3) Last resort: a restored window is normally handed the foreground by
    #    the shell itself.
    try:
        u.ShowWindow(hwnd, 6)                      # SW_MINIMIZE
        time.sleep(0.15)
        u.ShowWindow(hwnd, 9)                      # SW_RESTORE
    except Exception:                                              # noqa: BLE001
        pass
    return u.GetForegroundWindow() == hwnd


# --------------------------------------------------------------- measuring --- #
class Tracker:
    """Per-frame measurement, copied faithfully from live_track.main().

    Duplicated rather than imported because that loop is monolithic, and I will
    not refactor a validated observer on the eve of a live run. It was checked
    against a real frame before use: obs 9 / gaps 8 / widest 73.1 deg.
    """

    def __init__(self, mx_tex, my_tex, mx_pro, my_pro):
        self.mx_tex, self.my_tex = mx_tex, my_tex
        self.mx_pro, self.my_pro = mx_pro, my_pro
        self.prev_tex = None
        self.prev_pro = None
        self.angle = 0.0
        self.last_t = None
        self.hist = collections.deque(maxlen=120)
        self.warm = False
        self.warm_since = None
        self.omega = 0.0
        self.alpha = 0.0
        self.omega_hist = collections.deque(maxlen=200)

    def step(self, frame, t_now):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        p_tex = lt.polar(gray, self.mx_tex, self.my_tex)
        p_pro = lt.polar(gray, self.mx_pro, self.my_pro)
        sig_tex = lt.signature_from_polar(p_tex)
        sig_pro = lt.signature_from_polar(p_pro)

        dtheta, conf_tex, sharp_tex, conf_pro = 0.0, 0.0, 0.0, 0.0
        if self.prev_tex is not None and sig_tex is not None:
            lag, conf_tex, sharp_tex = lt.circular_lag(self.prev_tex, sig_tex)
            dtheta = lag * (360.0 / lt.N_THETA)
        if self.prev_pro is not None and sig_pro is not None:
            lag2, conf_pro, _ = lt.circular_lag(self.prev_pro, sig_pro)
            if conf_tex < lt.MIN_CONF and conf_pro > conf_tex:
                dtheta = lag2 * (360.0 / lt.N_THETA)
                conf_tex = conf_pro
        if sig_tex is not None:
            self.prev_tex = sig_tex
        if sig_pro is not None:
            self.prev_pro = sig_pro

        good = (conf_tex >= lt.MIN_CONF and sharp_tex >= lt.MIN_SHARP
                and abs(dtheta) < 90.0)
        if good and not self.warm:
            if self.warm_since is None:
                self.warm_since = t_now
            elif t_now - self.warm_since >= lt.WARMUP_S:
                self.warm = True
        if not good:
            dtheta = 0.0
        self.angle = (self.angle + dtheta) % 360.0

        self.last_t = t_now
        self.hist.append((t_now, self.angle))
        if len(self.hist) >= 8 and good:
            ta = np.array([a[0] for a in self.hist])
            aa = np.array([a[1] for a in self.hist])
            keep = ta >= ta[-1] - 0.35
            ta, aa = ta[keep], aa[keep]
            if len(ta) >= 6:
                unwrapped = np.degrees(np.unwrap(np.radians(aa)))
                A = np.c_[ta - ta.mean(), np.ones(len(ta))]
                try:
                    sol, *_ = np.linalg.lstsq(A, unwrapped, rcond=None)
                    self.omega = float(sol[0])
                except Exception:                              # noqa: BLE001
                    pass
        self.omega_hist.append((t_now, self.omega))

        # ---- the log does not spin at a constant speed ----------------- #
        # Measured live (temp\omega_live.py): it holds ~195 deg/s for a couple
        # of seconds, ramps to ~330 deg/s over about 0.5 s, holds that, then
        # ramps back down. Aiming with one omega held fixed across the 205 ms
        # flight is therefore wrong twice over: the least-squares omega lags
        # the true speed by ~50 deg/s during a ramp (worth ~10 deg of aim), and
        # the curvature adds 0.5*alpha*t^2 (another ~6 deg). Together that is
        # the ~14 deg of scatter measured on real throws.
        #
        # So estimate the slope of omega and carry omega forward to NOW, which
        # removes the lag. The curvature term is handled in the aim.
        self.alpha = 0.0
        if len(self.omega_hist) >= 8:
            tw = np.fromiter((x[0] for x in self.omega_hist), float)
            ww = np.fromiter((x[1] for x in self.omega_hist), float)
            keep = tw >= tw[-1] - 0.45
            tw, ww = tw[keep], ww[keep]
            if len(tw) >= 6 and ww.std() >= 0.5:
                A = np.c_[tw - tw.mean(), np.ones(len(tw))]
                try:
                    sol, *_ = np.linalg.lstsq(A, ww, rcond=None)
                    self.alpha = float(sol[0])
                    self.omega = float(sol[0] * (t_now - tw.mean()) + sol[1])
                except Exception:                          # noqa: BLE001
                    pass

        b_ch, _, r_ch = cv2.split(frame)
        sky_u8 = ((cv2.subtract(b_ch, r_ch) > 25) & (b_ch > 90)).astype(np.uint8)
        p_sky = cv2.remap(sky_u8, self.mx_pro, self.my_pro,
                          cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
        occ_full = (p_sky == 0).mean(axis=1) > 0.5
        i0 = int(lt.N_RING * lt.OCC_IN_FRAC)
        occ = occ_full[i0:]      # kept identical to live_track on purpose: it
                                 # slices the angle axis where the comment means
                                 # the radius axis. Do not "fix" it here or the
                                 # aim stops matching what the observer reports.
        return {
            "conf_tex": conf_tex, "conf_pro": conf_pro,
            "angle": self.angle, "omega": self.omega, "alpha": self.alpha,
            "obs": lt.runs_of(occ, lt.MIN_RUN_DEG, lt.MAX_OBJ_DEG),
            "gaps": lt.gaps_of(occ, lt.MIN_RUN_DEG),
            "good": (good and self.warm
                     and abs(self.omega) <= 400.0),
        }


def slot_frac(frame, cyl, r, cxl, height, width):
    y0 = int(cyl + 2.00 * r)
    y1 = int(min(height, cyl + 2.80 * r))
    x0 = int(max(0, cxl - 0.25 * r))
    x1 = int(min(width, cxl + 0.25 * r))
    sl = frame[y0:y1, x0:x1]
    if not sl.size:
        return 0.0
    sb = sl[:, :, 0].astype(np.int16)
    sr = sl[:, :, 2].astype(np.int16)
    return float((~((sb > sr + 25) & (sb > 90))).mean())


def find_go_button(frame, cx, cy, r):
    """Locate the green GO disc. Returns (x, y) or None.

    Found from pixels rather than as an offset in units of r, because r changes
    when the window is resized while the UI bar does not scale with it. The
    filters are each earned from a real screenshot:
        area in [2500, 40000]   the disc is ~100x100 px
        0.75 <= w/h <= 1.33     rejects the tall sidebar banners
        fill >= 0.50            the disc is solid (0.66); a nearby hollow
                                decorative ring scores 0.19 and must lose
        within 5r of the log    rejects the left-hand banners
        below the log           the bar sits under the target
    """
    b = frame[:, :, 0].astype(np.int16)
    g = frame[:, :, 1].astype(np.int16)
    rr = frame[:, :, 2].astype(np.int16)
    mask = ((g > b + 45) & (g > rr + 45) & (g > 110)).astype(np.uint8)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    # Position is the real filter. Measured 2026-11-20: the shape/size/fill
    # tests alone matched a tree canopy at (964, 1098) and the bot spent four
    # minutes clicking foliage while insisting it had pressed GO. The disc sits
    # at a fixed place relative to the log -- 2.96 r right, 4.29 r down on this
    # 2560x1440 layout -- so only accept something within half a radius of it.
    ex, ey = cx + 2.96 * r, cy + 4.29 * r
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (2500 <= area <= 40000):
            continue
        if not (0.75 <= (w / max(1, h)) <= 1.33):
            continue
        if area / float(w * h) < 0.50:
            continue
        xc, yc = x + w / 2.0, y + h / 2.0
        if abs(xc - ex) > 0.50 * r or abs(yc - ey) > 0.45 * r:
            continue
        d = math.hypot(xc - ex, yc - ey)
        if best is None or d < best[0]:
            best = (d, float(xc), float(yc))
    return None if best is None else (int(round(best[1])), int(round(best[2])))


def ang_diff(a: float, b: float) -> float:
    """Signed shortest difference a-b, in (-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


# -------------------------------------------------------------------- main --- #
def find_cashout_box(frame, cx, cy, r):
    """Locate the yellow CASHOUT panel. Returns its centre, or None.

    This matters because the obvious guess is WRONG: mid-round the round green
    button still says GO, and clicking it does not cash out -- a test run clicked
    it twice and the balance fell by exactly 2 x the bet. The cash-out control is
    the wide yellow panel that only appears once a round is live.

    Filters are measured from live frames, not invented:
        hue 15-40, sat >= 120, val >= 110
                              the panel is GOLD; a hue/sat test survives the
                              brightness swing that a fixed RGB test does not
        area >= 4000          the panel is ~200x60 px of solid yellow
        w/h >= 1.6            a wide bar, unlike the small gold ladder labels
        fill >= 0.55          solid block, not a ring or an icon
        below the log centre  the panel bar sits under the target

    Why HSV and not RGB (measured on this 2560x1440 PC, 2026-11-19)
    -----------------------------------------------------------------
    The earlier test was r>170 & g>130 & b<110, tuned on the laptop. Here the
    live panel frequently renders DARKER -- mean BGR (13,117,147), i.e. r=147 --
    and only 0.0 % of its pixels passed. The bot then declared "no live panel"
    and scored a live round as lost. Ten saved frames split perfectly:
        disabled panel (dark olive)  -> RGB: none,  HSV: none   (correct)
        live panel, bright           -> RGB: 320x107, HSV: 321x107
        live panel, dimmed           -> RGB: NONE,    HSV: 320x107  <-- the bug
    Hue 15-40 / sat 120 keeps the disabled panel rejected (it is desaturated),
    so this is not a looser test -- it is a test of the right quantity.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] >= 15) & (hsv[:, :, 0] <= 40)
            & (hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 110)).astype(np.uint8)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 4000 or w < 120 or h < 40:
            continue
        if w / max(1, h) < 1.6:
            continue
        if area / float(w * h) < 0.55:
            continue
        if (y + h / 2.0) <= cy:
            continue
        if best is None or area > best[0]:
            best = (area, x + w / 2.0, y + h / 2.0)
    return None if best is None else (int(round(best[1])), int(round(best[2])))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--trigger", choices=("space", "click"), default="space")
    ap.add_argument("--click-x", type=int, default=None)
    ap.add_argument("--click-y", type=int, default=None)
    ap.add_argument("--go-x", type=int, default=None)
    ap.add_argument("--go-y", type=int, default=None)
    ap.add_argument("--impact-deg", type=float, default=180.0,
                    help="screen angle where the knife lands (180 = bottom)")
    ap.add_argument("--t-total", type=float, default=0.205,
                    help="press -> landing, seconds (was 0.230; 51 measured "
                         "throws showed a +4.1 deg over-lead, i.e. -25 ms)")
    ap.add_argument("--min-gap", type=float, default=20.0,
                    help="refuse gaps narrower than this (knife is 8.03)")
    ap.add_argument("--min-omega", type=float, default=150.0,
                    help="do not throw below this |omega|. Measured on 249 real "
                         "throws (2026-11-19): 0 hits out of 10 below 150 deg/s, "
                         "91%% at 150-210. The old floor of 120 let the bot into "
                         "a bucket that never hit.")
    ap.add_argument("--stability", type=float, default=0.45,
                    help="omega must have kept one sign for this many seconds")
    ap.add_argument("--sweep", default=None,
                    help="comma-separated t_total values (seconds). One is "
                         "picked at random per throw and written to the CSV, "
                         "so hit rate can be compared across leads in a "
                         "single run instead of one run per value")
    ap.add_argument("--trace", default=None,
                    help="write one row per frame (angle, omega, slot) to this "
                         "CSV, to see what the log does across a throw")
    ap.add_argument("--dump-miss", action="store_true",
                    help="keep the last 0.7 s of log frames in memory and write "
                         "them to temp/miss/ when a round is lost. A miss that "
                         "cannot be replayed cannot be diagnosed; this is the "
                         "only way to see what the knife actually did")
    ap.add_argument("--max-alpha", type=float, default=50.0,
                    help="do not throw while the log's spin rate is changing "
                         "faster than this (deg/s^2). The log ramps between "
                         "~195 and ~335 deg/s over about 0.5 s, and a "
                         "fixed-omega prediction made during a ramp is wrong "
                         "by ~16 deg -- the entire measured aim error. "
                         "0 disables the gate.")
    ap.add_argument("--slow-omega", type=float, default=SLOW_OMEGA)
    ap.add_argument("--min-slack", type=float, default=18.0,
                    help="refuse any throw whose predicted margin at impact is "
                         "below this. The floor was raised to 22 on 2026-11-20 "
                         "on the theory that the worst throws sat at slack "
                         "18-21, then tested on a full run: accuracy fell from "
                         "98.1%% to 96.5%% and all three misses landed at slack "
                         "24.1-28.8, i.e. the widest margins in the run. The "
                         "correlation was small-sample noise, and the higher "
                         "floor only halved the throw rate. Reverted to 18. Do "
                         "NOT raise past ~25: the observed maximum is 28.8.")
    ap.add_argument("--patience", type=float, default=600.0,
                    help="after this long with no throw, relax the omega floor. "
                         "Default 600 s = effectively never: waiting costs "
                         "nothing, a reversal throw costs the whole round.")
    ap.add_argument("--max-throws", type=int, default=600)
    ap.add_argument("--dry-run", action="store_true",
                    help="measure and log but never press anything")
    ap.add_argument("--drift-check", type=int, default=0,
                    help="re-locate every N throws (0 = off; measured target "
                         "jitter of +-4 px made this fire 28 times in 240 s and "
                         "reset the tracker for nothing)")
    ap.add_argument("--min-r", type=float, default=70.0,
                    help="reject a located target smaller than this radius")
    ap.add_argument("--max-r", type=float, default=320.0,
                    help="reject a located target larger than this radius")
    ap.add_argument("--max-move", type=float, default=120.0,
                    help="during drift recovery, reject a target this far away")
    ap.add_argument("--no-focus-check", action="store_true",
                    help="send space even when the game window is not focused")
    ap.add_argument("--no-auto-focus", action="store_true",
                    help="do not take the focus back for the game window. By "
                         "default the bot re-focuses it, otherwise it freezes "
                         "the moment any other window is touched.")
    ap.add_argument("--rounds", type=int, default=0,
                    help="stop after this many completed rounds (0 = run until "
                         "--duration expires). A round ends either by cash-out "
                         "or by dying first.")
    ap.add_argument("--bet", type=float, default=105.0,
                    help="stake per round, only used to report money")
    ap.add_argument("--one-round", action="store_true",
                    help="stop immediately after the first successful cash-out. "
                         "Used to prove one round end-to-end without betting again.")
    ap.add_argument("--no-auto-go", action="store_true",
                    help="never click the GO button. Throwing already starts a "
                         "round, and a stray GO click mid-round costs a bet.")
    ap.add_argument("--cashout-at", type=float, default=2.00,
                    help="click the cash-out button once the HELD multiplier "
                         "(log value one rung behind) reaches this. 0 disables. "
                         "Remember the log prints the NEXT rung, not the held one.")
    ap.add_argument("--round-timeout", type=float, default=110.0,
                    help="hard per-round budget in seconds. When it expires the "
                         "bot cashes out at whatever is already HELD (as long as "
                         "that is above x1.00, which is still a profit) instead "
                         "of gambling or overrunning. 0 disables. This is what "
                         "keeps a match near the two-minute brief.")
    ap.add_argument("--dump-mult", default=None,
                    help="save the log-centre crop whenever the read changes, "
                         "so every logged value can be audited against pixels")
    ap.add_argument("--outdir", default="recordings")
    args = ap.parse_args()

    sweep_values = []
    if args.sweep:
        sweep_values = [float(x) for x in args.sweep.split(",") if x.strip()]
        print(f"[auto] lead sweep over {len(sweep_values)} values: "
              f"{', '.join(f'{v*1000:.0f} ms' for v in sweep_values)}")

    sct = mss.MSS()
    mon = sct.monitors[1]
    sw, sh = mon["width"], mon["height"]

    def locate(verbose=True, expect=None):
        shot = cv2.cvtColor(np.asarray(sct.grab(mon)), cv2.COLOR_BGRA2BGR)
        got = lt.find_target(shot, verbose=verbose)
        if got is None:
            return None
        cx_, cy_, r_ = got
        # find_target accepts any circle ringed by >=35 % sky and applies no
        # size limit. On this game it has been seen to return r=24 at the
        # top-left, which would rebuild every remap grid around nothing.
        if not (args.min_r <= r_ <= args.max_r):
            if verbose:
                print(f"[auto] rejected target r={r_:.0f} -- plausible is "
                      f"{args.min_r:.0f}-{args.max_r:.0f}")
            return None
        if expect is not None:
            d = math.hypot(cx_ - expect[0], cy_ - expect[1])
            if d > args.max_move:
                if verbose:
                    print(f"[auto] rejected target {d:.0f} px from the known "
                          "position -- looks like a false positive")
                return None
        bbox_ = lt.roi_for(cx_, cy_, r_, sw, sh, 1.60, 1.60, 3.05)
        x0_, y0_ = bbox_["left"], bbox_["top"]
        cxl_, cyl_ = cx_ - x0_, cy_ - y0_
        geo_ = lt.build_geometry(cxl_, cyl_, r_)
        return {
            "cx": cx_, "cy": cy_, "r": r_, "bbox": bbox_,
            "cxl": cxl_, "cyl": cyl_,
            "mx_tex": geo_["tex"][0], "my_tex": geo_["tex"][1],
            "mx_pro": geo_["pro"][0], "my_pro": geo_["pro"][1],
            "bw": bbox_["width"], "bh": bbox_["height"], "shot": shot,
        }

    # Locating is a one-shot guess about a moving, animating picture, and it
    # has been seen to latch onto a decorative circle (r=24) while the real log
    # sat in plain sight. Rejecting a bad radius without retrying turned that
    # flake into "no target on screen", so retry briefly instead of giving up.
    # The game must be VISIBLE to be located. If the user is typing in another
    # window the game sits behind it, locate() sees a desktop and the bot gives
    # up before it ever throws. Bring the game forward first.
    try:
        _found = []

        def _enum_cb(hwnd, _param):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                if "Knife" in window_title(hwnd):
                    _found.append(hwnd)
            return True

        _cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                 wintypes.LPARAM)(_enum_cb)
        ctypes.windll.user32.EnumWindows(_cb, 0)
        if _found:
            print(f"[auto] bringing the game window forward (0x{_found[0]:X})")
            focus_window(_found[0])
            time.sleep(0.4)
    except Exception as exc:                                  # noqa: BLE001
        print(f"[auto] could not raise the game window: {exc}")

    L = None
    # Time-based, not attempt-based: a window that is still animating into the
    # foreground can take a couple of seconds to paint, and 8 grabs (2.8 s) was
    # measured short on this PC. Keep re-focusing while we wait rather than
    # giving up on a game that is in fact open.
    _deadline = time.time() + 20.0
    _tries = 0
    while True:
        L = locate(verbose=(_tries == 0))
        if L is not None:
            break
        if time.time() > _deadline:
            break
        _tries += 1
        if _tries % 3 == 0 and _found and not args.no_auto_focus:
            focus_window(_found[0])
        time.sleep(0.35)
    if L is None:
        print("[auto] no target on screen after 20 s -- open the game first "
              f"(foreground 0x{foreground_root():X})")
        return 2

    cx, cy, r = L["cx"], L["cy"], L["r"]
    bbox = L["bbox"]

    # The multiplier is printed on the log, so it is read from the SAME crop the
    # tracker already grabs -- no extra screen grab, no extra latency. The
    # coordinates therefore have to be translated into that crop.
    lcx, lcy = cx - bbox["left"], cy - bbox["top"]
    try:
        mreader_ = mreader.Reader()
        print(f"[auto] multiplier reader: {len(mreader_.masks)} glyph shapes "
              f"loaded -- reads xN.NN from the log centre")
    except Exception as exc:                                    # noqa: BLE001
        mreader_ = None
        print(f"[auto] multiplier reader DISABLED ({exc}) -- "
              "multiplier will not be logged")

    # The window that owns the pixel at the log's centre. Space is only sent
    # while this window is foreground; otherwise a stray space would scroll or
    # type into whatever app took focus.
    game_root = window_at(cx, cy)

    # ---- miss recorder ----------------------------------------------------- #
    # A lost round is the only evidence that matters and it is gone the moment
    # it happens. Keep the last 0.7 s of the log's own neighbourhood (full
    # resolution, ~70 frames) and write it out on a loss, so a miss can be
    # replayed instead of theorised about. 0.7 s at 195 deg/s is 136 deg, which
    # covers the 205 ms flight plus the frames on either side of the press.
    miss_ring = collections.deque(maxlen=70) if args.dump_miss else None

    # ---- throw / GO points ------------------------------------------------ #
    throw_pt = (
        args.click_x if args.click_x is not None else int(round(cx - 3.00 * r)),
        args.click_y if args.click_y is not None else int(round(cy - 1.00 * r)),
    )
    go_pt = ((args.go_x, args.go_y)
             if (args.go_x is not None and args.go_y is not None)
             else find_go_button(L["shot"], cx, cy, r))

    # ---- fast UI strip ------------------------------------------------ #
    # The GO disc and the yellow CASHOUT bar both live in one short strip under
    # the log. Scanning the whole 1920x1080 screen cost a measured 50 ms per
    # call, because three 2.07 M-pixel planes get converted to int16 first. The
    # strip is ~11x smaller and gives the same answer. This matters twice a
    # second in the liveness check, and it matters most at the instant of a
    # cash-out, where 45 ms of extra latency is 45 ms of multiplier given away.
    def ui_roi(cx_, cy_, r_):
        x0_ = max(0, int(cx_ - 2.0 * r_))
        y0_ = max(0, int(cy_ + 3.0 * r_))
        x1_ = min(sw, int(cx_ + 4.3 * r_))
        y1_ = min(sh, int(cy_ + 5.8 * r_))
        return {"left": x0_, "top": y0_,
                "width": max(1, x1_ - x0_), "height": max(1, y1_ - y0_)}

    def grab_ui(cx_, cy_, r_):
        roi_ = ui_roi(cx_, cy_, r_)
        return (cv2.cvtColor(np.asarray(sct.grab(roi_)), cv2.COLOR_BGRA2BGR),
                roi_["left"], roi_["top"])

    def check_pt(pt, label):
        x, y = pt
        if not (0 <= x < sw and 0 <= y < sh):
            raise SystemExit(f"[auto] {label} {pt} is off-screen ({sw}x{sh}) -- aborting")
        if go_pt is not None and math.hypot(x - go_pt[0], y - go_pt[1]) < 90:
            raise SystemExit(f"[auto] {label} {pt} sits on the GO button -- aborting")
        if y > sh - 110:
            raise SystemExit(f"[auto] {label} {pt} is in the bottom UI bar -- aborting")
        if abs(x - cx) > 4.5 * r or abs(y - cy) > 4.5 * r:
            print(f"[auto] WARNING: {label} {pt} is far from the log")
        return pt

    check_pt(throw_pt, "throw point")

    trk = Tracker(L["mx_tex"], L["my_tex"], L["mx_pro"], L["my_pro"])

    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, f"throws_{stamp}.csv")
    fh = open(csv_path, "w", newline="", encoding="utf-8")
    wr = csv.writer(fh)
    wr.writerow(["t", "event", "aim_deg", "omega", "gap_w", "slack", "t_total",
                 "slot", "n_obs", "detail", "mult"])

    rounds_path = os.path.join(args.outdir, f"rounds_{stamp}.csv")
    rfh = open(rounds_path, "w", newline="", encoding="utf-8")
    rwr = csv.writer(rfh)
    rwr.writerow(["round", "start_s", "end_s", "outcome", "cashout_held",
                  "peak_log", "throws", "hits"])

    round_no = 0
    round_open = False
    round_t0 = 0.0
    round_throws = 0
    round_hits = 0
    round_peak = None
    wins = 0
    losses = 0
    pnl = 0.0
    t_cashout = None
    last_cash_t = None
    prev_obs = None

    def open_round(t_now_):
        nonlocal round_no, round_open, round_t0, round_throws, round_hits
        nonlocal round_peak
        if round_open:
            return
        round_no += 1
        round_open = True
        round_t0 = t_now_
        round_throws = 0
        round_hits = 0
        round_peak = None

    def close_round(outcome, t_end, held=None):
        nonlocal round_open, wins, losses, pnl, round_no
        if not round_open:
            return
        # A round that was opened by a throw fired just as the PREVIOUS round
        # died is not a real round: it holds one throw and lasts a fraction of
        # a second (observed 0.09-0.18 s, peak 1.00). Counting it as a loss
        # understates the win rate and burns the --rounds budget, which counts
        # wins + losses. Log it, but do not score it and do not consume a
        # round number. A genuine one-throw round cannot happen this fast: the
        # throw gates alone (two rotations + sign stability) take >2 s.
        if (outcome == "lost" and round_throws <= 1
                and (t_end - round_t0) < 1.5):
            rwr.writerow([round_no, round(round_t0 - t_start, 3),
                          round(t_end - t_start, 3), "phantom",
                          "", "", round_throws, round_hits])
            rfh.flush()
            round_open = False
            round_no -= 1
            print("[auto] phantom round ignored (1 throw, "
                  f"{t_end - round_t0:.2f}s) -- not scored")
            return
        # peak_round is the highest number the LOG printed this round; the money
        # actually held at that moment is one rung behind it.
        peak_log = peak_round
        peak_held = mreader.current_from_log(peak_log) if peak_log else None
        rwr.writerow([round_no, round(round_t0 - t_start, 3),
                      round(t_end - t_start, 3), outcome,
                      f"{held:.2f}" if held is not None else "",
                      f"{peak_held:.2f}" if peak_held is not None else "",
                      round_throws, round_hits])
        rfh.flush()
        if outcome != "won" and miss_ring:
            # Only on a loss: the last 0.7 s of frames, written once. This is
            # what turns "it missed" into "it missed because ...".
            try:
                outdir = os.path.join("temp", "miss")
                os.makedirs(outdir, exist_ok=True)
                tag = f"r{round_no:02d}_{round(round_t0 - t_start, 1):07.1f}s"
                for i, (_tt, _img) in enumerate(miss_ring):
                    cv2.imwrite(os.path.join(outdir, f"{tag}_{i:03d}.png"), _img)
                print(f"[auto] miss frames -> {outdir}\\{tag}_*.png "
                      f"({len(miss_ring)} frames)")
            except Exception as exc:                            # noqa: BLE001
                print(f"[auto] could not write miss frames: {exc}")
            miss_ring.clear()
        if outcome == "won" and held is not None:
            wins += 1
            pnl += args.bet * held - args.bet
        else:
            losses += 1
            pnl -= args.bet
        round_open = False

    print(f"[auto] target ({cx:.1f},{cy:.1f}) r={r:.1f}  box {L['bw']}x{L['bh']}"
          f" @ ({bbox['left']},{bbox['top']})")
    print(f"[auto] trigger={args.trigger}  throw point {throw_pt}  GO "
          f"{go_pt if go_pt else 'NOT FOUND -> auto-restart disabled'}")
    if game_root and window_title(game_root):
        print(f"[auto] game window 0x{game_root:X} '{window_title(game_root)}'"
              " -- space is sent only while this window is focused")
    print(f"[auto] impact {args.impact_deg:.0f} deg  t_total {args.t_total*1000:.0f} ms"
          f"  slow<{args.slow_omega:.0f} deg/s  min gap {args.min_gap:.0f} deg")
    print(f"[auto] min slack {args.min_slack:.0f} deg  min omega "
          f"{args.min_omega:.0f} deg/s  stability {args.stability:.2f} s  "
          f"max alpha {args.max_alpha:.0f} deg/s2  "
          f"round cap {args.round_timeout:.0f} s  target x{args.cashout_at:.2f}")
    print(f"[auto] {'DRY RUN -- nothing is pressed' if args.dry_run else 'ARMED'}"
          f"  F10 stops  log {csv_path}")

    orig_cursor = cursor_pos()
    t_start = time.perf_counter()
    state = "WAIT"                 # WAIT -> FLYING
    t_click = 0.0
    t_state = 0.0
    aim_deg = float("nan")
    aim_gap_w = float("nan")
    aim_slack = float("nan")
    aim_pred = float("nan")
    obs_at_click = -1
    mult_at_click = None
    # Set when the throw in flight is the one that reaches --cashout-at. The
    # landing branch then cashes out on the PANEL, without waiting for the
    # reader, because the digits are unreadable exactly while a rung is banked.
    cash_aim = None
    aim_obs0 = []
    aim_t_frame = None
    aim_omega0 = 0.0
    aim_centre0 = None
    t_launch = None
    t_reload = None
    slot_base = None
    throws = 0
    tw = None
    hits = 0
    t_last_throw = t_start
    warned_focus = False
    last_focus_try = 0.0
    last_go_t = 0.0
    slot_low_since = None
    last_log = 0.0
    mult_val = None          # last trusted read of the log-centre number
    last_mult_read_t = 0.0   # when that read actually happened
    mult_str = ""
    peak_round = None        # best multiplier seen in the current round
    best_ever = None         # best of the whole run
    last_mult_t = 0.0
    last_dump_val = None
    last_reject_why = None
    cashed_out = False
    cashed = []              # held multiplier of every completed round
    last_live_t = 0.0        # last time the yellow CASHOUT panel was checked
    not_live_n = 0           # consecutive checks that found no live round
    # ---- round-start patience ------------------------------------------------ #
    round_start_rotations = 2
    rotations_seen = 0.0
    last_omega_sign = 0
    sign_stable_since = 0.0
    last_rot_t = None
    last_unstable_t = 0.0    # last frame the vision looked unsettled
    # The multiplier must be readable for the watch-and-wait gate to open. If it
    # never is (bad calibration, reskin, wrong screen scale), the bot sits at
    # "throws 0" forever with no explanation -- which is exactly what happened
    # on the first 2560x1440 run. Warn loudly instead of deadlocking in silence.
    mult_fail_since = None
    mult_warned = False

    try:
        while True:
            t_now = time.perf_counter()
            if key_down(VK_F10):
                print("\n[auto] F10 -> stop")
                break
            if t_now - t_start > args.duration:
                break
            if args.rounds and (wins + losses) >= args.rounds:
                print(f"[auto] {args.rounds} rounds done -> stopping")
                break

            raw = sct.grab(bbox)
            # Zero-copy extract (see live_track.py). The old path copied the
            # 4-channel buffer twice and halved the loop rate to 50 fps at
            # 2560x1440; this holds the full 100 Hz budget.
            frame = cv2.cvtColor(np.asarray(raw), cv2.COLOR_BGRA2BGR)
            if (miss_ring is not None and t_click
                    and 0.0 <= (t_now - t_click) < 0.55):
                # Record ONLY the flight window, not every frame. A round is not
                # scored lost until 1.5 s after the slot empties, so a rolling
                # 0.7 s buffer had already forgotten the knife by the time the
                # loss was written: the first four replays showed an empty log
                # and no throw. Anchoring the buffer to the press fixes that and
                # costs a copy on ~10 % of frames instead of all of them.
                _h = int(1.30 * r)
                _y0 = max(0, int(L["cyl"]) - _h)
                _y1 = min(frame.shape[0], int(L["cyl"]) + _h)
                _x0 = max(0, int(L["cxl"]) - _h)
                _x1 = min(frame.shape[1], int(L["cxl"]) + _h)
                miss_ring.append((t_now - t_click, frame[_y0:_y1, _x0:_x1].copy()))
            m = trk.step(frame, t_now)
            sf = slot_frac(frame, L["cyl"], r, L["cxl"], L["bh"], L["bw"])
            n_obs = len(m["obs"])
            if slot_base is None and sf > 0.05:
                slot_base = sf

            # A live throw empties the slot for ~67 ms (measured, n=44). So a
            # slot that stays empty for 1.5 s means the round is not running --
            # and this, not n_obs==0, is what a finished round actually looks
            # like: the decorative knives stay, so obs never reaches zero.
            if sf < 0.05:
                if slot_low_since is None:
                    slot_low_since = t_now
            else:
                slot_low_since = None
            round_dead = (slot_low_since is not None
                          and t_now - slot_low_since > 1.5)

            # ---- tracking dropout: ignore the frame entirely -------------- #
            # n_obs == 0 is the known ~21 % dropout mode of the obstacle scan,
            # NOT evidence that the round ended. Conflating the two is what
            # wasted 354 of 400 presses in the 240 s run: one dropped frame
            # released the flight state and let a second knife be fired into a
            # game still animating the first.
            if n_obs == 0:
                continue

            # ---- vision instability tracker (NOT a round over) --------- #
            # A finished round used to be detected here as "the obstacle count
            # dropped by 4 or more". That is wrong, and it cost six rounds at
            # exactly x1.35: that is where the ladder finishes its second row,
            # and the game wipes the stuck knives and blanks the number while it
            # scrolls to the next row. Measured on the 30-round log: n_obs fell
            # 14 -> 4 and the reader returned nothing for ~1.4 s, yet the round
            # was still alive (the log printed x1.48 afterwards, not x1.01).
            # A collapse now means exactly one thing: do not throw until the
            # picture settles. The only round-over signal is the log printing
            # x1.01 again, handled where the multiplier is read.
            if prev_obs is not None and (prev_obs - n_obs) >= 4:
                last_unstable_t = t_now
                wr.writerow([round(t_now - t_start, 3), "redraw", "", "",
                             "", "", "", round(sf, 4), n_obs,
                             f"n_obs {prev_obs}->{n_obs}; vision settling",
                             mult_str])
            prev_obs = n_obs

            # ---- rotation sign stability & round-start patience ---------- #
            # The aim needs a rotation sign that will still be that sign when
            # the knife lands ~205 ms from now, and the round-start gate wants
            # two clean turns before trusting the first throw. The accumulator
            # is keyed off last_rot_t, NOT off t_state: t_state is only set by
            # a throw, so keying off it deadlocked the first throw of every
            # round at zero rotations (observed: 0 throws in 12 s).
            omega_t = m["omega"]
            if omega_t != 0.0:
                sgn_t = 1 if omega_t > 0 else -1
                if last_omega_sign != sgn_t:
                    last_omega_sign = sgn_t
                    sign_stable_since = t_now
                if last_rot_t is not None:
                    rotations_seen += abs(omega_t) * (t_now - last_rot_t) / 360.0
            last_rot_t = t_now

            # ---- read the multiplier printed on the log ------------------- #
            # Throttled to ~5 Hz: the number only changes when a knife lands.
            # A read the reader does not trust is RECORDED AS UNKNOWN, never
            # carried over. An earlier version reused the last good value, and
            # that put a confident x1.48 in the log for eight straight hits
            # that the reader had actually failed to read.
            if mreader_ is not None and (t_now - last_mult_t) > 0.20:
                last_mult_t = t_now
                v, why = mreader_.read(frame, lcx, lcy, r)

                if v is None:
                    # The number is unreadable: whatever we think the log is
                    # doing may already be stale. Block throws briefly.
                    last_unstable_t = t_now
                    if mult_fail_since is None:
                        mult_fail_since = t_now
                    elif (not mult_warned
                          and t_now - mult_fail_since > 4.0):
                        mult_warned = True
                        print(f"[auto] WARNING: the log-centre multiplier has "
                              f"been unreadable for {t_now - mult_fail_since:.1f}s "
                              f"({why}) -- no throw is permitted while it is "
                              f"unknown. If this persists the bot will never "
                              f"throw; check the calibration and the digit "
                              f"templates.")
                    if why != last_reject_why:
                        last_reject_why = why
                        wr.writerow([
                            round(t_now - t_start, 3), "mult_unknown", "", "",
                            "", "", "", round(sf, 4), n_obs, why, ""])
                        if args.dump_mult:
                            os.makedirs(args.dump_mult, exist_ok=True)
                            cv2.imwrite(os.path.join(
                                args.dump_mult,
                                f"{t_now - t_start:07.2f}_REJECT_{why}.png"),
                                mreader.centre_crop(frame, lcx, lcy, r))
                else:
                    last_reject_why = None
                    mult_fail_since = None
                    mult_warned = False
                    # A trusted read falling back to x1.01 after being above it
                    # is a finished round: the display resets to the first rung,
                    # which is the "landed back on the start" asked for.
                    if mult_val is not None and mult_val > 1.05 and v <= 1.01 + 1e-9:
                        reached = peak_round if peak_round else mult_val
                        wr.writerow([
                            round(t_now - t_start, 3), "new_round", "", "",
                            "", "", "", round(sf, 4), n_obs,
                            f"reached x{reached:.2f} -> reset x{v:.2f}",
                            f"x{v:.2f}"])
                        print(f"[auto] round ended at x{reached:.2f}"
                              f" -- new round at x{v:.2f}")
                        # A trusted read falling back to the first rung is the
                        # ONLY proof that a round is over. If we never cashed
                        # out, that is a real loss and it must be counted here,
                        # or --rounds would never terminate.
                        if round_open and not cashed_out:
                            held_peak = mreader.current_from_log(reached)
                            close_round("lost", t_now)
                            hp = f"x{held_peak:.2f}" if held_peak else "?"
                            print(f"[auto] round {round_no} LOST before target "
                                  f"(held peaked {hp}, {round_hits} hits)")
                            state = "WAIT"
                            t_launch = t_reload = None
                        peak_round = None
                        cashed_out = False
                        cash_aim = None
                        last_unstable_t = t_now
                    mult_val = v
                    last_mult_read_t = t_now
                    mult_str = f"x{v:.2f}"
                    if peak_round is None or v > peak_round:
                        peak_round = v
                    if best_ever is None or v > best_ever:
                        best_ever = v
                    if args.dump_mult and v != last_dump_val:
                        last_dump_val = v
                        os.makedirs(args.dump_mult, exist_ok=True)
                        cv2.imwrite(os.path.join(
                            args.dump_mult, f"{t_now - t_start:07.2f}_x{v:.2f}.png"),
                            mreader.centre_crop(frame, lcx, lcy, r))

                    # ---- cash out ------------------------------------- #
                    # `v` is the NEXT rung, so the money at risk is one rung
                    # behind it. Cash out on the held value, never on `v`, or
                    # the bot would give back a rung on every round.
                    held = mreader.current_from_log(v)
                    # ---- hard per-round time cap ------------------------ #
                    # The brief is "finish a match in about two minutes". If the
                    # strict margin gate has not produced a cash-out by then,
                    # bank what is already held instead of gambling or running
                    # long. Cashing out above x1.00 is a profit, never a loss,
                    # so the cap can only cost upside -- never the stake.
                    timed_out = (args.round_timeout > 0 and round_open
                                 and (t_now - round_t0) > args.round_timeout)
                    if ((args.cashout_at and not cashed_out and go_pt is not None
                         and held is not None
                         and held >= args.cashout_at - 1e-9
                         and (last_cash_t is None
                              or t_now - last_cash_t > 3.0))
                            or (timed_out and not cashed_out
                                and go_pt is not None and held is not None
                                and held > 1.0
                                and (last_cash_t is None
                                     or t_now - last_cash_t > 3.0))):
                        # Locate the yellow panel on a fresh full grab; the
                        # cropped frame does not contain the whole bar.
                        box = None
                        try:
                            sub, ox, oy = grab_ui(cx, cy, r)
                            got = find_cashout_box(sub, cx - ox, cy - oy, r)
                            if got is not None:
                                box = (got[0] + ox, got[1] + oy)
                        except Exception:
                            box = None
                        if box is None:
                            box = (int(round(cx + 0.27 * r)),
                                   int(round(cy + 4.33 * r)))
                        click_at(*box)
                        cash_pt = box
                        # A click can be swallowed (focus switch, compositor
                        # hiccup). Observed on this PC 2026-11-19: the x2.12
                        # click did nothing, the bot marked itself cashed out,
                        # kept playing and re-clicked at x2.47 -- risking the
                        # stake on a rung it never intended to take.
                        #
                        # Verification must allow for the win animation: the
                        # gold panel lingers ~1 s even on SUCCESS. A 0.36 s
                        # check re-clicked 3x on all 18 cash-outs, which is 3
                        # blind clicks on a win screen. So settle for 1.2 s
                        # before the first retry.
                        #
                        # Waiting costs nothing here: after a cash-out the bot
                        # stops throwing, so a FAILED click leaves the log
                        # parked on the same rung. The retry still cashes on
                        # the intended rung -- it cannot drift to a higher one.
                        clicked_again = 0
                        if not args.dry_run:
                            now0 = time.perf_counter()
                            next_click = now0 + 1.2
                            while time.perf_counter() < now0 + 3.4:
                                time.sleep(0.2)
                                try:
                                    sub2, ox2, oy2 = grab_ui(cx, cy, r)
                                    still_gold = find_cashout_box(
                                        sub2, cx - ox2, cy - oy2, r) is not None
                                except Exception:            # noqa: BLE001
                                    still_gold = False
                                if not still_gold:
                                    break
                                now2 = time.perf_counter()
                                if now2 >= next_click and clicked_again < 2:
                                    click_at(*box)
                                    clicked_again += 1
                                    next_click = now2 + 0.7
                            if clicked_again:
                                print(f"[auto] cash-out click did not register "
                                      f"-- re-clicked {clicked_again}x at "
                                      f"x{held:.2f}")
                            if os.environ.get("KN_DUMP_UI"):
                                print(f"[auto] cash-out panel cleared after "
                                      f"{time.perf_counter() - now0:.2f}s "
                                      f"(re-clicks {clicked_again})")
                        cashed_out = True
                        cashed.append(held)
                        t_cashout = t_now
                        last_cash_t = t_now
                        close_round("won", t_now, held)
                        wr.writerow([
                            round(t_now - t_start, 3), "CASHOUT", "", "", "", "",
                            "", round(sf, 4), n_obs,
                            f"held x{held:.2f} (log printed x{v:.2f}) "
                            f"clicked {cash_pt}"
                            f"{' TIMEOUT' if timed_out else ''}", mult_str])
                        print(f"[auto] *** CASHED OUT at x{held:.2f} "
                              f"(log read x{v:.2f})"
                              f"{' ON TIME CAP' if timed_out else ''} ***")
                        state = "CASHED"
                        t_state = t_now
                        if args.one_round:
                            print("[auto] --one-round: stopping here so the "
                                  "result can be checked before betting again")
                            break

                    # ---- start the next round -------------------------- #
                    # After a cash-out the game shows the win state: the log
                    # reads x1.01 and the yellow panel disappears. Waiting for
                    # a fresh x1.01 read (plus a beat for the animation) is
                    # what lets the loop run unattended instead of betting
                    # blind into a live round.
                    #
                    # The old test ALSO cleared unconditionally after 6 s, and
                    # that is how one round got cashed out twice: observed
                    # 2026-11-19, held x2.12 at 79.9 s then held x2.47 at
                    # 86.2 s. The win screen keeps printing a big number, the
                    # latch expired, the next read armed another cash-out.
                    # Clear on evidence -- the number actually reset -- with a
                    # long absolute fallback only so it can never deadlock.
                    reset_seen = (mult_val is not None and mult_val <= 1.5)
                    if (state == "CASHED" and t_cashout is not None
                            and ((t_now - t_cashout > 2.5
                                  and mult_val is not None
                                  and mult_val <= 1.01 + 1e-9)
                                 or (t_now - t_cashout > 6.0 and reset_seen)
                                 or (t_now - t_cashout > 25.0))):
                        state = "WAIT"
                        cashed_out = False
                        t_cashout = None
                        print("[auto] next round -> throwing again")
                        # reset rotation tracking for the new round
                        rotations_seen = 0.0
                        last_omega_sign = 0
                        sign_stable_since = 0.0
                        # The display still shows the rung we banked (x2.28 for a
                        # 2.12 cash-out) until the next round redraws. Without
                        # this the NEXT round inherited that number as its peak:
                        # measured 2026-11-20, round 7 reached only x1.75 but the
                        # log recorded peak_log x2.12, which silently corrupted
                        # every peak-based accuracy number.
                        peak_round = None

            # ---- is a round actually running? ----------------------------- #
            # slot_frac is not sufficient. After a CASH-OUT the game shows a
            # win state in which the knife slot stays FULL, so "slot empty for
            # 1.5 s" never fires and the bot sat frozen for the rest of the run
            # (observed: 24 s stuck in CASHED, throws stuck at 1). The yellow
            # CASHOUT panel, by contrast, exists ONLY while a round is live --
            # a direct pixel answer. Absence is required twice in a row so a
            # single animating frame cannot make the bot bet into a live round.
            if (not args.no_auto_go and mreader_ is not None
                    and (t_now - last_live_t) > 0.6):
                last_live_t = t_now
                try:
                    sub, ox, oy = grab_ui(cx, cy, r)
                    live = find_cashout_box(sub, cx - ox, cy - oy, r) is not None
                except Exception:                                # noqa: BLE001
                    live = True                     # fail safe: assume live
                if live:
                    not_live_n = 0
                else:
                    if os.environ.get("KN_DUMP_UI"):
                        os.makedirs("temp/ui_miss", exist_ok=True)
                        cv2.imwrite(
                            os.path.join("temp/ui_miss",
                                         f"{t_now - t_start:07.2f}"
                                         f"_nl{not_live_n + 1}.png"), sub)
                    not_live_n += 1
                    # Three checks at 0.6 s = 1.8 s without a gold panel. Two
                    # was enough to score a live round as lost whenever the
                    # panel dimmed on two consecutive samples; one extra sample
                    # costs 0.6 s of delay on a genuine round end and makes a
                    # false one much less likely.
                    if not_live_n >= 3:
                        round_dead = True
                        # The round is not running. If we never cashed out, it
                        # ended by dying, and it must be closed HERE -- otherwise
                        # the next round's throws get attributed to this one and
                        # the per-round CSV reports peaks that round never had.
                        if round_open and not cashed_out and round_throws > 0:
                            close_round("lost", t_now)
                            print(f"[auto] round {round_no} ended with no live "
                                  f"panel -- counted as a loss")
                        # Do NOT clear cashed_out here. Doing so let the next
                        # 5 Hz read fire the cash-out click again on a stale
                        # number: one round produced FIVE cash-out clicks.
                        # The latch is cleared only by a confirmed new round.
                        if state == "FLYING":
                            state = "WAIT"
                            t_launch = t_reload = None

                        # reset rotation tracking for the new round
                        rotations_seen = 0.0
                        last_omega_sign = 0
                        sign_stable_since = 0.0
            # ---- round genuinely not running -> press GO ------------------ #
            # A live throw empties the slot for ~67 ms (n=44). 1.5 s of empty
            # slot means there is no round. This -- not n_obs==0 -- is what a
            # finished round looks like, because the decorative knives baked
            # into the art never disappear.
            if round_dead:
                if state == "FLYING":
                    state = "WAIT"
                    t_launch = t_reload = None
                    wr.writerow([round(t_now - t_start, 3), "round_dead", "", "",
                                 "", "", "", round(sf, 4), n_obs,
                                 "slot empty 1.5 s; state released", mult_str])
                if (not args.dry_run and not args.no_auto_go
                        and (t_now - last_go_t) > 1.5):
                    if go_pt is None:
                        # No throw gates belong here. Pressing GO is how a
                        # finished round is restarted; blocking it would stall
                        # the whole run. The gates belong on the throw.
                        sub, ox, oy = grab_ui(cx, cy, r)
                        g = find_go_button(sub, cx - ox, cy - oy, r)
                        go_pt = None if g is None else (g[0] + ox, g[1] + oy)
                    if go_pt is None:
                        # Blind click, but only here. This branch runs after the
                        # launcher has been empty for 1.5 s, so no round is live:
                        # there is no bet to lose and no rung to give away. The
                        # disc's place relative to the log is measured on this
                        # layout, so the ratio is a real position, not a guess.
                        go_pt = (int(round(cx + 2.96 * r)),
                                 int(round(cy + 4.29 * r)))
                        print("[auto] GO disc not detectable -- using the "
                              "measured disc position")
                    else:
                        print(f"[auto] no round running -> GO at {go_pt}")
                        click_at(*go_pt)
                        wr.writerow([round(t_now - t_start, 3), "click_go", "", "",
                                     "", "", "", round(sf, 4), n_obs,
                                     str(go_pt), mult_str])
                        last_go_t = t_now
                        time.sleep(0.8)
                continue

            # ---- flight bookkeeping -------------------------------------- #
            if state == "FLYING":
                low = sf < 0.5 * (slot_base or 0.15)
                if low and t_launch is None:
                    t_launch = t_now
                elif (not low) and t_launch is not None and t_reload is None:
                    t_reload = t_now
                    hit = n_obs > obs_at_click
                    hits += int(hit)
                    round_hits += int(hit)
                    # ---- TRUE landing angle ------------------------------- #
                    # The first version measured "the knife nearest the impact
                    # line". That is whichever knife happens to sit there, so it
                    # could never differ from 180 by more than the spacing
                    # between knives, and its standard deviation described the
                    # picture rather than the aim. It was worthless.
                    #
                    # This version finds the knife that is actually NEW: take
                    # every knife we saw at press time, rotate each one by the
                    # measured spin over the elapsed time, and the survivor that
                    # matches none of them is the one that just landed. Rewinding
                    # it to press time puts it in the same frame of reference as
                    # the gap centre we aimed at, so the difference IS the aim
                    # error in degrees.
                    #
                    # It deliberately does not require a hit. Requiring one would
                    # censor the sample to "errors inside the gap" and hide the
                    # very misses we are trying to explain.
                    land_txt = ""
                    # Honest hit label: did the ladder advance by one rung from
                    # press time to landing? This is the signal future tuning
                    # must use; the knife-count counter is known to undercount.
                    i0 = rung_index(mult_at_click)
                    i1 = rung_index(mult_val)
                    if i0 is not None and i1 is not None:
                        land_txt += f"mult_step={i1 - i0} "
                    if aim_obs0 and aim_t_frame is not None and aim_centre0 is not None:
                        dt_l = t_reload - aim_t_frame
                        olds = [((c + aim_omega0 * dt_l) % 360.0) for c in aim_obs0]
                        cands = [(min(abs(ang_diff(lt.polar_to_game(s + wi / 2.0), o))
                                      for o in olds),
                                  lt.polar_to_game(s + wi / 2.0))
                                 for s, wi in m["obs"]]
                        if cands:
                            match, c_new = max(cands)
                            if match >= 4.0:      # clearly not a pre-existing knife
                                land_press = (c_new - aim_omega0 * dt_l) % 360.0
                                err_true = ang_diff(land_press, aim_centre0)
                                land_txt = (f"aimerr={err_true:+6.1f} "
                                            f"sep={match:4.1f} "
                                            f"lag={dt_l:5.3f} ")
                    wr.writerow([
                        round(t_now - t_start, 3), "landed", round(aim_deg, 1),
                        round(m["omega"], 1), round(aim_gap_w, 1),
                        round(aim_slack, 1), round(args.t_total, 4),
                        round(sf, 4), n_obs,
                        f"press_to_launch_ms={(t_launch-t_click)*1000:.1f} "
                        f"slot_empty_ms={(t_reload-t_launch)*1000:.1f} "
                        f"press_to_reload_ms={(t_reload-t_click)*1000:.1f} "
                        f"pred_land={aim_pred:.1f} hit={int(hit)} "
                        f"{land_txt}obs {obs_at_click}->{n_obs}", mult_str])
                    # ---- armed cash-out ------------------------------------ #
                    # The panel is the authority, not the number. If the throw
                    # that was meant to finish the round put a knife in, the
                    # CASHOUT panel is gold on this very frame and one click
                    # banks the rung we aimed at. If it missed, the panel is
                    # gone and there is nothing to click -- the round-over
                    # path below scores it, exactly as before.
                    if cash_aim is not None and not cashed_out:
                        _aim = cash_aim
                        cash_aim = None
                        box = None
                        try:
                            sub, ox, oy = grab_ui(cx, cy, r)
                            got = find_cashout_box(sub, cx - ox, cy - oy, r)
                            if got is not None:
                                box = (got[0] + ox, got[1] + oy)
                        except Exception:                      # noqa: BLE001
                            box = None
                        if box is not None:
                            click_at(*box)
                            cash_pt = box
                            cleared = False
                            reclicks = 0
                            _v0 = time.perf_counter()
                            while time.perf_counter() - _v0 < 1.5:
                                time.sleep(0.1)
                                try:
                                    sub2, ox2, oy2 = grab_ui(cx, cy, r)
                                    still = find_cashout_box(
                                        sub2, cx - ox2, cy - oy2, r) is not None
                                except Exception:              # noqa: BLE001
                                    still = False
                                if not still:
                                    cleared = True
                                    break
                                # The gold panel lingers ~1 s even on success,
                                # so only re-click late, and only once.
                                if reclicks == 0 and time.perf_counter() - _v0 > 1.0:
                                    click_at(*box)
                                    reclicks = 1
                            if cleared:
                                cashed_out = True
                                cashed.append(_aim)
                                t_cashout = t_now
                                last_cash_t = t_now
                                close_round("won", t_now, _aim)
                                wr.writerow([
                                    round(t_now - t_start, 3), "CASHOUT", "",
                                    "", "", "", "", round(sf, 4), n_obs,
                                    f"armed: banked x{_aim:.2f} on the landing "
                                    f"frame (panel cleared in "
                                    f"{time.perf_counter() - _v0:.2f}s, "
                                    f"reclicks {reclicks})", mult_str])
                                print(f"[auto] *** CASHED OUT at x{_aim:.2f} "
                                      f"on landing (armed, reader not used) ***")
                                state = "CASHED"
                                t_state = t_now
                                t_launch = t_reload = None
                                continue
                    state = "WAIT"
                    t_launch = t_reload = None
                # ---- watchdogs ------------------------------------------- #
                # These are deliberately NOT part of the chain above. When they
                # were `elif`s, a slot that read low and never recovered skipped
                # every timeout and left the bot frozen in FLYING forever --
                # observed live: one throw, then 46 s of nothing, while the game
                # sat there perfectly playable.
                if state == "FLYING":
                    if t_launch is None and (t_now - t_state) > 1.10:
                        # Never saw the slot empty: the key did not register, or
                        # the reload was faster than one frame.
                        hit = n_obs > obs_at_click
                        hits += int(hit)
                        round_hits += int(hit)
                        wr.writerow([
                            round(t_now - t_start, 3), "no_launch_seen",
                            round(aim_deg, 1), round(m["omega"], 1),
                            round(aim_gap_w, 1), round(aim_slack, 1),
                            round(args.t_total, 4), round(sf, 4), n_obs,
                            f"hit={int(hit)} obs {obs_at_click}->{n_obs} "
                            f"slot_base={slot_base}", mult_str])
                        print("[auto] WARNING: no launch seen in 1.1 s -- the "
                              f"{args.trigger} trigger may not reach the game")
                        state = "WAIT"
                        t_launch = t_reload = None
                    elif (t_launch is not None and t_reload is None
                          and (t_now - t_launch) > 1.10):
                        # The slot emptied and never came back. Recover instead
                        # of waiting for a frame that may never arrive.
                        wr.writerow([
                            round(t_now - t_start, 3), "flight_stalled",
                            round(aim_deg, 1), round(m["omega"], 1),
                            round(aim_gap_w, 1), round(aim_slack, 1),
                            round(args.t_total, 4), round(sf, 4), n_obs,
                            f"slot_base={slot_base} launch_at={t_launch - t_start:.2f}",
                            mult_str])
                        print("[auto] slot emptied and never recovered -- "
                              "recovering to WAIT")
                        state = "WAIT"
                        t_launch = t_reload = None

            # ---- aim ------------------------------------------------------ #
            # Hard gate: never throw a knife AFTER we have already reached the
            # cash-out target. The reader is only 5 Hz, so the log could be at
            # 1.48 for up to 0.2 s before we see it; if we fired in that window
            # we would cash out one rung higher than intended. The correct
            # behavior is: held >= target -> cash out (handled above), otherwise
            # we should not be in WAIT at all. But as a second line of defence,
            # refuse to throw if the HELD value is already at target.
            if (state == "WAIT" and args.cashout_at is not None
                    and mult_val is not None
                    and mreader.current_from_log(mult_val) is not None
                    and mreader.current_from_log(mult_val) >= args.cashout_at - 1e-9):
                continue

            if state == "WAIT" and m["good"] and throws < args.max_throws:
                omega_raw = m["omega"]
                relaxed = (t_now - t_last_throw) > args.patience
                # Reversals are where the misses live: 50 % hits below
                # 150 deg/s against 89 % above it, because that is exactly
                # where omega is small AND changing sign. So demand a sign that
                # has held, and real movement -- unless we have waited so long
                # that standing still has become the larger risk.
                recent = [w for (tt, w) in trk.omega_hist
                          if tt >= t_now - args.stability]
                stable = bool(recent) and (all(w > 0 for w in recent)
                                           or all(w < 0 for w in recent))
                floor = 25.0 if relaxed else args.min_omega
                omega = (omega_raw if (abs(omega_raw) >= floor
                                       and (stable or relaxed)) else None)
                # The log ramps between ~195 and ~335 deg/s over about half a
                # second. Any fixed-omega prediction made during a ramp is
                # wrong by tens of degrees, so simply do not throw then:
                # waiting is free, a bad throw costs the round. This gate
                # removes the measured 14 deg of aim scatter at its source.
                alpha = m["alpha"]
                if omega is not None and abs(alpha) > args.max_alpha:
                    omega = None
                still = omega is not None and abs(omega) < 30.0
                # While t_total is still a guess, only take wide gaps.
                need = args.min_gap if throws >= 3 else max(args.min_gap, 50.0)

                # The lead is the one free parameter that the hit/miss stream
                # can actually identify: with the log turning at a steady rate,
                # a wrong lead and a wrong aim are the same number of degrees,
                # and the landed knife always sits on the impact line, so it
                # carries no information. Sweeping the lead across a run and
                # counting hits per value is the only unbiased way to find it.
                t_lead = args.t_total
                if sweep_values:
                    t_lead = random.choice(sweep_values)

                now_opts = []
                future_opts = []
                for start, w in (m["gaps"] if omega is not None else []):
                    if w < need:
                        continue
                    centre = lt.polar_to_game(start + w / 2.0)
                    # Carry the measured acceleration through the flight: the
                    # rotation is w*t + alpha*t^2/2, not w*t.
                    pred = (centre + omega * t_lead
                            + 0.5 * alpha * t_lead ** 2)
                    err = ang_diff(pred, args.impact_deg)
                    slack = w / 2.0 - KNIFE_FULL_DEG / 2.0 - SAFETY_DEG - abs(err)
                    now_opts.append((slack, centre, w, pred, err))

                    # Earliest future instant that puts the centre on the line.
                    # Skipped when the log is effectively still: dividing by a
                    # near-zero omega is what makes the naive formulation blow
                    # up, and there is nothing to schedule anyway.
                    if not still:
                        t_reach = ang_diff(args.impact_deg, centre) / omega
                        if t_reach < 0.0:
                            t_reach += 360.0 / abs(omega)
                        t_ideal = t_now + t_reach - t_lead
                        if t_ideal >= t_now - 0.005:
                            future_opts.append((t_ideal, centre, w))

                now_opts.sort(reverse=True)
                chosen = None
                # The margin floor is shared by BOTH selection paths. It steps
                # down after a long wait, because gaps shrink as knives
                # accumulate and a fixed floor can deadlock late in a round; it
                # never steps below a positive margin.
                waited = t_now - t_last_throw
                if waited > 20.0:
                    floor_slack = max(6.0, args.min_slack - 8.0)
                elif waited > 12.0:
                    floor_slack = max(9.0, args.min_slack - 4.0)
                else:
                    floor_slack = args.min_slack
                if now_opts:
                    slack, centre, w, pred, _err = now_opts[0]
                    fast = abs(omega) > args.slow_omega
                    gate = 0.0 if (relaxed or not fast) else SLACK_HIGH_OMEGA
                    gate = max(gate, floor_slack)
                    if slack >= gate:
                        chosen = (t_now, centre, w, pred, slack, "now")
                if chosen is None and future_opts:
                    t_ideal, centre, w = min(future_opts)
                    # The scheduled path has NO measured prediction error: it
                    # fires on the assumption that the centre arrives exactly on
                    # the line. Its entire margin is the gap itself, so the gap
                    # must clear the same floor. Without this the gate was
                    # bypassed on 5 of 13 throws, which is how a "strict" run
                    # still threw 13 knives in 23 seconds.
                    sched_slack = w / 2.0 - KNIFE_FULL_DEG / 2.0 - SAFETY_DEG
                    if ((t_ideal - t_now) <= LEAD_S
                            and sched_slack >= floor_slack):
                        chosen = (t_ideal, centre, w, float("nan"),
                                  sched_slack, "sched")

                if chosen is not None:
                    t_target, centre, w, pred, slack, how = chosen
                    t_target = max(t_target, t_now)
                    aim_deg, aim_gap_w, aim_slack, aim_pred = centre, w, slack, pred
                    obs_at_click = n_obs
                    # The obs counter undercounts hits by ~15 % (it misses a
                    # hit whenever the knife count is mis-read between throws).
                    # Record the multiplier at press time as well, so a later
                    # analysis can decide a hit from the ladder advancing,
                    # which the verified reader gets right. Logging only.
                    mult_at_click = mult_val
                    # ---- arm the cash-out ---------------------------------- #
                    # Measured 2026-11-20, round 9 of the first 10-round x2.12
                    # run: the last knife landed at 211.89 with the ladder on
                    # x2.12, the reader then returned "no_text" for 0.8 s while
                    # the raised rung animated, and the round had already reset
                    # before a trusted x2.28 could be read. A round sitting
                    # exactly on the target was scored as a loss. So the throw
                    # that is meant to finish the round does not depend on the
                    # reader at all: we know which rung it becomes, and the
                    # cash-out target is located on pixels.
                    cash_aim = None
                    if args.cashout_at and not args.dry_run:
                        _h0 = mreader.current_from_log(mult_val)
                        _after = next_rung(_h0)
                        if (_after is not None
                                and _after >= args.cashout_at - 1e-9):
                            cash_aim = _after
                    # Snapshot for the landing-angle measurement, which the
                    # reload branch below needs. `angle` is stored in GAME
                    # coordinates on purpose: the gap centre we aim at is also
                    # game coordinates, so the difference between the two is a
                    # real aim error and not a coordinate offset.
                    aim_obs0 = [lt.polar_to_game(s + wi / 2.0)
                                for s, wi in m["obs"]]
                    aim_t_frame = t_now
                    aim_omega0 = omega
                    aim_centre0 = centre
                    if not args.dry_run:
                        if (args.trigger == "space" and not args.no_focus_check
                                and game_root
                                and foreground_root() != game_root):
                            # Take the focus back instead of stalling. Without
                            # this the bot freezes the moment any other window
                            # is touched, including the chat window. Rate
                            # limited, because SetForegroundWindow is expensive
                            # and Windows throttles repeated calls.
                            if (not args.no_auto_focus
                                    and (t_now - last_focus_try) > 0.5):
                                last_focus_try = t_now
                                silently_focused = focus_window(game_root)
                                if silently_focused:
                                    print("[auto] took the focus back for the game")
                            if foreground_root() != game_root:
                                if not warned_focus:
                                    print("[auto] HOLDING: the game window is not "
                                          f"focused (foreground 0x{foreground_root():X},"
                                          f" game 0x{game_root:X}) -- space not sent")
                                    warned_focus = True
                                continue
                        warned_focus = False
                        # ---- throw gates ---------------------------------------
                        # 1) wait two full rotations after the round starts: the
                        #    opening throws are the ones with least evidence
                        #    about which way the log is actually turning.
                        if rotations_seen < round_start_rotations:
                            continue
                        # 2) the rotation sign must have held for at least
                        #    --stability, which covers the ~205 ms flight.
                        if t_now - sign_stable_since < args.stability:
                            continue
                        # 3) never throw into a redraw. At x1.35 the game wipes
                        #    the knives and blanks the log; the picture we would
                        #    aim with is already gone by the time the knife lands.
                        if t_now - last_unstable_t < 0.60:
                            continue
                        # The --min-slack margin gate is enforced during
                        # candidate selection, where the step-down lives.
                        # --------------------------------------------------------
                        sleep_until(t_target)
                        if args.trigger == "space":
                            t_click = press_space()
                        else:
                            t_click = click_at(*throw_pt)
                    else:
                        t_click = time.perf_counter()
                    throws += 1
                    open_round(t_now)
                    round_throws += 1
                    t_last_throw = t_click
                    t_state = t_click
                    state = "FLYING"
                    t_launch = t_reload = None
                    wr.writerow([
                        round(t_now - t_start, 3), "throw", round(centre, 1),
                        round(omega_raw, 1), round(w, 1),
                        round(slack, 1) if slack == slack else "",
                        round(t_lead, 4), round(sf, 4), n_obs,
                        f"{how} {'slow' if abs(omega) <= args.slow_omega else 'fast'}"
                        f" pred={pred:.1f} a={m['alpha']:+.0f}"
                        + (" dry" if args.dry_run else ""), mult_str])

            # ---- periodic re-locate, in case space scrolled the page ----- #
            if (args.drift_check and throws and throws % args.drift_check == 0
                    and throws != getattr(main, "_last_drift", None)):
                main._last_drift = throws
                chk = locate(verbose=False, expect=(cx, cy))
                if chk is None:
                    print("[auto] drift check found nothing usable -- keeping "
                          "the current calibration")
                elif (abs(chk["cx"] - cx) > 4 or abs(chk["cy"] - cy) > 4
                      or abs(chk["r"] - r) > 3):
                    dr = abs(chk["r"] - r) / max(r, 1.0)
                    dpos = math.hypot(chk["cx"] - cx, chk["cy"] - cy)
                    if dr > 0.05 or dpos > 40:
                        # Seen live: a re-locate returned r=105 where the truth
                        # was 126, a 17 % radius error that silently corrupts
                        # every remap grid. A drift check must correct small
                        # movement, never swap in a different-sized circle.
                        print(f"[auto] drift candidate rejected: r {r:.0f}->"
                              f"{chk['r']:.0f} ({100*dr:+.0f}%), moved "
                              f"{dpos:.0f} px -- keeping the calibration")
                    else:
                        print(f"[auto] DRIFT: target moved ({cx:.0f},{cy:.0f},"
                              f"r{r:.0f}) -> ({chk['cx']:.0f},{chk['cy']:.0f},"
                              f"r{chk['r']:.0f})  re-initialising")
                        cx, cy, r = chk["cx"], chk["cy"], chk["r"]
                        bbox = chk["bbox"]
                        lcx, lcy = cx - bbox["left"], cy - bbox["top"]
                        L = chk
                        trk = Tracker(chk["mx_tex"], chk["my_tex"],
                                      chk["mx_pro"], chk["my_pro"])
                        slot_base = None
                        if args.click_x is None:
                            throw_pt = (int(round(cx - 3.00 * r)),
                                        int(round(cy - 1.00 * r)))
                        wr.writerow([round(t_now - t_start, 3), "relocate", "",
                                     "", "", "", "", round(sf, 4), n_obs,
                                     f"({cx:.0f},{cy:.0f},r{r:.0f})", mult_str])

            if args.trace:
                if tw is None:
                    tw = csv.writer(open(args.trace, "w", newline="",
                                         encoding="utf-8"))
                    tw.writerow(["t", "angle", "omega", "slot", "n_obs",
                                 "state", "d_throw", "d_click", "impact_off"])
                # TRUE aim error, measured every frame: how far the centre of
                # the gap that straddles the impact line is from the impact
                # line itself. The knife always sticks AT the impact line, so
                # its final position says nothing about the aim. The gap centre
                # does. On the frame the knife lands, this number IS the error
                # that made it hit or miss, with no rewinding, no omega
                # integration and no guessing which knife is new.
                off = None
                for _s, _w in m["gaps"]:
                    _c = lt.polar_to_game(_s + _w / 2.0)
                    _d = ang_diff(_c, args.impact_deg)
                    if abs(_d) <= _w / 2.0:
                        off = _d
                        break
                tw.writerow([
                    round(t_now - t_start, 3), round(m.get("angle", 0.0), 2),
                    round(m["omega"], 1), round(sf, 4), n_obs, state,
                    round(t_now - t_last_throw, 3) if t_last_throw else "",
                    round(t_now - t_click, 3) if t_click else "",
                    round(off, 1) if off is not None else ""])

            if t_now - last_log > 2.0:
                last_log = t_now
                print(f"[auto] {t_now-t_start:6.1f}s  w {m['omega']:7.1f}  "
                      f"obs {n_obs:2d}  gaps {len(m['gaps']):2d}  slot {sf:.3f}"
                      f"  throws {throws}  hits {hits}  {mult_str or 'x??':>5}"
                      f"  best {('x%.2f' % best_ever) if best_ever else 'x??':>5}"
                      f"  fl={'L' if t_launch is not None else '-'}"
                      f"{'R' if t_reload is not None else '-'}"
                      f" age {t_now - t_state:5.1f}s"
                      f"  {state}")
    finally:
        ctypes.windll.user32.SetCursorPos(int(orig_cursor[0]), int(orig_cursor[1]))
        fh.close()

    print("\n" + "=" * 64)
    close_round("lost", time.perf_counter())     # a round cut short by the stop
    try:
        rfh.close()
    except Exception:
        pass

    print(f"throws {throws}   hits {hits}   rate {100*hits/max(1,throws):.1f}%")
    tot = wins + losses
    print(f"rounds {tot}   cashed {wins}   lost {losses}   "
          f"round win rate {100*wins/max(1,tot):.1f}%")
    print(f"net money (bet {args.bet:.0f})  {pnl:+.2f}")
    if cashed:
        print(f"cash-out sizes : {' '.join('x%.2f' % c for c in cashed)}")
    print(f"round log: {rounds_path}")
    print(f"best multiplier seen in this round : "
          f"{('x%.2f' % peak_round) if peak_round else 'not read'}")
    print(f"best multiplier seen in the run    : "
          f"{('x%.2f' % best_ever) if best_ever else 'not read'}")
    if args.cashout_at:
        if cashed:
            avg = sum(cashed) / len(cashed)
            print(f"rounds cashed out                  : {len(cashed)}"
                  f"  ({' '.join('x%.2f' % c for c in cashed)})")
            print(f"average cash-out                   : x{avg:.2f}")
            print("  (money is bet x multiplier; the bet is set in the game, so "
                  "the balance is the only true P&L)")
        else:
            print("rounds cashed out                  : 0 "
                  f"(target x{args.cashout_at:.2f} never reached)")
    print(f"log: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
