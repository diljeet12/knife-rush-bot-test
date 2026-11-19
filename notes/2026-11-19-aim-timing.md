# Aim accuracy — what we know, what we don't (2026-11-19)

Status: **the bot works, it does not win.** Read the bottom line first.

## Bottom line

| | |
|---|---|
| Per-throw accuracy | **~87 %** (54/62 matched landings, 8-round run) |
| Accuracy needed to cash out at 2.12x | **95.7 %** (17 consecutive hits) |
| Chance of finishing a round at 87 % | ~9.5 % (`0.87^17`) |
| Observed over 30 rounds | 4 cashed / 26 lost = **13.3 %** |
| Observed over 8 rounds (alpha fix) | 1 cashed / 7 lost = **12.5 %** |

The gap is not small. 87 % is nowhere near 95.7 %, and no amount of
"throw only on good gaps" fixes it, because **gap width does not predict
hits** (16–20 deg slack: 89 %; 20–25 deg slack: 89.5 %). The error is
independent of the margin we are measuring, which means the error is not
in the picture — it is in the clock.

## What works

* **Space-bar actuation, GO detection, focus gate, auto-focus.** Reliable.
  The bot finds the game, brings it to the front, presses GO, throws, and
  recovers from stalls.
* **Multiplier reading from the log centre.** 0 wrong reads on 31 known
  frames. Log prints the *next* rung, so cash-out uses `held` not the
  printed value.
* **Cash-out at 2.12x** clicks the yellow CASHOUT panel, not GO.
* **Gap measurement.** Median per-frame slip vs tracked rotation is
  0.14 deg — the geometry in the picture is accurate to a fraction of a
  degree.
* **Bookkeeping.** 30 bets x $105 = $3,150 exactly. Per-round and
  per-throw CSVs are consistent.
* **Instrumentation.** `--trace` dumps one row per frame (angle, omega,
  slot, n_obs). `--sweep` randomises the lead per throw and writes the
  value used into the CSV.

## What does not work

* **~87 % per-throw accuracy.** This is the whole problem. Everything else
  is done.
* **The alpha (spin-ramp) fix did not help.** Evidence: in the 8-round run
  the measured `a=` values were +3, +4, -18, -11, -2, -2, +2, +13, -10,
  +10, +21 — all far below the 50 deg/s^2 gate, which therefore never
  fired. Either the ramp is not present at throw time, or the estimator is
  smoothing it away. Either way the change bought nothing measurable.
* **The `--sweep` design starves long leads.** A 300 ms lead at 193 deg/s
  needs a 58 deg lead, which most gaps cannot cover, so the bot stops
  throwing: 2 rounds in 222 s, one stall of 37 s. Any future sweep must
  either cap the lead near the current value or force the "now" path.

## Theories tested and killed

### 1. "The log ramps between 195 and 330 deg/s" — real, but not the cause
Measured live: steady ~195, ramps to ~330 over ~0.5 s, holds, ramps back.
Bimodal omega histogram confirms. But modelling it changed nothing
(see above), and the residual after the fix was unchanged.

### 2. "The press→launch delay is the missing 300 ms" — correlation is real, cause is not
`press_to_launch_ms` measured across 62 throws:

| delay | hit rate |
|---|---|
| 267–370 ms | 26/33 = 78.8 % |
| 370–420 ms | 10/11 = 90.9 % |
| 420–470 ms | 9/9 = 100 % |
| 470–720 ms | 6/6 = 100 % |

hits mean 400 ms (sd 96), misses mean 323 ms (sd 37). That looks
decisive — until the frame trace:

```
press 1: press +0ms ... holder empty at +345ms, n_obs 8->9 at +345ms
press 2: press +0ms ... holder empty at +345ms, n_obs 9->10 at +379ms, omega -330
```

The log turns at a constant 193 deg/s straight through those 345 ms with
no pause and no change of rate, and press 2 **hit** while spinning at
330 deg/s. If the knife really landed 345 ms after the press, the lead
error at 330 deg/s would be 46 deg and that throw could not have hit.

Conclusion: 345 ms is the game's insert/reload **animation**, not the
flight. `press_to_launch_ms` measures when the holder graphic empties, not
when the knife arrives. The hit-rate correlation is a proxy for "the press
landed inside a transition", not for a timing error we can subtract.

### 3. "The holder was empty when we pressed" — false
Every throw in the 8-round run had holder slot 0.12–0.20 (full). Slot was
not the discriminator.

### 4. "Reload→press timing predicts the bad presses" — false
0–150 ms: 90.9 %, 150–300: 100 %, 300–450: 60 %, 450–900: 90.9 %. No
monotone trend, n too small to read anything.

### 5. "Measure the aim error from where the knife landed" — impossible in principle
The game inserts the knife **exactly on the impact line**. Its final
radial position therefore encodes nothing about where we aimed. Worse,
with the log turning at a steady rate, "wrong lead" and "wrong aim" are
the *same number of degrees*: `pred = centre + omega*t` has one free
parameter, `t`. No geometric measurement can separate them. The earlier
`aimerr=` column rewinded by the measured 345 ms and so reported
`omega*(0.205 - 0.345)` regardless of whether the aim was actually good —
it is not evidence and should be ignored.

This is the reason the only honest estimator left is **hit rate itself,
as a function of the lead**.

## The lead sweep (partial)

Randomised lead per throw, 27 throws with a known outcome:

| lead | hits | rate |
|---|---|---|
| 160 ms | 4/4 | 100 % |
| 205 ms | 4/4 | 100 % |
| 250 ms | 5/5 | 100 % |
| 300 ms | 12/14 | 85.7 % |

Overall 25/27 = 92.6 %, but the buckets are far too small to separate
160/205/250 (a 4/4 is consistent with anything from 40 % to 100 % at 95 %
confidence). The one usable signal is that **300 ms is not better** and
probably worse. The current 205 ms is not obviously wrong.

## Hard limits

* Frame rate ceiling ~30 fps. One frame at 330 deg/s is 10.5 deg, larger
  than the 8.03 deg knife. Any error of one frame in the timing is worth
  more than the knife width.
* `mss` has a ~16 ms fixed grab cost, so the decision→press latency has a
  floor.
* The log decelerates/accelerates in a way that is measurable but, at
  30 fps, not measurable *well*.

## Next step (if any)

1. Re-run the sweep with leads **0.19, 0.205, 0.22, 0.235** — narrow, so
   the starvation does not bias it — over 30+ rounds. Anything outside
   this band is already excluded.
2. If no lead beats the current one, accept that 87 % is the ceiling of
   30 fps desktop vision here and stop. The game is not beatable at 87 %.
   Reaching 95.7 % would need sub-frame timing or reading the game's
   internals, which is out of scope by decision.

## Refuted claims from earlier sessions (do not resurrect)

* "Slow spin is 0/9" — measured omega *after* impact, not during flight.
* "Aim error sigma = 14.7 deg" — measured the knife nearest the impact
  line, not the landed knife. Structurally invalid.
* "`aimerr=` in the landed rows" — see theory 5; it restates the timing
  error it was meant to measure.
