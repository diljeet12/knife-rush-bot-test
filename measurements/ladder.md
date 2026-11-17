# Knife Rush — Multiplier Ladder (CONFIRMED)

**Game:** Knife Rush (demo / play-money)
**Captured:** 2026-11-17, 15:32:43 – 15:33:07 local
**Source:** 4 in-game screenshots of the paged ladder UI, read directly
**Confidence:** HIGH — every value read from the UI, and independently cross-checked
against the 2026-11-16 30 fps video capture

---

## 1. Raw evidence

The ladder UI is paged, **5 slots per page**, with `<` and `>` arrows.

| Page | Screenshot | Values (left → right) |
|------|------------|------------------------|
| 1 | `per knife hit value/Screenshot 2026-11-17 153243.png` | 1.01, 1.03, 1.06, 1.10, 1.15 |
| 2 | `per knife hit value/Screenshot 2026-11-17 153251.png` | 1.19, 1.24, 1.30, 1.35, 1.42 |
| 3 | `per knife hit value/Screenshot 2026-11-17 153258.png` | 1.48, 1.56, 1.65, 1.75, 1.85 |
| 4 | `per knife hit value/Screenshot 2026-11-17 153307.png` | 1.98, 2.12, 2.28, 2.47, 2.70 |

On page 1 the third slot (**x1.06**) is rendered in gold; every other slot on every
page is white. Interpretation unconfirmed — either a "current / next" marker or the
equipped knife skin. It does not affect the values.

---

## 2. The ladder

| # | Multiplier | Δ step | Δ % |
|---|-----------|--------|-----|
| 1 | 1.01 | — | — |
| 2 | 1.03 | +0.02 | +1.98 % |
| 3 | 1.06 | +0.03 | +2.91 % |
| 4 | 1.10 | +0.04 | +3.77 % |
| 5 | 1.15 | +0.05 | +4.55 % |
| 6 | 1.19 | +0.04 | +3.48 % |
| 7 | 1.24 | +0.05 | +4.20 % |
| 8 | 1.30 | +0.06 | +4.84 % |
| 9 | 1.35 | +0.05 | +3.85 % |
| 10 | 1.42 | +0.07 | +5.19 % |
| 11 | 1.48 | +0.06 | +4.23 % |
| 12 | 1.56 | +0.08 | +5.41 % |
| 13 | 1.65 | +0.09 | +5.77 % |
| 14 | 1.75 | +0.10 | +6.06 % |
| 15 | 1.85 | +0.10 | +5.71 % |
| 16 | 1.98 | +0.13 | +7.03 % |
| **17** | **2.12** | **+0.14** | **+7.07 %** |
| 18 | 2.28 | +0.16 | +7.55 % |
| 19 | 2.47 | +0.19 | +8.33 % |
| 20 | 2.70 | +0.23 | +9.31 % |

The step sequence is **not monotone** (0.05 → 0.04 at index 6, 0.06 → 0.05 at
index 9), so it is **not** a generated formula. It is a hand-authored table,
and must be treated as literal data.

---

## 3. Headline number

**2.00x is reached on throw 17 — not 14.**

- Throw 16 → **x1.98** (short by 0.02)
- Throw 17 → **x2.12** ✅

The "14 knives" estimate came from assuming a clean triangular series
(+0.01, +0.02, +0.03, +0.04, …). That series breaks at index 5/6
(1.15 → 1.19 is +0.04, not +0.05), so the extrapolation was invalid.

The old PRD's "16–17 knives" was numerically close, but it was a guess with no
supporting evidence. It is now replaced by measured data.

---

## 4. Cross-check against the 30 fps video

`measurements/KNIFE_TIMING_AND_GEOMETRY.md` §5.1 reported this sequence:

> `1.01, 1.03, 1.10, 1.19, 1.24, 1.30, 1.35, 1.42, 1.48, 1.56`

Mapping those onto the confirmed ladder:

| Video value | Ladder index |
|---|---|
| 1.01 | 1 |
| 1.03 | 2 |
| 1.10 | 4 |
| 1.19 | 6 |
| 1.24 | 7 |
| 1.30 | 8 |
| 1.35 | 9 |
| 1.42 | 10 |
| 1.48 | 11 |
| 1.56 | 12 |

Indices **3 (1.06)** and **5 (1.15)** are missing from the video read.

Two hard conclusions:

1. The video's "irregular steps" (0.02, 0.07, 0.09, 0.05, …) were an artefact of
   **dropped samples**, not a differently-shaped ladder.
2. **The ladder is identical across runs.** The 2026-11-16 video and the
   2026-11-17 screenshots agree at all 10 shared points. It is deterministic
   game data, not randomised per run.

Corollary: the earlier inference "10 video values = 10 knives per level" is
**wrong**. The video captured 10 values spanning 12 ladder positions.

---

## 5. Probability budget for a 2.00x cash-out

Requires **17 consecutive hits, zero misses.**

| per-throw hit rate p | P(clean run) = p^17 |
|---|---|
| 0.980 | 70.9 % |
| 0.990 | 84.3 % |
| 0.995 | 91.9 % |
| 0.998 | 96.6 % |
| 0.999 | 98.3 % |

Inverted — the per-throw hit rate required to hit a target success rate:

| Target clean-run | Required per-throw p |
|---|---|
| 80 % | 0.9869 |
| 90 % | 0.9938 |
| 95 % | 0.9970 |

---

## 6. Still open

1. **Is there a page 5?** Page 4 ends at 2.70 with `>` still active. Unknown
   whether the table continues. Only matters if we chase past 2.00x.
2. **Does the ladder reset at a level transition?** If a run contains multiple
   levels and the ladder restarts at 1.01 each level, then 2.00x may be
   unreachable inside one level and the throw count changes entirely.
   **This is the single most important remaining question.**
3. **What is displayed at a fresh run, before any throw?** The user reported
   "1.1x", but the ladder's first value is 1.01 and 1.10 is index 4. Needs
   resolving — possibly the gold highlight marks a mid-run position.
4. Values beyond 2.70.

---

## 7. Related files

- Screenshots: `per knife hit value/Screenshot 2026-11-17 153243.png`,
  `153251.png`, `153258.png`, `153307.png`
- Prior consolidated analysis: `measurements/ladder_analysis.md`
- Video cross-check: `measurements/KNIFE_TIMING_AND_GEOMETRY.md` §5.1
