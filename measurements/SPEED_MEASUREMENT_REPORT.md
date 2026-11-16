# Knife Rush — Target Rotation Speed Measurement

**Date:** 2026-11-16
**Video:** `gameplay1.mp4` — 1916 × 868, 30 fps, 1409 frames, 46.97 s
**Script:** `find_speed.py`
**Method:** classical CV — radial-signature circular cross-correlation (no AI, no training data)

---

## 1. The measurement

**Two speeds, not three.** An earlier run reported three tiers; the third cluster was the
ramp *between* the two real speeds, not a tier. The clustering was corrected to require a
genuine valley between histogram modes.

| | °/s | rev/s | RPM | s per revolution | °/frame @ 60 Hz | share of time |
|---|---|---|---|---|---|---|
| **Slow** | **194.5** | 0.540 | 32.4 | 1.85 s | **3.24°** | 79.7% |
| **Fast** | **321.2** | 0.892 | 53.5 | 1.12 s | **5.35°** | 20.3% |

Absolute range:

| statistic | °/s | rev/s | RPM |
|---|---|---|---|
| min | ≈ 0 (log genuinely stops near t = 10 s) | 0.000 | 0.0 |
| median | 195.1 | 0.542 | 32.5 |
| mean | 220.2 | 0.612 | 36.7 |
| max | 343.5 | 0.954 | 57.3 |
| p95 | 331.6 | 0.921 | 55.3 |
| std | 57.2 | 0.159 | 9.5 |

**Transitions** between the two speeds are smooth ramps of roughly 0.5–1 s, not instant
steps. There is a band between ~205 and ~260 °/s where the speed is *unknown* — a bot
should not throw blind inside it.

**Direction reversals:** two sign flips detected at t = 39.17 s and t = 39.37 s.

---

## 2. How much to trust it

### Good

- Two independent estimators (radial-signature correlation, and per-ring correlation)
  agree to a **median of 0.005°**, 95th percentile 0.020°.
- Only **6 frames out of 1370 (0.44%)** disagreed by more than 2°.
- Centre refined by maximising correlation rather than by shape: mean confidence
  **0.78 → 0.90**. The centre crosshair is visibly dead-centre on the log.
- 97.3% of frames passed the confidence gate.
- `find_speed.py` runs a self-test at startup that *proves* the sign convention and
  sub-pixel accuracy. There is no sign bug in the output.

### Not good — be aware

- **226 of 1408 frames (16%) needed repair.** The recording has heavy capture jitter: the
  encoder duplicates frames, then catches up with a double step. Fixed by integrating angle
  first and differentiating over a 0.5 s window (correct treatment for a noisy incremental
  signal), but it proves the 30 fps file is a poor sample.
  **Re-record at 60 fps constant frame rate (OBS, CFR) for tighter numbers.**
- **The two "reversals" at t = 39.17 s and 39.37 s are probably not reversals.** The log
  dips to zero, goes negative for ~1 s, then recovers — the shape of a **round restart**,
  not a direction change. Flagged as uncertain, not claimed.
- **9.6 ms/frame offline.** This includes the cross-check estimator; it is not the
  real-time path. The lean path has not been timed yet and no number should be quoted for
  it until it is.
- 30 fps recording of a 60 fps game. The speed values transfer (angles are scale-invariant)
  but the *timing resolution* does not.

### The genuinely good news

At 321 °/s and 60 Hz, a 30° gap gives a **~44 ms window — about 2.6 frames**. The game is
much slower than the worst case assumed in early planning. The timing problem is
comfortably solvable.

---

## 3. Method — why classical CV and not an AI model

The task is not "recognise the log". It is *"how many degrees did the log rotate between
frame t and frame t+1, to within ±0.3°"*. That is metrology, not perception.

The wood grain, bark cracks and rim shading form a natural **optical encoder**. Pipeline:

1. **Locate the log** — colour mask → dominant warm blob → vectorised radial scan → robust
   median radius (rejects protruding knives) → algebraic least-squares circle fit, iterated.
2. **Refine the centre** — grid search for the centre that maximises inter-frame correlation
   (coarse 2 px, fine 0.5 px). A centre error `e` injects a once-per-revolution wobble of
   roughly `e/r` radians; 12 px at r = 122 px was ~5.6° of corruption.
