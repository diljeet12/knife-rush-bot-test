# Live Harness — what was actually observed

Written 2026-11-16 ~11:15, after the first live runs against the real browser
game (Knife Rush, `knife-rush.onout.games`).

Everything below is measured, not estimated. Where something is unverified it
says so.

---

## 1. The overlay works, and Windows hides it from the camera

The overlay is a full-screen, click-through, always-on-top Tk window using
`-transparentcolor`, with:

| ctypes call | effect |
|---|---|
| `WS_EX_TRANSPARENT` | clicks and drags pass through to the game |
| `WS_EX_LAYERED` | required for per-pixel colour keying |
| `WS_EX_NOACTIVATE` | it never steals focus from the game |
| `WDA_EXCLUDEFROMCAPTURE (0x11)` | **Windows omits it from screen capture** |

Proof of the last one: a `shot.py` grab taken while the overlay was live shows
a completely clean game — no box, no circle, no text. The overlay is invisible
to MSS. That is the ideal outcome, because the captured ROI then contains only
game pixels.

**Consequence:** screenshots cannot be used to check overlay alignment while
`WDA` is active. `--no-wda` exists for that check only.

---

## 2. Overlay alignment: verified to 1 px

Checked numerically while `--no-wda` was active, by classifying the exact ink
colour `#00d8ff` (BGR 255,216,0) and histogramming rows and columns:

| feature | expected | measured |
|---|---|---|
| capture box left | 757 | **756–757** |
| capture box right | 1162 | **1161–1162** |
| capture box top | 197 | **196–197** |
| capture box bottom | 785 | **784–785** |
| circle centre x | 960 | **960** (extremes 834 / 1086) |
| circle centre y | 400 | **400** (extremes 274 / 526) |
| circle radius | 126 | **126** |

Display is at **120 DPI = 125 % scaling**, which was the obvious suspect for a
coordinate offset. There is none: Tk and MSS agree on physical pixels.

**The overlay is correctly aligned. Nothing to fix here.**

---

## 3. `--no-wda` contaminates the tracker (do not measure with it)

With the overlay captured, `HoughCircles` locked onto **the HUD's own drawn
circle**: it reported `(960.0, 400.1) r=125.1` with "84 % sky around it" while
the tracker was pointing at empty sky. A perfect thin circle is exactly what
Hough wants.

`--no-wda` is therefore a **visual inspection mode only**. Any CSV recorded
with it is invalid.

---

## 4. Rotation speed: the live tool reproduces the offline number

This is the strongest result of the session. Offline video analysis gave
**194.5 °/s (79.7 % of the time)** and **321.2 °/s (20.3 %)**.

Live, from `recordings/live_20261116_110920.csv` (1 440 frames, 40.7 s):

| quantity | offline video | live harness |
|---|---|---|
| median `omega_fit` | 194.5 °/s | **194.2 °/s** |
| tier split | 79.7 / 20.3 | **78 / 22** |
| p95 | 331.6 °/s | **333.3 °/s** |

Agreement to 0.15 % on the median. The two-tier speed ramp is real and the
live pipeline measures it.

### Open bug: the sign is not normalised

`live_20261116_111012.csv` reports the *same* magnitude with the opposite
sign: median **−194.2 °/s**, 87 % negative, stable across a 391-frame median
run. Rotation is one-directional, so the sign is an accident of which way the
correlation peak landed on the first frames.

Not yet fixed. Fix is one line: decide direction once from the first ~0.5 s of
confident frames and flip the whole run to match.

---

## 5. Frame rate is adequate

| run | frames | span | median fps | median dt |
|---|---|---|---|---|
| 11:07:58 | 2 100 | 42.9 s | 56.2 | 17.1 ms |
| 11:09:20 | 1 440 | 40.7 s | 36.4 | 26.8 ms |
| 11:10:12 | 1 740 | 51.0 s | 34.0 | 27.9 ms |
| 11:11:11 | 4 020 | 102.6 s | 38.5 | 21.6 ms |

