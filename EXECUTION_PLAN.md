# EXECUTION PLAN — Knife Rush 2.00x Bot

**Supersedes:** `next plan.md` (the old PRD). The old PRD contains three claims that are
**not supported by any evidence in this repo** and must not be inherited:

| Old PRD claim | Status | Truth |
|---|---|---|
| "~16–17 consecutive perfect throws to 2.00x" | ❌ UNPROVEN | Two different ladder sequences exist. Real answer is somewhere between **14 and 23 knives**. Unknown until measured (Phase 0.1). |
| "Actuator fires within ±1 ms, verified via audio sync" | ❌ UNVERIFIABLE | No high-speed camera, no audio rig. Achievable and measurable target is **±2 ms std**, verified with `perf_counter`, not audio. |
| "Phase 1 latency, Phase 2 actuator" | ❌ IMPOSSIBLE ORDER | You cannot measure click→land latency without something that clicks. They are one phase. |

**Written:** 2026-11-17
**For:** the next AI model / next human session. Assume zero context.
**Repo:** `D:\random works by gs\KN helper` (git remote: `github.com/gurwinderwhara111/knife-rush-bot`, private)

---

# 0. READ THIS FIRST — 10 rules for whoever executes this

1. **Never run the tracker and claim a result without a CSV.** "It looked right" is not evidence.
2. **Never invent a function name.** Before importing anything from `live_track.py`, run
   `grep -n "^def \|^class " live_track.py` and confirm it exists. A previous attempt
   hallucinated 7 functions and produced a file that dies at import.
3. **Never touch a file marked DO NOT TOUCH (§4) without an explicit instruction.**
4. **Never change the measured constants** in §2. They come from data. If you think one is
   wrong, design a measurement — don't edit the number.