3. **Polar unwrap** an annulus, `r ∈ [0.55 R, 0.92 R]`. The inner cut deliberately excludes
   the multiplier text at the log's centre.
4. **Collapse to a 1-D signature** `s(θ)` — per-ring DC removal and equalisation, then mean
   across radius.
5. **Circular cross-correlation** between consecutive signatures, FFT-based, with parabolic
   sub-bin interpolation.
6. **Cross-check** every frame with a second estimator that correlates each radius ring
   separately instead of averaging first.
7. **Integrate → deglitch → differentiate over a window** to defeat capture jitter.
8. **Cluster** the speed histogram into tiers, requiring a real valley between modes.

Why not a neural network:

| | classical correlation | CNN / segmentation |
|---|---|---|
| accuracy | 0.05–0.3° | ~±1° (mask boundary noise: 1 px = 0.43° at r = 132) |
| cost / frame | ~1–2 ms (lean path, estimated) | 5–30 ms |
| training data | none needed | none available |
| failure mode | explicit confidence score | opaque |
| budget @ 60 Hz | 16.7 ms total | inference alone can exceed it |

A neural net is the right tool for a different job: producing a **one-time ground-truth
mask** of the log, offline. Not for the control loop.

---

## 4. Geometry conflicts found in the earlier hand-measured files

These were found while building the pipeline and should be fixed before any coordinate is
reused.

1. **Four different image sizes across the source material** — `download.jpg` 1917×1077,
   clean screenshot 1825×858, overlay 1367×742, video 1916×868, actual display 1920×1080.
   **None matches the screen.** Coordinates from `download.jpg` are *not* screen
   coordinates. Nothing absolute may be hardcoded; calibrate at runtime.

2. **Target centre recorded as both (949, 390) and (957, 392)** — 8 px apart, which is
   3.5° of angular error at r = 132.

3. **Knife tip recorded as both (954, 666) and (959, 657)** — 9 px apart.

4. **The sixteen "centre to corner" values are mislabelled.** Each is the distance from a
   *screen corner* to the object's centre — pure Pythagoras, zero new information.
   Verified 4/4 exactly for the log: √(949² + 390²) = 1026.0, etc. Labels read as
   object-corner distances and will mislead anyone reusing them. Drop them from the spec.

5. **The impact point is not 180°.** Measurements put the knife 10 px right of the target
   centre → impact ≈ **175.7°**, i.e. between L30 and L31. The overlay drawing puts it 3 px
   left → ≈ **181.3°**. A **13 px / 5.6° contradiction** between the table and the drawing.

6. **Rotation pivot ≠ visual centroid (hypothesis).** The log's visible disc sits ~10 px
   left of the screen's centre column while the knife sits exactly on it. The bevel is
   thicker on the right. Track the pivot from motion, not from the sprite's bounding box.

---

## 5. Files produced

```
find_speed.py                        the measurement script
measurements/speed_per_frame.csv     per-frame Δθ, ω, confidence, both estimators
measurements/speed_report.md         auto-generated summary
measurements/speed_summary.json      machine-readable results
measurements/omega_vs_time.png       ω(t) + histogram
measurements/detection_overlay.png   detected centre / radius drawn on a real frame
```

Usage:

```
python find_speed.py --video gameplay1.mp4
python find_speed.py --video gameplay1.mp4 --limit 200   # quick test
python find_speed.py --probe                             # metadata only
```

---

## 6. Open flag — unresolved

The detection overlay revealed a **cash-out wagering interface**: account balance, stake,
rising multiplier ladder (x1.06 → x1.24), cash-out button, live player count, player ID.

The stated context was a party bet between friends. A balance of $999,999.88 strongly
suggests a demo or sandbox account, but that has not been confirmed.

**Position taken:** the measurement and geometry analysis are complete and legitimate. An
auto-clicker pointed at a real-money wagering platform would not be built. The question
"is any real money in the loop?" was asked and is **still unanswered**.

---

*Measurement is of a 30 fps screen recording, not of the live game. Re-measure from a
60 fps CFR recording before trusting the timing model.*
