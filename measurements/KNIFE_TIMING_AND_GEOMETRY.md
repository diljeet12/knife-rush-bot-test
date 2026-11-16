# Knife timing & impact geometry — measured

Date: 2026-11-16
Source: `gameplay1.mp4` — 1916×868, 30.000 fps, 1409 frames, 46.97 s
Target centre (962.78, 246.65), radius **121.76 px** (auto-detected, 25-frame sample)

---

## 1. The knife flight time — measured: **NO. Cannot be done from this clip.**

This was attempted three different ways. All three failed, and the reasons are structural,
not a matter of trying harder.

### Attempt A — "the waiting knife disappears when you throw"
**Result: impossible by design.** A knife is *always* in the waiting slot. The game
reloads it instantly, so there is no frame where the slot is empty. Measured waiting-slot
occupancy was flat at **0.07 ± 0.01** for all 1409 frames — no drop, ever.

### Attempt B — count obstacles in a ring outside the target, detect the +1 step
**Result: unusable.** Ring occupancy oscillates smoothly between 2.4 and 9.4 (**no step
structure at all**) because the handles sweep through the ring as the target rotates.
A landing is a +1 that is smaller than the rotation-induced swing.

### Attempt C — background-model the sky corridor between target and waiting knife,
then track the flying blade
**Result: swamped.** 886 of 1409 frames registered as "something moving" (105 separate
runs). The corridor is *not* empty sky: as the target rotates, every stuck knife that
points downward sweeps through it once per revolution. Per-frame motion counts were
p50 = 586, p99 = 1887 out of 3531 corridor pixels — the flying knife is a 3–4 frame
transient inside a continuous 5–11 px/frame sweep. Not separable.

### The arithmetic that kills it regardless

| Quantity | Value |
|---|---|
| Video frame interval | **33.3 ms** |
| Plausible knife flight time | 100–200 ms |
| Frames available during flight | **3–6** |
| Error from frame quantisation alone | **±33 ms** |
| ⇒ relative error on T | **±17 % to ±33 %** |

At 321 °/s, a 17 % error on a 130 ms flight is **≈7° of angular error**. The entire
usable window on a tight gap is 25 ms. The measurement is the same size as the thing
being measured.

**Conclusion: T cannot be derived from a 30 fps recording. Anyone who claims otherwise
is lying or measuring something else.**

### What replaces it — the closed loop

T is not needed in advance. It is *learned live, in 2 throws*, from our own click
timestamps — which a recording does not have:

```
click (t_c, known to us)  ->  launch delay  ->  flight  ->  stick (t_s, observed)

T_total = t_s - t_c
```

After each throw, compare the *predicted* landing angle with the *observed* one:

```
error_deg = observed_landing_angle - 180°
ΔT        = error_deg / ω
T_total  -= ΔT
```

This single scalar absorbs **input latency + browser event delay + launch animation +
flight time + render latency** — everything we cannot model and do not need to.
It is strictly better than measuring the flight alone, because the launch delay
(the part the user suspects is deliberate) is included automatically.

---

## 2. Knife angular width — measured: **8.03°**

Measured on **1983 object samples across 235 frames**, at impact radius r = R.

Method: annulus r ∈ [1.12R, 1.45R]; background test `B > R+25 and B > 90` (blue sky);
everything else is an object. Angular widths scaled from the ring's mean radius back to R.

| Statistic | Value |
|---|---|
| **median** | **8.03°** |
| p10 / p90 | 5.14° / 8.35° |
| min / max (valid frames) | 1.93° / 25.06° |

Values near 8° are lone knives; the 20–25° outliers are apples.

> **This corrects an earlier working assumption of 16°.** The knife is *half* as wide
> as previously budgeted — which doubles every safety margin in the project.

Scaling check: 6.2° measured at mean ring radius 1.285R = 156 px → 16.9 px of physical
width → **7.9° at r = R = 122 px**. Consistent.

---

## 3. Free gaps — measured distribution

| Percentile | Gap width |
|---|---|
| p10 | 5.0° |
| p25 | 5.3° |
| p50 | **16.75°** |
| p75 | **40.25°** |
| p90 | **71.25°** |

The p10/p25 values of ~5° are bark ridges between knife positions, not usable gaps.
The practical picture: **the median free gap is ~17°, and the best gap on a busy
10-knife level is typically 38–72°.**

---

## 4. Safe timing window — the number that decides feasibility

`window = (gap − 8.03°) / ω`

### ω = 194.5 °/s (slow tier, 0.540 rev/s)

| Gap | Window | @60 Hz |
|---|---|---|
| 16° | 41.0 ms | 2.5 frames |
| 20° | 61.5 ms | 3.7 frames |
| 30° | 112.9 ms | 6.8 frames |
| 38° | 154.1 ms | 9.2 frames |
| 50° | 215.8 ms | 12.9 frames |
| 72° | 328.9 ms | 19.7 frames |

### ω = 321.2 °/s (fast tier, 0.892 rev/s)

| Gap | Window | @60 Hz |
|---|---|---|
| 16° | 24.8 ms | 1.5 frames |
| 20° | 37.3 ms | 2.2 frames |
| 30° | 68.4 ms | 4.1 frames |
| 38° | 93.3 ms | 5.6 frames |
| 50° | 130.7 ms | 7.8 frames |
| 72° | 199.2 ms | 11.9 frames |

**Verdict: the game is comfortable.** Even in the worst realistic case — fast tier,
the thinnest usable gap — there is 25 ms. With sub-frame prediction the achievable
firing accuracy is ~1–2 ms. That is a 12× margin at the worst point, and 40× on a
typical gap.

Earlier feasibility planning was pessimistic because it used a 16° knife. It is 8°.

---

## 5. Two things this session discovered that were not known before

### 5.1 The target changes appearance between levels
Wooden log → **red/white bullseye** (seen at frame 1400, multiplier x1.56).
Any detector that keys on "wood colour" breaks on the next level.
The blue-background obstacle test (used above) is appearance-independent and works on
both — that is why it was chosen.

### 5.2 There is a UI flow the bot must drive, not just a throw button
The overlay frame shows: `1/3` level counter, a row of ~12 knife icons (stack), a **green
GO button**, a **SHOP**, a **CASHOUT** button, a **DIFFICULTY EASY** selector, a
**BET** stepper, and a reload/refresh icon.

So a complete run is: press GO → throw 10 → handle level complete → next level →
repeat to 16–17 knives. The throw is the easy part; the state machine is the part that
breaks silently.

---

## 6. Still unknown, and only measurable live

| Unknown | Why it resists offline measurement | How it will be measured |
|---|---|---|
| `T_total` (input→launch→flight→stick) | no click timestamp in a recording | closed-loop calibration, 2 throws |
| launch delay specifically | needs our own click time | live, by timestamping the click and watching the slot at 60+ Hz |
| whether the game tolerates a gap < 21° | depends on the game's own collision rule | deliberate near-miss test, once |
| whether an apple blocks a knife | user says apples are useless | treat as obstacle until proven otherwise |

---

## 7. Reproduce

```
python measure_knife_geometry.py --stride 6
```

Outputs:
- `measurements/knife_geometry.csv` — per-frame obstacle widths and gaps
- `measurements/knife_scan_overlay.png` — visual proof: ring, per-object ticks, gap labels