Best case 17.1 ms per frame — inside a 60 Hz budget. Worst case 27.9 ms, which
is 1.7 frames, so prediction is mandatory regardless.

ROI at 125 % scaling: **405 × 588 px at (757, 197) = 11.5 % of the screen.**

---

## 6. The real problem: it is not looking at the target most of the time

| run | frames with ≥ 8 knives visible | frames with 0 obstacles |
|---|---|---|
| 11:02:04 | 0.0 % | 12.9 % |
| 11:07:58 | 0.0 % | **78.9 %** |
| 11:09:20 | 56.2 % | 35.3 % |
| 11:10:12 | 62.2 % | 22.5 % |
| 11:11:11 | 19.5 % | 58.2 % |

The two earliest runs never saw a target at all — those are the
`(104, 222) r=39` and `(145, 219) r=91` false positives on the editor window.

The good runs still spend a third to half their frames reading empty sky,
because:

1. The game changes state (level complete, log destroyed, new log spawns).
2. The browser loses the foreground.
3. Calibration happens **once at startup and never re-checks**.

There is no "target lost" signal. The tracker happily logs
`n_obstacles = 0, widest_gap = 0.0, corridor_motion = 0.97` as if that were
data. It is not data; it is blindness.

### Status right now

The screen is **1.6 % sky** — the game is not visible. The tool is in its
`--wait` loop, correctly refusing to lock onto anything. That is the guard
working, not a failure.

---

## 7. Bugs found and fixed during this session

| bug | symptom | fix |
|---|---|---|
| blob scoring picked UI panels | `r=39` at `(104, 222)` | Hough circle search + sky-annulus guard |
| Hough radius 15 % short | `r=106.9` vs true `124.5` | 720-ray median + least-squares circle fit → `125.7` |
| Hough false positives | "found" a circle in an editor screenshot | require ≥ 35 % sky in the ring outside |
| `OCC_IN_FRAC = 0.80` | occupancy band was 1.33R–1.42R, a 9 % sliver | `0.36` → 1.12R–1.42R, matching the offline scan |
| `cv2.rectangle` on MSS buffer | `tracking_area.png` never written | `.copy()` the non-contiguous BGRA slice |
| no way to stop a click-through overlay | no focus, no keys | global `F10` stop / `F9` dump / `F8` spokes |

---

## 8. Records actually saved

| file | size | contents |
|---|---|---|
| `recordings/live_*.csv` × 7 | 808 KB | **10 747 data rows** of per-frame telemetry |
| `measurements/tracking_area.png` | 1.36 MB | full screen with the capture box drawn |
| `measurements/calibration.json` | 0.2 KB | last centre / radius / screen |
| `temp/roi_now.png` | 216 KB | 1:1 crop of the live ROI (bullseye, 9 knives) |
| `temp/shots/*.png` | 3 files | screen grabs used for the alignment proof |
| `temp/locate_test.png` | 445 KB | first successful circle fit |

CSV columns: `t, dt_ms, fps, angle_polar_deg, dtheta_deg, omega_inst_dps,
omega_fit_dps, conf_tex, sharp_tex, conf_pro, n_obstacles, widest_gap_deg,
widest_gap_game_deg, corridor_motion`.

---

## 9. What a live ROI actually looks like

One 1:1 crop, bullseye skin, multiplier **x1.85**, nine knives, two apples:

- capture box brackets the target *and* the whole waiting knife;
- gap labels read **16, 27, 27, 28, 29, 30, 32, 38 degrees**;
- the 38° gap is visually the widest empty arc. The labels match the picture.

Those gap widths are consistent with the 8.03° knife width measured offline:
nine knives at ~40° spacing leave ~32° nominal gaps, reduced or widened by
placement jitter.

---

## 10. Next actions, in order

1. Normalise the omega sign once per run (bug, §4).
2. Add target-lost detection: if `n_obstacles == 0` or the sky annulus turns
   non-sky for > 0.3 s, mark the run "not tracking" and re-locate. Never log
   zeros as measurements.
3. Re-verify the target periodically (~2 Hz) instead of once at startup.
4. Then, and only then, measure `T_total` closed-loop.
