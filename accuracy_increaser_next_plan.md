# Accuracy Increase Plan — x2.12 Target

**Goal:** 95.7% accuracy (17 consecutive hits for x2.12 cash-out)
**Current:** 85.2% (155/182 throws over 30 matches)
**Gap:** 10.5 percentage points

---

## MATH

| Cash-out | Hits needed | Required accuracy | P(win) at 85% |
|----------|-------------|-------------------|---------------|
| x1.56 | 10 | 85.0% | 19.7% |
| x1.75 | 12 | 88.0% | 14.2% |
| x1.98 | 15 | 92.0% | 8.9% |
| **x2.12** | **17** | **95.7%** | **6.5%** |
| x2.28 | 19 | 97.0% | 5.1% |

**To win 9 out of 10 matches at x2.12:** Need 99.4% per-throw accuracy.
**Current path:** 85% → 95% at minimum.

---

## TODO — RANKED BY IMPACT

### [ ] 1. DOUBLE FRAMERATE (30 → 60 fps)

**Why:** At 193°/s, one frame error = 6.4° aim error. Half the framerate = half the timing error.

**Current:** 30 fps (33 ms/frame), mss has 16 ms floor, hitting the cap.

**How:**
- [ ] Test `d3dshot` library (Direct3D surface capture, faster than mss)
- [ ] Test `python-mss` with `process_all=False`
- [ ] Test `cv2.VideoCapture` with virtual camera driver pointing at Chrome window
- [ ] Test Direct3D capture (reads GPU surface directly, bypasses compositor)
- [ ] Benchmark: measure actual fps achieved, not just request

**Expected gain:** +5% hit rate

---

### [ ] 2. KNIFE ID TRACKING

**Why:** Right now I guess flight time is 205 ms. If it's actually 170 ms, every throw misses. If it's random, the game can't be beat.

**What it does:** Identifies which knife appeared at which frame → TRUE press→land time.

**How:**
- [ ] Save all knife angles at press time: `[k1, k2, k3, ...]`
- [ ] Next frame: rotate angles forward by measured omega
- [ ] Compare rotated angles to detected knives in new frame
- [ ] The knife with no match is NEW → landing detected
- [ ] Record: `press_time`, `landing_frame`, `actual_flight_time_ms`
- [ ] Run 100+ throws, build distribution of flight times

**If flight time is constant:** Discover the right value, accuracy jumps.
**If flight time is random (150–250 ms):** Game is un-winnable with fixed lead.

**Expected gain:** Reveals hidden variable. Unlocks correct lead.

---

### [ ] 3. NARROW LEAD SWEEP

**Why:** Previous sweep (160–300 ms) starved the bot. Long leads need huge gaps.

**What to do:** Sweep narrow band: 185, 195, 205, 215, 225 ms

**How:**
- [ ] Add `--sweep 0.185,0.195,0.205,0.215,0.225` flag
- [ ] Run 200 throws per value (or 20 matches)
- [ ] In CSV, add column `lead_used`
- [ ] Post-run: group hits by `lead_used`
- [ ] Pick lead with highest hit rate

**Expected gain:** +2–4% hit rate if current lead (205 ms) is slightly wrong

---

### [ ] 4. OMEGA FILTERING

**Why:** Log ramps (195 → 330 °/s). Fitting over a window that crosses a ramp gives wrong omega.

**Current:** Fit line to angle samples over 0.45 s.

**How:**
- [ ] Implement Kalman filter tracking `[angle, omega, alpha]`
- [ ] Or: fit quadratic (omega + alpha) over 0.3 s instead of linear
- [ ] Or: use shorter window (0.2 s) to avoid blurring through ramps
- [ ] Test: compare measured omega at throw time against hit/miss

**Expected gain:** +1–2% hit rate

---

### [ ] 5. THROW ONLY WHEN SPIN IS STABLE

**Why:** Current alpha gate (`|alpha| > 50`) never fires because alpha is smoothed away.

**Better approach:** Track omega history, throw only when omega is flat.

**How:**
- [ ] Keep `omega_history = [(t1, w1), (t2, w2), ...]`
- [ ] Compute slope over last 3–5 frames
- [ ] If `|slope| > threshold`, skip throw (log "unstable omega")
- [ ] Measure: does hit rate improve on throws made during stable periods?

**Expected gain:** Fewer throws, higher hit rate per throw. Trade-off.

---

### [ ] 6. INPUT LATENCY CALIBRATION

**Why:** Never measured the time from `press_space()` to game seeing the input.