5. **Every phase has an acceptance test.** If the test fails, stop. Do not proceed on hope.
6. **Nothing is written to C:.** Not caches, not `pip install`, not temp files. If a package
   is missing, vendor it into `D:\...\vendor\` or make a venv on D:.
7. **The observer is the product until Phase 6.** No clicking, no keypresses into the game,
   until the observer's own numbers are verified correct.
8. **`--no-wda` recordings are invalid data.** That mode exists for pixel-alignment checks
   only. Any CSV recorded with it is contaminated by the overlay.
9. **Do not add machine learning.** The task is sub-pixel metrology, not perception.
   Classical correlation beats a CNN here by 10–30× on both accuracy and cost (§2.7).
10. **When unsure, write the uncertainty in the file and stop.** A wrong number silently
    baked into a constant costs more than a day of not knowing.

---

# 1. Mission

Build a vision-based observer + actuator that plays the browser game **Knife Rush**
(`knife-rush.onout.games`) in **demo/play-money mode only** and reaches the **2.00x
multiplier** without a miss.

**Hard constraints**

| Constraint | Value | Consequence |
|---|---|---|
| CPU | Intel i3-1115G4, 2C/4T, 3.0 GHz, no CUDA | Classical CV only. Budget 8 ms/frame. |
| RAM | 8 GB total, typically ~1.3 GB free | Ring buffer ≤ 20 frames. No frame caches. |
| Display | 1920×1080 physical, **125 % scaling (120 DPI)** | Tk and MSS agree on physical px — verified. |
| Disk | Project on D:, 131 GB free. C: has 14.4 GB | D: only. No exceptions. |
| Python | 3.13, `C:\Users\gurwi\AppData\Local\Programs\Python\Python313\python.exe` | Already installed. Do not reinstall. |
| Game | Browser canvas. No DevTools, no DOM, no JS injection. | Pure vision + synthetic input. |

---

# 2. VERIFIED GROUND TRUTH — do not re-derive, do not "improve"

Everything in this section was measured. Each row states its provenance. If you re-measure
and get a different number, that is a **finding** — report it, don't overwrite the table.

## 2.1 Rotation speed

| Quantity | Value | Provenance |
|---|---|---|
| Slow tier | **194.5 °/s** (0.540 rev/s), 79.7 % of time | `find_speed.py` on `gameplay1.mp4`, 30 fps, 1409 frames |
| Fast tier | **321.2 °/s** (0.892 rev/s), 20.3 % of time | same |
| Within-tier std | **1.25 °/s** (0.21 RPM) | `measurements/speed_report.md` |
| Absolute max ever observed | **343.5 °/s** | same |
| Live reproduction | **194.2 °/s** vs 194.5 offline = **0.15 % agreement** | `LIVE_HARNESS_REPORT.md` §4 |
| Transition band | smooth ramp over 0.5–1.0 s; **205–260 °/s is unstable — do not throw in it** | `SPEED_MEASUREMENT_REPORT.md` §1 |
| Direction | one-directional *per round*; **two sign flips seen at t=39.17 s and 39.37 s** in the video | same, §1 — interpreted as a round restart, **not proven** |

**⚠ Do not assume a fixed sign for a whole run.** See §5 trap T3.

## 2.2 Knife geometry

| Quantity | Value | Provenance |
|---|---|---|
| Knife angular width at r = R | **8.03°** median (p10 5.14°, p90 8.35°) | 1983 samples / 235 frames, `measure_knife_geometry.py` |
| Outliers 20–25° | apples, not knives | `KNIFE_TIMING_AND_GEOMETRY.md` §2 |
| Free gap p10 / p25 | 5.0° / 5.3° | bark ridges, **not usable** |
| Free gap p50 | **16.75°** | usable |
| Free gap p75 / p90 | 40.25° / 71.25° | comfortable |

## 2.3 Safe timing window

`window = (gap − 8.03°) / ω`

| Gap | @194.5 °/s | @321.2 °/s |
|---|---|---|
| 16° | 41.0 ms | **24.8 ms** (worst realistic case) |
| 30° | 112.9 ms | 68.4 ms |
| 38° | 154.1 ms | 93.3 ms |
| 72° | 328.9 ms | 199.2 ms |

**The game is solvable.** Achievable firing precision ~1–2 ms ⇒ 12× margin worst case.

## 2.4 Live system performance

| Quantity | Value | Provenance |
|---|---|---|
| Frame rate | 27.7 – 56.2 fps (median dt 17.1 – 28.0 ms) | 9 CSVs in `recordings/` |
| ROI at R≈126 | **405 × 588 px at (757, 197)** = 11.5 % of screen | `LIVE_HARNESS_REPORT.md` §5 |
| Overlay alignment | centre (960, 400), r = 126, box 756–1162 × 196–785 — **all to 1 px** | §2, measured with `--no-wda` |
| Overlay invisibility | 0 cyan pixels in an MSS grab → `WDA_EXCLUDEFROMCAPTURE` working | §1 |

## 2.5 Impact point

- **Game rule: 180°** (bottom of the log). The knife flies straight up a vertical line and
  sticks at the bottom. Visually confirmed in `GEOMATORY-and-screen-resulation/*.png`.
- **Pixel measurements disagree:** 175.7° (from the measurement table) vs 181.3° (from the
  overlay drawing) — a **13 px / 5.6° contradiction**, unresolved.
- 5.6° is **33 % of a median 16.75° gap**. This must be resolved (Phase 5) before aiming.

## 2.6 Environment facts that caused bugs before

- `cv2.imshow` **does not exist** in this OpenCV build (no HighGUI). Preview is Tk + PIL.
- The preview window **must be placed outside the ROI** or MSS photographs the preview of
  the game inside the game — a feedback loop that looks like "the tracker is drunk".
- `WDA_EXCLUDEFROMCAPTURE` requires **Win10 build 19041+**. On older builds the call
  **succeeds and silently behaves as `WDA_MONITOR`** (black box, not transparent).
  It also requires **DWM composing** — Remote Desktop disables DWM and breaks it.
- Windows default timer resolution is **15.625 ms**. `timeBeginPeriod` is per-process since
  Win10 2004 and does **not** make `Sleep` accurate below ~1–2 ms. Correct pattern for
  sub-millisecond firing is **sleep-then-spin** (§Phase 6).
- `pydirectinput` exists to work around **DirectX** games. This game is a **browser canvas**
  — normal Win32 messages. Its advantage may not apply. **Test, don't assume.**

## 2.7 Why classical CV, not AI

| | classical correlation | CNN |
|---|---|---|
| accuracy | 0.05–0.3° | ~±1° |
| cost/frame | 1–2 ms | 5–30 ms |
| training data | none needed | none available |
| budget @60 Hz | 16.7 ms total | inference alone can exceed it |

Cross-check between two independent estimators: **median disagreement 0.005°**, p95 0.020°.

---

# 3. KNOWN BROKEN — exact, with line numbers

`live_track.py` on disk = commit `c4bf1d6` ("fix: three critical bugs").
That commit **is the regression**. The version on GitHub (`b6cf6dc`) measured correctly.

## 3.1 BUG-1 — omega reads 2× the truth (SEVERITY: FATAL)

**Location:** `live_track.py` lines **924** and **958**

```python
924:  angle = (angle + dtheta) % 360.0          # add #1
930:  angle_hist.append((t_now, angle))         # history sampled here
958:  angle = (angle + dtheta) % 360.0          # add #2 — DUPLICATE, inside `if sign_decided:`
```

**Mechanism:** history becomes `d₁, 2d₁+d₂, 2d₁+2d₂+d₃ …`. Consecutive differences ≈ `2·dθ`.
The least-squares slope therefore returns **2×ω**.

**Evidence (recordings/live_20261116_112711.csv, the only run with the fixes active):**

| statistic | value | meaning |
|---|---|---|
| p25 | **−392.6 °/s** | 2 × 194.5 = 389 ✅ |
| p95 | **+661.1 °/s** | 2 × 321.2 = 642 ✅ |
| samples > 400 °/s | **613 of 1589** | physically impossible — real max is 343.5 |
| samples in slow tier | **19** | vs 809 in the pre-fix run |
| angle behaviour | 141.29 → 185.85 in 65 ms (677 °/s); later 103.66 → 90.63 → 77.60 | running *backwards* |

## 3.2 BUG-2 — the sign multiply compounds (SEVERITY: HIGH)

**Location:** lines **954–956**

```python
omega_fit *= sign        # in-place; when the lstsq branch is skipped the previous
omega_inst *= sign       # already-flipped value gets multiplied by sign AGAIN
```

Result on a CCW run: ω alternates ± every frame. Evidence: 11 sign flips, 46.6 % positive.

## 3.3 BUG-3 — FIX 1 itself was wrong (SEVERITY: HIGH, design error)

The comment says *"the correlation peak sign is arbitrary"*. It is **not** arbitrary — it is
the direction of motion. Locking one sign for an entire run assumes the log never reverses.

The video found **two sign flips at t=39.17 s and 39.37 s** (dip to ~0, then negative for ~1 s).
That is either a round restart with reversed rotation, or a measurement artifact. **Unresolved.**
Until it is resolved, a per-run sign lock is unjustified.

Pre-fix evidence that the raw sign was already usable:

| run | samples | % positive | sign flips |
|---|---|---|---|
| 11:09:20 | 1433 | 78.0 | 3 |
| 11:10:12 | 1730 | 12.5 | 5 |
| **11:27:11 (fixed)** | 1589 | **46.6** | **11** |

The "fix" made the sign *less* consistent than doing nothing.

## 3.4 BUG-4 — health test measures the wrong thing (SEVERITY: HIGH)

**Location:** lines **979–994** (FIX 2), **1007–1035** (FIX 3)

```python
979:  sky_now = sky_annulus_frac(frame, cxl, cyl, r)
980:  tracking_ok = (len(obs) >= 8 and sky_now >= 0.35)
```

`sky_annulus_frac` samples rings at **1.08 / 1.18 / 1.28 / 1.38 R**. That is exactly where
the knives and their handles live (8–14 of them, ~8° each plus handles), and behind the log
is **pine forest and mountains, not sky**. It was written as a **startup guard**
("is this blob floating on sky, or is it the editor window?") and is now reused as a
**continuous health check**. Different question, wrong instrument.

**Evidence:** the fixed run reports **65.6 % lost** while simultaneously seeing:

| n_obstacles | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
|---|---|---|---|---|---|---|---|---|---|
| frames | 177 | 200 | 188 | **345** | 198 | 149 | 221 | 54 | 56 |

You cannot have 11 knives on a log you claim to be blind to.

## 3.5 BUG-5 — `measure_latency.py` is dead on arrival (SEVERITY: FATAL for that file)

- Imports **7 names that do not exist** in `live_track.py`: `make_polar_maps`
  (real name: `build_geometry`), `detect_rotation_and_obstacles`, `periodic_relocate_check`,
  `draw_status`, `draw_click_through_overlay`, `get_window_handle_excluding_capture`,
  `DEFAULT_RADIUS`.
- Calls `roi_for(cx, cy, r)` — real signature is `roi_for(cx, cy, r, sw, sh, ...)`.
- Uses `pydirectinput.keyDown('f2')` as a **state reader**. It is a **sender**. That loop
  would fire F2 thousands of times per second, and `check_quit_keys` would spam **F11 —
  the browser fullscreen toggle**.
- Correct reader is `ctypes.windll.user32.GetAsyncKeyState(vk)`, already implemented
  correctly in `live_track.py` as `_vk_pressed()` (lines 404–417).

**Action: delete or quarantine this file.** Do not patch it. Phase 6 replaces it.

## 3.6 BUG-6 — dead constant

`live_track.py:100` `RING_FRAMES = 40` is unused. The real ring is `--ring` (default 20,
line 724). Harmless, but do not "fix" it into use without checking RAM.

## 3.7 Data quality of the recording folder

| file | rows | lost % | ≥8 obstacles % | median abs ω | verdict |
|---|---|---|---|---|---|
| 11:06:52 | 187 | 0 | 0 | 0 | junk (blindness logged as zeros) |
| 11:02:04 | 1140 | 0 | 0 | 0 | junk |
| 11:02:33 | 120 | 0 | 0 | 0.2 | junk |
| 11:07:58 | 2100 | 0 | 0 | 0 | junk |
| **11:09:20** | 1433 | 0 | 56.2 | **194.2** | ✅ **clean, usable** |
| **11:10:12** | 1730 | 0 | 62.2 | **194.8** | ✅ **clean, inverted sign** |
| 11:11:11 | 4020 | 0 | 19.5 | 160.4 | degraded |
| 11:12:58 | 532 | 0 | 50.2 | 187.0 | partially usable |
| 11:27:11 | 1589* | **65.6** | 34.4 | **394.1 (2× wrong)** | ❌ invalid |

Move the four junk files to `recordings/invalid/` so nobody analyses them as a set.

---

# 4. DO NOT TOUCH — already working, verified

Changing these without a failing test is how this project loses a week.

| Component | Location | Why |
|---|---|---|
| `auto_locate` | `live_track.py:168–244` | Finds the log on a real screen. Blob fallback. |
| `refine_circle` | `live_track.py:247–301` | 720-ray median + lstsq circle fit. Fixed a 15 % radius error. |
| `sky_annulus_frac` | `live_track.py:304–324` | **Correct as a startup guard.** Wrong only as a live health check. Keep the function. |
| `hough_candidates` / `find_target` | `:333–396` | Rejects editor windows and UI panels. Proven. |
| `build_geometry` / `polar` | `:107–129` | Remap grids. Rebuild only when calibration changes. |
| `polar_to_game` | `:132–134` | `(a + 90) % 360`. Verified. |
| `runs_of` / `gaps_of` | `:137–162` | Ring-wrap-correct. Produces the gap list. |
| `_vk_pressed` | `:404–417` | Correct `GetAsyncKeyState` edge detection. |
| `Hud` class | `:423–577` | Overlay verified to 1 px, invisible to capture, click-through. **Only change allowed: circle radius (§Phase 3).** |
| `Preview` class | `:583–649` | Works around missing HighGUI. |
| `roi_for` / `place_preview` | `:652–696` | Geometry is correct and validated by screenshots. |
| CSV writer / ring dump / hotkeys | `:864–870, 1210–1233` | Working. |
| `find_speed.py` | whole file | Self-tests pass. Cross-check agrees to 0.005°. Independent tool. |
| `measure_knife_geometry.py` | whole file | Produced the 8.03° measurement. Independent tool. |
| `shot.py` | whole file | Alignment verification utility. |

**Never rewrite `live_track.py`.** Edit surgical blocks only. It is 1277 lines of working
code with four regression bugs in two small regions (§3.1–3.4).

---

# 5. HALLUCINATION TRAPS — things a fresh model will believe that are false

| # | Trap | Truth |
|---|---|---|
| T1 | "The plan says 14 / 16–17 / 21–23 knives to 2.00x." | **MEASURED 2026-11-17: 17 throws.** Ladder is `1.01 1.03 1.06 1.10 1.15 / 1.19 1.24 1.30 1.35 1.42 / 1.48 1.56 1.65 1.75 1.85 / 1.98 2.12 2.28 2.47 2.70`. Throw 16 = 1.98 (short), throw 17 = 2.12. Full table + probabilities: `measurements/ladder.md`. |
| T2 | "Impact is exactly 180°, it says so in the code." | The *game rule* is 180°. The *pixel measurement* contradicts itself: 175.7° vs 181.3°. Unresolved. |
| T3 | "Rotation is one-directional, so lock the sign once." | **MEASURED, and it is false.** A 60 s run on 2026-11-17 produced **9 clean sign runs, 4 CW and 5 CCW**, lasting 0.3–9.1 s each. The log reverses direction several times per minute. Locking a sign inverts every downstream prediction after each flip. **Never lock.** Also: whole-run monotonicity is an invalid acceptance test for this reason. |
| T4 | "`DEFAULT_FLIGHT_T = 0.150` is the flight time." | It is a **guess** used only to draw a ghost marker. Never measured. Flight time cannot be measured from 30 fps (proven three ways — see `KNIFE_TIMING_AND_GEOMETRY.md` §1). |
| T5 | "The three fixes are working." | They are the regression. §3.1–3.4. |
| T6 | "Apples don't matter." | Unproven. They are 20–25° wide and counted as obstacles — which is **conservative**, so leave it. |
| T7 | "Use the L1–L60 grid for aiming." | It is **screen-fixed**; it does not rotate with the log. It is a human label layer only. The bot uses the 1440-bin log-relative grid. |
| T8 | "`measure_latency.py` exists, so latency measurement is half done." | The file cannot import. §3.5. |
| T9 | "Re-locate every 0.5 s keeps tracking healthy." | It fires on a broken signal and can churn the CPU doing full-screen Hough. §3.4. |
| T10 | "We can measure flight time from the video." | Proven impossible three different ways. Do not retry. |
| T11 | "Use `cv2.imshow`." | Not available in this OpenCV build. |
| T12 | "Put the preview anywhere." | If it overlaps the ROI, MSS captures the preview inside the capture → feedback loop. |
| T13 | "The multiplier ladder is linear / unknown." | It is **measured and non-linear**. Exact 20-value table in `measurements/ladder.md`. Steps run 0.02 → 0.23 and are **not monotone** (0.05 → 0.04 at index 6), so it is a hand-authored table, not a formula. |
| T14 | "10 knives per level." | Still **unresolved**. The video's 10 values actually spanned 12 ladder positions (indexes 3 and 5 were dropped), so "10 values" never proved 10 knives. The knife-slot count in the UI is unverified. |
| T15 | "Just `pip install` what you need." | Installs land on **C:**. Forbidden. Vendor to D: or venv on D:. |
| T16 | "`pydirectinput` is required because it's a game." | It is a **browser canvas**, receiving normal Win32 messages. Test the simplest option first. |
| T17 | "`--no-preview` turns the preview off." | **It does not exist.** Preview is opt-in via `--preview` and is already off by default. argparse exits with code 2 on `--no-preview`. |
| T18 | "The command lines in this plan are runnable as written." | They were not. 7 lines carried the non-existent `--no-preview` flag and were corrected on 2026-11-17. Run `python live_track.py -h` before copying any command. |
| T19 | "`omega_fit` hit 500–600 °/s, so the estimator is still broken." | The first ~1 s after acquisition is a transient while the lstsq window fills. It produced fit values up to **602** against a physical cap of 343.5. `WARMUP_S = 1.0` now suppresses it, and every sample above 400 in the 2026-11-17 run was inside that window. Check the `t` column before blaming the estimator. |
| T20 | "The target's big number is the current multiplier." | It is the **NEXT** multiplier. Proven arithmetically: bet 105, cashout 108.15 → current 1.03, while the target label read 1.06. The **gold knife** in the paged ladder is the current one. |

---

# 6. PHASES — step by step

Each phase: **goal → steps → acceptance → rollback**. Do not skip acceptance.

---

## PHASE 0 — Fill the three holes in ground truth (MANUAL, no code)

These block every downstream estimate. Total cost: ~15 minutes.

### 0.1 Read the full multiplier ladder — ✅ DONE 2026-11-17
Result recorded in `measurements/ladder.md`. Complete 20-value table read from 4 live
screenshots; independently confirmed against the 2026-11-16 video (10 shared points agree
exactly, proving the ladder is deterministic across runs).

```
1.01  1.03  1.06  1.10  1.15
1.19  1.24  1.30  1.35  1.42
1.48  1.56  1.65  1.75  1.85
1.98  2.12  2.28  2.47  2.70
```

**Answer: 17 throws to reach ≥ 2.00x** (throw 16 = 1.98, throw 17 = 2.12).
**Still open:** whether a page 5 exists beyond 2.70, and whether the ladder resets at a
level transition. The reset question decides the throw count and is asked in 0.3.

### 0.2 Confirm demo mode
1. Record the account balance / stake UI state.
2. Confirm no real payment method is attached.

**Acceptance:** written confirmation in `measurements/ladder.md`. If any real money is in the
loop, **stop the project** — an auto-clicker on a real-money wagering product is out of scope.

### 0.3 Count knife slots per level
1. Zoom the top stack row on a screenshot; count icons precisely.
2. Cross-check against the ladder length from 0.1.

**Acceptance:** a number, not an estimate.

---

## PHASE 1 — Restore correct rotation measurement — ✅ PASSED 2026-11-17

Nothing else matters until ω is right. This is a 3-edit change.

### 1.1 Remove the duplicate angle advance
- File: `live_track.py`
- Delete **line 958**: `angle = (angle + dtheta) % 360.0  # re-apply with correct sign`
- Keep line 924 as the only place `angle` advances.

### 1.2 Remove the in-place sign multiplication
- File: `live_track.py`, lines **954–956**
- Delete `omega_fit *= sign` and `omega_inst *= sign`.
- If a display magnitude is wanted, compute `omega_abs = abs(omega_fit)` **for display only**
  and never write it back to `omega_fit`.

### 1.3 Replace the sign lock with continuous measurement
- Delete the whole `sign_decided` / `sign_buffer` / `sign` mechanism (lines **944–958** and
  the initialisation at **850–853**).
- Also remove `sign_decided = False` / `sign_buffer = []` from the relocate block (1032–1033).
- Keep the **raw measured sign** and log it. Do not force it.

**Reason:** §3.3. The sign is a measurement, not a constant. If the log reverses at a round
restart, a locked sign silently inverts every prediction for the rest of the run.

### 1.4 Add a stability gate (new, 3 lines)
- If `abs(omega_fit) < 60.0` **or** `abs(omega_fit) > 400.0`, set a flag `omega_stable = False`.
- Downstream prediction must refuse to fire when `omega_stable` is False.
- Rationale: 205–260 °/s is the documented unstable ramp band; anything above 400 is
  physically impossible and means the measurement is corrupt.

### 1.5 Acceptance test — MANDATORY — ✅ PASSED 2026-11-17
Result: `recordings/live_20261117_155446.csv`, 60 s, 1987 rows, 714 tracked.
C1 p50 **195.9** (+0.7 % vs 194.5) · C2 **0 of 714** above 400 · C3 **78.9 %** slow ·
C4 **18.9 %** fast · C5 **98.7 %** local direction. **VERDICT: PASS.**

Two additions were required to reach this, both now in the code:
- `WARMUP_S = 1.0` — no measurement is published until 1 s of unbroken confident
  frames, because the first ~0.85 s after acquisition produced fit values up to 602 °/s.
- C5 was rewritten. Whole-run monotonicity is impossible: the log reverses direction
  (9 sign runs in 60 s, 4 CW / 5 CCW). C5 now measures local consistency.

Run one live session, target visible, 60 seconds:
```
python live_track.py --duration 60
python analyze_run.py
```
`analyze_run.py` implements every check below and exits non-zero on failure. It was
validated against two known recordings: `live_20261116_110920.csv` → PASS (p50 194.9,
0 of 809 above 400) and `live_20261116_112711.csv` → FAIL (p50 394.1, 613 of 1589 above
400), reproducing the previously established figures exactly.

| Check | Pass condition |
|---|---|
| p50 of `abs(omega_fit_dps)` where `n_obstacles ≥ 8` | **194.5 ± 2 %** OR **321.2 ± 3 %** |
| Count of samples with `abs(omega_fit) > 400` | **0** |
| Count in slow tier (150–240) | > 50 % of tracked samples |
| Count in fast tier (280–360) | 5–40 % of tracked samples |
| C5 `angle_polar_deg` local direction consistency | ≥ 95 % of frames agree with the local (rolling ±15 frame) median direction |

**Known confound, state it before judging a failure:** the Phase 2 health gate is still
the broken one, so 40–65 % of frames are marked lost and excluded. That does **not**
corrupt the ω math (lost rows are written as `n_obstacles=-1`, filtered out), but a
*bad* re-locate can move `cxl,cyl,r` to the wrong object and then ω is wrong for a
different reason. Before declaring the fix failed, check the stdout log for
`[relocate] recalibrated` lines whose centre differs from the startup centre.

**If any check fails: do not proceed. Report the numbers. Rollback:**

```
git checkout b6cf6dc -- live_track.py
```
This restores the last known-good measurement (194.2 °/s live, matching offline to 0.15 %).
It also removes the target-lost machinery — which is fine, Phase 2 rewrites that anyway.

---

## PHASE 2 — Replace the health test with one grounded in data

### 2.1 Instrument before deciding
Do not design a new threshold from intuition. Add these columns to the CSV
(`writer.writerow` header at lines 867–870, and the two row-append blocks at 1047–1059):

| new column | source |
|---|---|
| `sky_now` | `sky_annulus_frac(frame, cxl, cyl, r)` — computed every frame, logged, **not acted on** |
| `r` | current radius |
| `cx`,`cy` | current centre |
| `omega_stable` | from 1.4 |
| `lost_reason` | 0=none, 1=too few obstacles, 2=sky low, 3=both |

### 2.2 One diagnostic run
```
python live_track.py --duration 120
```
Play normally, including one level transition if possible.

### 2.3 Analyse, then decide
Compute the distribution of `sky_now` during **known-good** frames (≥8 obstacles, stable ω).
Then pick a health test whose false-positive rate on that distribution is < 1 %.

**Candidate design (do not adopt without the data):**
- Health = `(8 ≤ n_obstacles ≤ 18)` **AND** `r` within ±8 % of calibrated `r`
  **AND** `abs(omega_fit)` in a sane band
- Use `sky_annulus_frac` **only** at startup and on explicit re-locate, never per frame
- Require **2 consecutive** failing frames before declaring lost (not 1)
- Require **3 consecutive** failures before triggering full-screen `find_target`

### 2.4 Acceptance
| Check | Pass |
|---|---|
| `lost_pct` during active play | **< 10 %** |
| Frames with ≥8 obstacles marked lost | **0** |
| Full-screen `find_target` calls per 60 s | < 5 |
| Level transition recovered within | < 2 s |

---

## PHASE 3 — HUD hardening (cheap, independent, can be done in parallel)

### 3.1 Move the circle out of the measured band
- `live_track.py:529` — `c.create_oval(cx - r, cy - r, cx + r, cy + r, ...)`
- Change radius from `1.00R` to **`1.46R`**.
- Reason: `1.00R` sits inside the protrusion estimator's annulus (0.95–1.42R). If
  `WDA_EXCLUDEFROMCAPTURE` ever fails, a static screen-fixed circle correlates at zero lag
  and drags the bullseye-skin fallback ω toward zero. At 1.46R every pixel of ink is outside
  every measurement band, so **correctness no longer depends on WDA**.

### 3.2 Make `verify()` actually able to detect WDA failure
- `live_track.py:496–513` currently samples a 16×16 patch at the monitor's **top-left corner**,
  where nothing is ever drawn. It can therefore never detect contamination.
- Change it to sample a pixel **on a drawn feature** (e.g. the box's top edge) and compare it
  against the expected colour. Failure = WDA not working = warn loudly.

### 3.3 Measure the HUD's cost
```
python live_track.py --duration 30 --no-hud --bench 30
python live_track.py --duration 30 --bench 30
```
Report both fps values. If the HUD costs > 15 % fps, reduce `--hud-fps` to 15 or stop
redrawing static elements (box, spokes) every frame.

### 3.4 Acceptance
| Check | Pass |
|---|---|
| All drawn ink at radius ≥ 1.44R (box excepted, it is at the ROI edge) | visually confirmed with `--no-wda` + `shot.py` |
| `verify()` returns False when WDA is deliberately disabled | tested once |
| HUD cost | measured and recorded |

---

## PHASE 4 — Firing mathematics (observer only, NO CLICKING)

This is the part the current code does not have at all.

### 4.1 The quantity that matters
The blade flies straight up and sticks at the **bottom (180°)**. Therefore the only question is:

> **At the instant the blade arrives, is the 180° arc free?**

Not "where is the widest gap". Not "where will the widest gap be in 150 ms".

```
T_arrive(gap) = wrap180(impact_polar − gap_centre) / ω
```
where `impact_polar = polar_to_game⁻¹(IMPACT_GAME_DEG)`, `wrap180` maps to (−180, 180],
and `T_arrive` is reduced modulo `360/|ω|`.

Declare: `fire_now  ⇔  ∃ gap : |T_arrive(gap) − T_total| < margin(gap)`

```
margin(gap) = ((gap_width − 8.03°) / 2) / |ω|      # half the usable window
```

### 4.2 Add to the CSV (no behaviour change yet)
New columns: `t_arrive_best_s`, `margin_ms`, `gap_used_deg`, `would_fire` (0/1).
Compute every frame. **Do not actuate.**

### 4.3 Optional but recommended: display it
On the HUD, replace the "ghost" concept with:
```
TIME TO 180°:  0.184 s      margin 34 ms      T_total 0.150 s
```
and colour the box green when `fire_now` is true.

### 4.4 Acceptance
From a 60 s session with `T_total` still a placeholder:
| Check | Pass |
|---|---|
| `would_fire` events occur | > 0 and < 2 per second |
| Consecutive `would_fire` gaps | ≥ 800 ms (game's own re-throw cadence) |
| `margin_ms` | positive in > 90 % of `would_fire` frames |
| Sign/geometry sanity | predicted arrival angles, offset by `ω·T_total`, land inside the gap used |

**This phase is where a wrong convention shows up as nonsense numbers. Do not proceed until
`would_fire` timings look physically plausible when watched live.**

---

## PHASE 5 — Resolve the impact angle (one deliberate throw)

### 5.1 Capture
```
python live_track.py --duration 60
```
Throw manually, deliberately, five times with a wide gap. Log the frames.

### 5.2 Measure
For each landing: take the frames 200–600 ms after the throw, fit the stuck blade's angle at
r ≈ 1.0R, average across 5 throws.

### 5.3 Decide
- If the measurement lands on 180.0 ± 1.5° ⇒ set `IMPACT_GAME_DEG = 180.0` and close the
  contradiction as a pixel-measurement artifact.
- If it consistently lands at e.g. 176° ⇒ that is the real value; set it and document why.

### 5.4 Acceptance
`IMPACT_GAME_DEG` fixed with a measurement, not an argument. Std across 5 throws < 2°.

---

## PHASE 6 — Minimal actuator (new file, never inside `live_track.py`)

### 6.1 Create `actuator.py` — standalone
`live_track.py` stays a pure observer. The actuator is a separate process or a separate
module gated behind an explicit `--arm` flag.

### 6.2 Choose the input library by measurement, not by reputation
Test all three on the real game page, 100 clicks each, measure which ones the page acts on:

| candidate | note |
|---|---|
| `pyautogui` / raw `SendInput` | the game is a browser canvas → normal Win32 messages. **Try this first.** |
| `pydirectinput` | exists for DirectX games; may be unnecessary here |
| `win32api.mouse_event` | legacy, usually works for browsers |

The **only** acceptance criterion is: the game registers the click 100/100 times.

### 6.3 Timing — sleep-then-spin (this is the part people get wrong)
Windows' default timer is 15.625 ms and `Sleep` is unreliable below ~1–2 ms. Correct pattern:

```python
# target is an absolute perf_counter() timestamp
while True:
    remaining = target - time.perf_counter()
    if remaining <= 0.0015:
        break
    time.sleep(remaining - 0.0015)   # coarse
while time.perf_counter() < target:  # spin, ~50 µs resolution
    pass
send_click()
```

Optional: `ctypes.windll.winmm.timeBeginPeriod(1)` at start, `timeEndPeriod(1)` at exit.
It is per-process since Win10 2004 and gives roughly 1 ms granularity — the spin loop is what
actually delivers sub-millisecond accuracy.

### 6.4 Safety gates — all mandatory
1. `GetForegroundWindow() == game_hwnd` before every click, else skip
2. `omega_stable` true, else skip
3. Frame age < 25 ms, else skip
4. `margin_ms > 8` (half the worst-case jitter), else skip
5. Max 1 click per 800 ms
6. **F12 = hard kill** (`os._exit`), readable via `GetAsyncKeyState`
7. Requires an explicit `--arm` flag; default is dry-run that logs instead of clicking

### 6.5 Acceptance
| Check | Pass |
|---|---|
| Firing jitter over 100 scheduled clicks | **std < 2 ms** |
| Clicks fired while `--arm` absent | **0** |
| Clicks fired while not foreground | **0** |
| F12 kill latency | < 100 ms, verified by timestamp log |

---

## PHASE 7 — Closed-loop `T_total`

### 7.1 Why it is not "measured" but "converged"
`T_total` = input latency + browser event queue + game launch animation + flight + render.
It cannot be decomposed reliably. It does not need to be. One scalar absorbs all of it:

```
error_deg = observed_landing_angle − IMPACT_GAME_DEG
ΔT        = error_deg / ω
T_total  -= ΔT          # clamp to ±5 ms per throw, bounds [50, 400] ms
```

Converges in ~2 throws.

### 7.2 Landing detection
New dark cluster at r ≈ 1.0R, persisting ≥ 3 frames, not present before the throw.
Report the angular centroid.

### 7.3 Persistence
`measurements/calibration.json` gains `T_total`, plus the value's timestamp and throw count.

### 7.4 Acceptance
| Check | Pass |
|---|---|
| \|error_deg\| median after 5 throws | **< 3°** |
| \|error_deg\| std after 10 throws | **< 2°** |
| `T_total` stable across 3 sessions | within 5 ms |

---

## PHASE 8 — Miss detection and abort

1. Miss = no landing cluster within `T_total + 80 ms` **and** corridor motion confirmed the
   throw happened.
2. Counters: 1 miss = warn; **2 consecutive = pause, require manual resume**;
   3 total in a run = hard stop.
3. Session cap: 20 throws. Write `recordings/run_<stamp>.json` on every exit path.

**Acceptance:** zero false aborts across 200 clean throws; 100 % of deliberate misses caught.

---

## PHASE 9 — Game state machine (only after 1–8 pass)

The bot must eventually: press GO → throw ×N → handle level complete → next level → repeat.

Only build this after the throw loop is reliable, because the state machine is where silent
failures hide. Elements to identify by vision, not coordinates:

- green PLAY button (bottom right of the control bar)
- DIFFICULTY selector (EASY)
- multiplier ladder (paged)
- `x/3` level counter (top centre)
- knife stack (top row)

**Acceptance:** an unattended run completes 3 levels without a manual touch.

---

## PHASE 10 — Endurance and the real attempts

1. 10-minute unattended observer run: no crash, RAM growth < 20 MB, fps stable.
2. Closed-loop calibration run: 5 throws, converges.
3. **Full 2.00x attempt.** The knife count from Phase 0.1 defines the target.
4. Repeat until 5 consecutive clean runs, or until the per-throw reliability number proves
   the required `p` is not reachable.

**Honest framing:** if measured per-throw `p = 0.99` and the real knife count is 23, the clean
run rate is `0.99^23 = 79 %`. That is a losing bet strategy over repeated sessions. The number
from Phase 0.1 decides whether this project is aimed at a realistic target.

---

# 7. Regression checklist — run before AND after every change

Paste the results into the commit message. No exceptions.

```
python -m py_compile live_track.py
python live_track.py --bench 5
python live_track.py --duration 60
```

| # | Metric | Pre-fix baseline | Pass |
|---|---|---|---|
| 1 | `py_compile` | clean | clean |
| 2 | median fps | 34–56 | ≥ 25 |
| 3 | mean frame cost | ~4–9 ms | ≤ 12 ms |
| 4 | p50 abs ω (tracked) | 194.2 | 194.5 ± 2 % or 321.2 ± 3 % |
| 5 | samples > 400 °/s | 0 (pre-fix) | **0** |
| 6 | lost % | 0 pre-fix / 65.6 post-fix | **< 10** |
| 7 | frames with ≥8 obstacles marked lost | 0 | **0** |
| 8 | overlay alignment | 1 px | unchanged |
| 9 | RAM after 60 s | ~150–200 MB | < 250 MB |

---

# 8. Commands reference

```powershell
cd "D:\random works by gs\KN helper"

# observer, normal
python live_track.py

# observer, no preview window, 60 s, logs CSV
python live_track.py --duration 60

# timing benchmark only
python live_track.py --bench 5

# manual calibration (from a screenshot you measured yourself)
python live_track.py --cx 960 --cy 400 --r 126

# overlay alignment check (WARNING: contaminates the tracker, invalid CSVs)
python live_track.py --no-wda
python shot.py

# offline video speed
python find_speed.py --video gameplay1.mp4

# offline knife geometry
python measure_knife_geometry.py --stride 6

# compile check
python -m py_compile live_track.py
```

**Global hotkeys** (work without window focus, via `GetAsyncKeyState`):
`F10` stop · `F9` dump ring buffer · `F8` toggle L1–L60 spokes

---

# 9. File map

| File | Status | Purpose |
|---|---|---|
| `live_track.py` | 1277 lines. **Working core, 4 regression bugs.** | The observer. |
| `find_speed.py` | Working. Do not touch. | Offline speed measurement + reusable signal functions. |
| `measure_knife_geometry.py` | Working. Do not touch. | Offline knife width / gap scan. |
| `shot.py` | Working. Do not touch. | Overlay alignment verification. |
| `run.cmd` | Working. | Launcher pinning all temp/cache env vars to D:. |
| `measure_latency.py` | **DEAD. Delete or quarantine.** | Import-fails; key-polling would spam F11. |
| `fix_state.py`, `fix_loop.py`, `fix_log.py` | Leftover patch scripts, untracked. | Delete after confirming their changes are already in `live_track.py`. |
| `next plan.md` | **Superseded by this file.** Keep for history, do not follow. | Old PRD with 3 unsupported claims. |
| `measurements/*.md` | Evidence. | Do not edit; append new reports instead. |
| `recordings/*.csv` | 4 junk, 2 clean, 3 degraded. | Move junk to `recordings/invalid/`. |

---

# 10. Risk register

| Risk | Prob | Impact | Mitigation |
|---|---|---|---|
| The new model re-derives a "fix" that reintroduces the 2× bug | High | Fatal | §3.1 is explicit. Regression check #5 catches it in 60 s. |
| Knife count to 2.00x is ~23, not 14 | Medium | Changes strategy | Phase 0.1 answers it before any code. |
| The log genuinely reverses direction between rounds | Medium | Silent inversion | §1.3 removes the sign lock. |
| Browser blocks synthetic input entirely | Medium | Fatal | Phase 6.2 tests three libraries before any design work. |
| RAM exhaustion (8 GB, ~1.3 GB free) | Medium | Crash mid-run | Ring ≤ 20; no frame caches; monitor RAM in regression #9. |
| `WDA_EXCLUDEFROMCAPTURE` silently degrades on an OS update | Low | Self-measurement | Phase 3.1 moves all ink out of the measured bands. |
| User loses the bet while the bot is mid-development | Certain if attempted early | — | **Do not attempt a real 2.00x run before Phase 7 acceptance passes.** |

---

# 11. Definition of Done

The project is done when **all** of these are true and written down:

1. `measurements/ladder.md` exists with a complete ladder and the exact knife count to 2.00x.
2. Median `abs(omega_fit)` reproduces 194.5 and 321.2 °/s within 2–3 %, with zero samples
   above 400 °/s.
3. `lost_pct` < 10 % during normal play, with zero frames wrongfully marked lost.
4. `IMPACT_GAME_DEG` fixed by measurement, std < 2° across 5 throws.
5. Firing jitter std < 2 ms over 100 scheduled clicks.
6. `T_total` converges to |error| < 3° median within 5 throws, and persists across restarts.
7. Abort logic verified: 0 false aborts / 200 throws; 100 % of deliberate misses caught.
8. **5 consecutive clean runs to the target multiplier** with zero misses.
9. `recordings/run_*.json` exists for every attempt, including failures.
10. Nothing on C: was written or modified at any point.

---

# 12. Current one-line status

> Capture, geometry, occupancy, gaps, overlay and logging work and are verified.
> Rotation speed and angle are currently **2× wrong** because of one duplicated line
> (`live_track.py:958`). Health detection is wrong because it reuses a startup guard as a
> live test. No actuator exists. The knife count to 2.00x is unknown.
> **Start at Phase 0, then Phase 1. Nothing else.**
