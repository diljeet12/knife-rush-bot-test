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
            "angle": self.angle, "omega": self.omega,
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
        if abs(xc - cx) > 5.0 * r or yc <= cy:
            continue
        if best is None or area > best[0]:
            best = (area, float(xc), float(yc))
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
        area >= 4000          the panel is ~200x60 px of solid yellow
        w/h >= 1.6            a wide bar, unlike the small gold ladder labels
        fill >= 0.55          solid block, not a ring or an icon
        below the log centre  the panel bar sits under the target
    """
    b = frame[:, :, 0].astype(np.int16)
    g = frame[:, :, 1].astype(np.int16)
    rr = frame[:, :, 2].astype(np.int16)
    mask = ((rr > 170) & (g > 130) & (b < 110)).astype(np.uint8)
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
    ap.add_argument("--min-omega", type=float, default=120.0,
                    help="do not throw below this |omega|: measured 50%% hit "
                         "rate under 150 deg/s because that is a reversal, "
                         "where omega is small and changing sign")
    ap.add_argument("--stability", type=float, default=0.45,
                    help="omega must have kept one sign for this many seconds")
    ap.add_argument("--slow-omega", type=float, default=SLOW_OMEGA)
    ap.add_argument("--patience", type=float, default=6.0,
                    help="after this long with no throw, stop waiting for slow")
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
    ap.add_argument("--dump-mult", default=None,
                    help="save the log-centre crop whenever the read changes, "
                         "so every logged value can be audited against pixels")
    ap.add_argument("--outdir", default="recordings")
    args = ap.parse_args()

    sct = mss.MSS()
    mon = sct.monitors[1]
    sw, sh = mon["width"], mon["height"]

    def locate(verbose=True, expect=None):
        shot = np.array(sct.grab(mon))[:, :, :3]
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
    L = None
    for attempt in range(8):
        L = locate(verbose=(attempt == 0))
        if L is not None:
            break
        time.sleep(0.35)
    if L is None:
        print("[auto] no target on screen after 8 tries -- open the game first")
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

    # ---- throw / GO points ------------------------------------------------ #
    throw_pt = (
        args.click_x if args.click_x is not None else int(round(cx - 3.00 * r)),
        args.click_y if args.click_y is not None else int(round(cy - 1.00 * r)),
    )
    go_pt = ((args.go_x, args.go_y)
             if (args.go_x is not None and args.go_y is not None)
             else find_go_button(L["shot"], cx, cy, r))

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
        nonlocal round_open, wins, losses, pnl
        if not round_open:
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
    t_launch = None
    t_reload = None
    slot_base = None
    throws = 0
    hits = 0
    t_last_throw = t_start
    warned_focus = False
    last_go_t = 0.0
    slot_low_since = None
    last_log = 0.0
    mult_val = None          # last trusted read of the log-centre number
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
            frame = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(
                raw.height, raw.width, 4)[:, :, :3].copy()
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

            # ---- round boundary ------------------------------------- #
            # A finished round swaps the log for a fresh one, which drops the
            # obstacle count by several at once (measured 15->8, 12->8, 10->7).
            # The multiplier reset is the other signal, but it can be missed
            # when the number is occluded, so both are used. close_round is a
            # no-op when the round was already closed by a cash-out.
            if (round_open and prev_obs is not None
                    and prev_obs - n_obs >= 4):
                peak = mreader.current_from_log(peak_round) if peak_round else 0.0
                close_round("lost", t_now)
                print(f"[auto] round {round_no} LOST before target "
                      f"(held peaked x{peak:.2f}, {round_hits} hits)")
                state = "WAIT"
                t_launch = t_reload = None
            prev_obs = n_obs

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
                        peak_round = None
                        cashed_out = False
                    mult_val = v
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
                    if (args.cashout_at and not cashed_out and go_pt is not None
                            and held is not None
                            and held >= args.cashout_at - 1e-9
                            and (last_cash_t is None
                                 or t_now - last_cash_t > 3.0)):
                        # Locate the yellow panel on a fresh full grab; the
                        # cropped frame does not contain the whole bar.
                        box = None
                        try:
                            full = np.array(sct.grab(mon))[:, :, :3]
                            box = find_cashout_box(full, cx, cy, r)
                        except Exception:
                            box = None
                        if box is None:
                            box = (int(round(cx + 0.27 * r)),
                                   int(round(cy + 4.33 * r)))
                        click_at(*box)
                        cash_pt = box
                        cashed_out = True
                        cashed.append(held)
                        t_cashout = t_now
                        last_cash_t = t_now
                        close_round("won", t_now, held)
                        wr.writerow([
                            round(t_now - t_start, 3), "CASHOUT", "", "", "", "",
                            "", round(sf, 4), n_obs,
                            f"held x{held:.2f} (log printed x{v:.2f}) "
                            f"clicked {cash_pt}", mult_str])
                        print(f"[auto] *** CASHED OUT at x{held:.2f} "
                              f"(log read x{v:.2f}) ***")
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
                    if (state == "CASHED" and t_cashout is not None
                            and (t_now - t_cashout > 6.0
                                 or (t_now - t_cashout > 2.5
                                     and v <= 1.01 + 1e-9))):
                        state = "WAIT"
                        cashed_out = False
                        t_cashout = None
                        print("[auto] next round -> throwing again")

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
                    live = find_cashout_box(
                        np.array(sct.grab(mon))[:, :, :3], cx, cy, r) is not None
                except Exception:                                # noqa: BLE001
                    live = True                     # fail safe: assume live
                if live:
                    not_live_n = 0
                else:
                    not_live_n += 1
                    if not_live_n >= 2:
                        round_dead = True
                        # Do NOT clear cashed_out here. Doing so let the next
                        # 5 Hz read fire the cash-out click again on a stale
                        # number: one round produced FIVE cash-out clicks.
                        # The latch is cleared only by a confirmed new round.
                        if state == "FLYING":
                            state = "WAIT"
                            t_launch = t_reload = None

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
                        go_pt = find_go_button(np.array(sct.grab(mon))[:, :, :3],
                                               cx, cy, r)
                    if go_pt is None:
                        print("[auto] no round running and no GO button -- idling")
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
                if sf < 0.5 * (slot_base or 0.15):
                    if t_launch is None:
                        t_launch = t_now
                elif t_launch is not None and t_reload is None:
                    t_reload = t_now
                    hit = n_obs > obs_at_click
                    hits += int(hit)
                    round_hits += int(hit)
                    wr.writerow([
                        round(t_now - t_start, 3), "landed", round(aim_deg, 1),
                        round(m["omega"], 1), round(aim_gap_w, 1),
                        round(aim_slack, 1), round(args.t_total, 4),
                        round(sf, 4), n_obs,
                        f"press_to_launch_ms={(t_launch-t_click)*1000:.1f} "
                        f"slot_empty_ms={(t_reload-t_launch)*1000:.1f} "
                        f"press_to_reload_ms={(t_reload-t_click)*1000:.1f} "
                        f"pred_land={aim_pred:.1f} hit={int(hit)} "
                        f"obs {obs_at_click}->{n_obs}", mult_str])
                    state = "WAIT"
                    t_launch = t_reload = None
                elif t_now - t_state > 1.10:
                    # Never saw the slot empty: the key did not register, or the
                    # reload was faster than one frame.
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

            # ---- aim ------------------------------------------------------ #
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
                still = omega is not None and abs(omega) < 30.0
                # While t_total is still a guess, only take wide gaps.
                need = args.min_gap if throws >= 3 else max(args.min_gap, 50.0)

                now_opts = []
                future_opts = []
                for start, w in (m["gaps"] if omega is not None else []):
                    if w < need:
                        continue
                    centre = lt.polar_to_game(start + w / 2.0)
                    pred = centre + omega * args.t_total
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
                        t_ideal = t_now + t_reach - args.t_total
                        if t_ideal >= t_now - 0.005:
                            future_opts.append((t_ideal, centre, w))

                now_opts.sort(reverse=True)
                chosen = None
                if now_opts:
                    slack, centre, w, pred, _err = now_opts[0]
                    # Patience only ever LOWERS the bar to zero; it never
                    # authorises negative slack, because negative slack is a
                    # knife in the log, not a throw.
                    fast = abs(omega) > args.slow_omega
                    gate = 0.0 if (relaxed or not fast) else SLACK_HIGH_OMEGA
                    if slack >= gate:
                        chosen = (t_now, centre, w, pred, slack, "now")
                if chosen is None and future_opts:
                    t_ideal, centre, w = min(future_opts)
                    if (t_ideal - t_now) <= LEAD_S:
                        chosen = (t_ideal, centre, w, float("nan"), float("nan"),
                                  "sched")

                if chosen is not None:
                    t_target, centre, w, pred, slack, how = chosen
                    t_target = max(t_target, t_now)
                    aim_deg, aim_gap_w, aim_slack, aim_pred = centre, w, slack, pred
                    obs_at_click = n_obs
                    if not args.dry_run:
                        if (args.trigger == "space" and not args.no_focus_check
                                and game_root
                                and foreground_root() != game_root):
                            if not warned_focus:
                                print("[auto] HOLDING: the game window is not "
                                      f"focused (foreground 0x{foreground_root():X},"
                                      f" game 0x{game_root:X}) -- space not sent")
                                warned_focus = True
                            continue
                        warned_focus = False
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
                        round(args.t_total, 4), round(sf, 4), n_obs,
                        f"{how} {'slow' if abs(omega) <= args.slow_omega else 'fast'}"
                        f" pred={pred:.1f}" + (" dry" if args.dry_run else ""), mult_str])

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

            if t_now - last_log > 2.0:
                last_log = t_now
                print(f"[auto] {t_now-t_start:6.1f}s  w {m['omega']:7.1f}  "
                      f"obs {n_obs:2d}  gaps {len(m['gaps']):2d}  slot {sf:.3f}"
                      f"  throws {throws}  hits {hits}  {mult_str or 'x??':>5}"
                      f"  best {('x%.2f' % best_ever) if best_ever else 'x??':>5}"
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