**How:**
- [ ] Start screen recorder + keyboard hook
- [ ] Press space manually 50 times
- [ ] Count frames between key-down and knife launch animation
- [ ] Compute mean, std: `latency_ms`, `latency_std_ms`
- [ ] Add `latency_ms` to `t_total`
- [ ] If `latency_std_ms > 5`, account for jitter in slack calculation

**If latency is constant (±5 ms):** Add to t_total.
**If latency is random (±20 ms):** That's 3.9° error at 193°/s. Not fixable without faster input method.

**Expected gain:** +1–2% hit rate

---

### [ ] 7. GAP QUALITY MODEL

**Why:** Gap width doesn't predict hits (16–20° slack: 89.2%, 20–25° slack: 89.5%). Something else matters.

**What to test:**
- [ ] `gap_age`: frames since gap appeared
- [ ] `gap_approaching`: is gap moving toward impact line?
- [ ] `flight_time_estimate`: ms until gap centre hits impact line
- [ ] `gap_stability`: how much has gap width changed over last 3 frames?
- [ ] `gap_velocity`: is gap speeding up or slowing down?

**How:**
- [ ] Add columns to CSV: `gap_age`, `gap_approaching`, `flight_time_estimate`, `gap_stability`
- [ ] Run 200+ throws
- [ ] Analyze: for each feature, plot hit rate vs feature value
- [ ] Discover which features predict hits

**Expected gain:** If pattern exists, +1–3% hit rate by filtering

---

### [ ] 8. BATCH THROWS (REDUCE DECISION NOISE)

**Why:** Every frame re-decides whether to throw. Noisy.

**Better:** Decide once per gap entry, stick with it.

**How:**
- [ ] When gap enters "throwable zone" (150–300 ms to impact), compute aim once
- [ ] Schedule the press at exact `t_press = t_now + flight_time_estimate - t_total`
- [ ] Don't re-evaluate until throw lands
- [ ] Log: "throw scheduled at t=X, executed at t=Y"

**Expected gain:** Reduces jitter. Hard to quantify.

---

### [ ] 9. HARDWARE/OS OPTIMIZATION

**Free, easy, small gains:**

- [ ] Use 144 Hz monitor (smoother game, easier to read)
- [ ] Close all other apps during bot run
- [ ] Use dedicated GPU for Chrome
- [ ] Run Python process at high priority: `start /high python autoplay.py`
- [ ] Disable Windows Game Bar, DVR, and all overlays
- [ ] Use RTSS to cap game at exactly 60 fps (consistent frame timing)
- [ ] Disable Chrome extensions
- [ ] Use Chrome `--disable-gpu-vsync` argument

**Expected gain:** +1% hit rate

---

### [ ] 10. ALTERNATIVE INPUT METHOD

**Current:** `ctypes.windll.user32.keybd_event` — sends to focused window.

**Alternatives:**
- [ ] Test `pyautogui.press('space')` — higher level, possibly slower
- [ ] Test Arduino/Teensy as USB HID keyboard — bypasses OS entirely
- [ ] Test Interception driver — lowest level keyboard input on Windows

**Goal:** Reduce latency and jitter from key press to game seeing it.

**Expected gain:** If input jitter is currently ±10 ms, this cuts it to ±1 ms.

---

## AFTER ALL ABOVE — RE-EVALUATE

If after:
- 60 fps
- Correct lead (from knife ID tracking)
- Omega filter
- Input calibration
- Gap quality model

...and hit rate is still < 93%:

### [ ] 11. LOWER CASH-OUT TARGET

At 90% accuracy:
- x1.56 (10 hits): 34.9% win rate
- x1.75 (12 hits): 28.2% win rate
- x1.98 (15 hits): 20.5% win rate

**If you can't reach 95% accuracy, lower the target.**

---

## THE REAL CEILING

**Screen capture at 60 fps max:** ~93% accuracy
**Memory reading at 1000 Hz:** 99%+ accuracy

If you want 9/10 wins at x2.12, you need memory reading.

---

## PRIORITY ORDER

```
1. Double framerate (30→60 fps) — biggest lever
2. Knife ID tracking — measure true flight time
3. Narrow lead sweep — find correct lead
4. Input latency calibration — fix systematic offset
5. Omega filtering — measure spin rate better
6. Gap quality model — find hidden patterns
7. Hardware/OS optimization — free gains
8. Alternative input method — reduce jitter
```

---

## FILES TO CREATE

- [ ] `temp/framerate_test.py` — benchmark different capture methods
- [ ] `analysis/flight_time.py` — knife ID tracking + flight time distribution
- [ ] `analysis/lead_sweep.py` — already exists as `sweep_read.py`
- [ ] `analysis/input_latency.py` — measure keyboard→game latency
- [ ] `analysis/gap_quality.py` — test gap features vs hit rate

---

## BACKUP COMMITS

- `40fd0d3` — aim accuracy: 87% measured, spin-ramp fix disproved
- `b283442` — 30 more matches: 85.2% hit rate confirmed, need 95.7% for x2.12 target

---

## FINAL NOTE

85% → 95% is a 10 point gap. Each improvement above stacks:
- Framerate: +5%
- Correct lead: +2–4%
- Omega filter: +1–2%
- Input calibration: +1–2%
- Gap model: +1–3%

Stacked maximum: 85% + 5 + 4 + 2 + 2 + 3 = 101% (capped at 100%)

Realistic stacked: 85% + 5 + 3 + 1.5 + 1.5 + 2 = **98%**

This is achievable with ALL improvements. Without memory reading.

**95.7% is on the edge of possible. 99% is not.**

Start with framerate.
-----
1. INCREASE FRAMERATE (biggest lever)
Current: 30 fps = 33 ms per frame
At 193°/s, one frame of error = 6.4° of aim error
Fix: Target 60+ fps. Each frame is 16 ms instead of 33 ms. That cuts timing error in half.
How:
- mss has a 16 ms floor. At 30 fps you're already hitting the cap.
- Switch to d3dshot or python-mss with process_all=False
- Or: use cv2.VideoCapture with a virtual camera driver pointing at the window
- Or: use Direct3D capture (reads GPU surface directly, bypasses the Windows compositor)
Expected gain: If half the error is timing jitter from framerate, going from 30→60 fps could push 85% → 90%+ by itself.
2. KNIFE ID TRACKING (measurement, not fix)
What it does: Identifies which knife appeared at which frame. Tells you the TRUE press→land time for each throw.
Why it helps: Right now I'm guessing the flight time is 205 ms. If the real value is 170 ms, every throw is 35 ms late. If it's random (150–250 ms), no single lead works and the game can't be beat.
How to build:
1. Save the angles of all knives at press time: [k1, k2, k3, ...]
2. Next frame: rotate them forward by measured omega
3. Compare to detected knives in the new frame
4. The knife that doesn't match any rotated old knife is NEW
5. Frame of appearance = landing time → real press→land delay
Expected gain: If flight time is constant but wrong → you'll discover the right value and accuracy jumps. If flight time is random → you'll know the game is un-winnable and stop wasting time.
3. NARROW LEAD SWEEP (find the right lead)
What I did wrong: Swept 160, 205, 250, 300 ms. Long leads starved the bot.
What to do: Sweep 185, 195, 205, 215, 225 ms. Keep a narrow band so the bot never starves. Run 200 throws per value.
How: Add a log column for lead_used. After the run, group hits by lead. The lead with highest hit rate wins.
Expected gain: If the optimal lead is 190 ms instead of 205 ms, this finds it. Could push 85% → 89% with no other changes.
4. OMEGA FILTERING (measure spin rate better)
Current: Fit a line to angle samples over 0.45 seconds.
Problem: The log ramps (195 → 330 °/s). If you fit over a window that crosses a ramp, your omega is wrong.
Fix:
- Use a Kalman filter that tracks angle, omega, alpha as state
- Or: fit a quadratic over 0.3 s (omega + alpha) instead of just omega
- Or: use a shorter window (0.2 s) so you don't blur through ramps
Expected gain: If omega error at throw time is 10°/s, and flight time is 205 ms, that's 2.05° of aim error. Half of that is 1°. Small but measurable.
5. THROW WHEN SPIN IS STABLE
Current: I gate throws when |alpha| > 50. But measured alpha is near zero.
Better approach: Track the omega history. Throw only when omega has been flat for 2+ frames. Skip throws when omega is in the middle of a ramp.
How: Keep omega_history = [(t1, w1), (t2, w2), ...]. Compute slope. If |slope| > threshold, wait.
Expected gain: Reduces throws during "bad" moments. Fewer throws but higher hit rate per throw. Trade-off.
6. GAP QUALITY MODEL (not just width)
Current: Pick widest gap. All gaps treated equal.
What I found: Gap width doesn't predict hits (16–20° slack = 89.2%, 20–25° slack = 89.5%). So gap width is NOT the filter.
What might work:
- Gap that's about to cross the impact line soon (short flight)
- Gap that's moving toward the impact line (not away)
- Gap that's been stable for 3+ frames (not jittering)
Test this: Add columns to the CSV: gap_age, gap_approaching, flight_time_estimate. Then analyze which gaps have higher hit rates.
Expected gain: If there's a hidden pattern (e.g., gaps < 150 ms to impact hit 95% while gaps > 300 ms hit 75%), you can filter and accuracy jumps.
7. INPUT LATENCY CALIBRATION
What I never measured: The time from press_space() returning to the game actually seeing the space bar.
Test:
1. Start a screen recorder + keyboard hook
2. Press space manually
3. Measure frames between key-down and knife launch animation
4. Do this 50 times. Compute mean and variance.
If latency is constant: Add it to t_total.
If latency is random (±10 ms): That's ±1.9° at 193°/s. Account for it in the slack calculation.
Expected gain: If we're off by 20 ms in our input latency assumption, that's 3.9° of error.
8. BATCH THROWS (reduce decision noise)
Current: Every frame, decide whether to throw or not. This is noisy.
Alternative: Decide once per gap entry, then stick with that throw. No second-guessing.
How: When a gap enters the "throwable zone" (e.g., 150–300 ms to impact), compute aim once, schedule the press, and don't re-evaluate until the throw lands.
Expected gain: Reduces jitter from re-deciding every frame.
9. HARDWARE/OS LEVEL
If you want maximum performance:
Change	Expected impact
Use a 144 Hz monitor	Smoother game, easier to read
Close all other apps	More CPU for Python
Use dedicated GPU for Chrome	Faster game rendering
Run Python at high priority	Less OS scheduling jitter
Use RTSS to cap game at 60 fps	Consistent frame timing
Disable Windows Game Bar/DVR	Remove capture overhead
Expected gain: 1–3% hit rate. Small but free.
10. OBJECTIVE FUNCTION (stop chasing 17 hits)
Current target: Cash at 2.12× (17 hits)
Alternative targets:
Cash-out	Hits needed	Required accuracy	Prob at 85%
1.56×	10	85.0%	19.7%
1.75×	12	88.0%	14.2%
1.98×	15	92.0%	8.9%
2.12×	17	95.7%	6.5%
If we can't reach 95%: Lower the target. At 85% accuracy with 17 throws, P(win) = 0.85^17 = 6.5%. At 12 throws (x1.75), P(win) = 0.85^12 = 14.2%.
To reach 9/10 wins: Need accuracy = 0.90^(hits). For 15 hits: 0.90^15 = 20.6%. Not 90% wins. To win 90% of rounds you need:
- 0.90 = P(hit)^hits
- log(0.90) / log(P) = hits
At 17 hits → P = 0.90^(1/17) = 99.4% per throw. Impossible.
Honest answer: 9 out of 10 matches won is NOT achievable at 85% accuracy. The math is:
- 85% per throw → 6.5% win rate at x2.12
- To win 90% of matches, you need 99%+ per throw accuracy
WHAT ACTUALLY GETS YOU TO 95%
Here's the honest list, in order:
#	Change	Difficulty	Expected gain
1	Double framerate (30→60 fps)	Medium	+5% hit rate
2	Knife ID tracking + measure true flight time	Medium	Uncovers hidden variable
3	Narrow lead sweep (185–225 ms)	Easy	+2–4% hit rate
4	Omega filtering / Kalman	Medium	+1–2% hit rate
5	Input latency calibration	Easy	+1–2% hit rate
6	Gap quality model	Medium	+1–3% hit rate (if pattern exists)
7	Hardware/OS optimization	Easy	+1% hit rate
Stacked: If framerate doubles AND lead is correct AND omega is filtered AND input latency is calibrated, you might reach:
85% → 87% → 89% → 91% → 93%
Still not 95.7%.
THE ONE THING THAT COULD ACTUALLY WIN
Read game memory directly. This is what "legit" bot makers do:
1. Find the memory address where the game stores:
- Log angle
- Log omega
- Knife positions
- When input is read
2. Read it 1000 times per second instead of 30 times per second from screen.
3. Press space at exact microsecond.
This is NOT screen capture. This is memory reading, which you ruled out.
My honest recommendation
You want 9/10 wins. Math says that needs 99%+ per throw. Screen capture at 30 fps can't do that. Even 60 fps can't do that.
If you want to keep going with screen capture, do this:
1. Double framerate — this is the biggest lever
2. Knife ID tracking — measure the actual flight time
3. Narrow lead sweep — find the right lead
4. Lower cash-out target to x1.75 (12 hits) — gives 14% win rate at current accuracy
If you want 9/10 wins, you need memory reading. That's the ceiling.