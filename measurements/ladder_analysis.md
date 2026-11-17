# Multiplier Ladder Analysis — All Known Data

**Last updated:** 2026-11-17
**Status:** ✅ **RESOLVED** — see `measurements/ladder.md` for the confirmed table.

---

## 0. RESOLUTION (2026-11-17, read from live UI)

Four screenshots (`per knife hit value/Screenshot 2026-11-17 1532*.png`) show the
complete paged ladder. Confirmed values:

```
1.01  1.03  1.06  1.10  1.15
1.19  1.24  1.30  1.35  1.42
1.48  1.56  1.65  1.75  1.85
1.98  2.12  2.28  2.47  2.70
```

| Claim below | Verdict |
|---|---|
| Ladder A (triangular, 2.05 at knife 14) | ❌ **FALSE.** Triangular assumption breaks at index 5/6. |
| Ladder B (irregular, ~21–23 knives) | ⚠️ **Shape right, count wrong.** The 10 video values are real ladder entries but 2 were dropped by sampling; the full table has 20 entries and 2.00x lands on **throw 17**. |
| Ladder C (x1.85 at 9 knives) | ✅ **Correct data point** — 1.85 is index 15. "9 knives" must mean 9 slots/knives remaining, not throws made. |
| Ladder D (x1.01 static) | ✅ Correct — 1.01 is index 1. |

**Authoritative answer: 17 throws to reach >= 2.00x (x2.12).**
Full detail, step table, video cross-check and probability budget:
`measurements/ladder.md`.

The sections below are kept as the historical reasoning trail.

---

## 1. Conflicting Ladders in the Repo

### Ladder A — Screenshot Series (from `image.png` overlay, paged UI)
> Source: `EXECUTION_PLAN.md` §5 trap T1, derived from the paged multiplier UI in the screenshots

| Knife # | Multiplier | Step |
|---------|------------|------|
| 0 (base) | 1.00 | — |
| 1 | 1.01 | +0.01 |
| 2 | 1.03 | +0.02 |
| 3 | 1.06 | +0.03 |
| 4 | 1.10 | +0.04 |
| 5 | 1.15 | (+0.05 projected) |
| 6 | 1.21 | (+0.06 projected) |
| 7 | 1.28 | (+0.07 projected) |
| 8 | 1.36 | (+0.08 projected) |
| 9 | 1.45 | (+0.09 projected) |
| 10 | 1.55 | (+0.10 projected) |
| 11 | 1.66 | (+0.11 projected) |
| 12 | 1.78 | (+0.12 projected) |
| 13 | 1.91 | (+0.13 projected) |
| **14** | **2.05** | **(+0.14 projected)** |

**Pattern:** step increases by 0.01 each knife (triangular numbers: 1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 66, 78, 91, 105 → divided by 1000)
**2.00x reached at:** knife **14**
**UI evidence:** multiplier ladder is **paged** (5 visible slots, `<` `>` arrows) — seen in `image.png`

---

### Ladder B — Video Series (from `gameplay1.mp4` frame-by-frame read)
> Source: `SPEED_MEASUREMENT_REPORT.md` line 169, `KNIFE_TIMING_AND_GEOMETRY.md` §5.1, `EXECUTION_PLAN.md` §5 trap T1

| Knife # | Multiplier | Step |
|---------|------------|------|
| 1 | 1.01 | — |
| 2 | 1.03 | +0.02 |
| 3 | 1.10 | +0.07 |
| 4 | 1.19 | +0.09 |
| 5 | 1.24 | +0.05 |
| 6 | 1.30 | +0.06 |
| 7 | 1.35 | +0.05 |
| 8 | 1.42 | +0.07 |
| 9 | 1.48 | +0.06 |
| 10 | 1.56 | +0.08 |
| 11 | ? | |
| 12 | ? | |
| 13 | ? | |
| 14 | ? | |
| ... | ... | |
| **?** | **≥2.00** | **projected ~21–23 knives** |

**Pattern:** **irregular**, no clear formula. Steps: 0.02, 0.07, 0.09, 0.05, 0.06, 0.05, 0.07, 0.06, 0.08
**2.00x reached at:** estimated **knife 21–23** (extrapolating ~0.06 avg step from 1.56)
**Video evidence:** 10 values captured over 46.97 s gameplay, ends at level 1 completion (10 knives)

---

### Ladder C — Live Harness Snapshot
> Source: `LIVE_HARNESS_REPORT.md` §9

> "One 1:1 crop, bullseye skin, multiplier **x1.85**, nine knives, two apples"

| Context | Value |
|---------|-------|
| Skin | red/white bullseye (not wooden log) |
| Knives stuck | 9 |
| Apples | 2 |
| Multiplier displayed | **x1.85** |
| Level | appears to be level 2 (skin changed at x1.56 in video) |

**Implication:** at knife 9 of level 2 (or cumulative knife ~19), multiplier = 1.85. This aligns better with Ladder B's projection (~21–23 knives to 2.00).

---

### Ladder D — Screenshot `details.md` Static Label
> Source: `GEOMATORY-and-screen-resulation/details.md` line 17

> "1. Wooden Target — **x1.01 in the middle**"

This is the **initial multiplier shown on the target at level start** (knife 0 / before first throw). Contradicts Ladder A's 1.00 base.

---

## 2. User's Current Report

> "start form 1.1 x when i didnt click any knife that mean 1st knife valsu is 1.1x"

If true: **base multiplier = 1.10**, first hit → 1.10 + step₁

This matches **Ladder A's knife 4 value** (1.10) as the starting point. Possible explanations:
- Game version difference
- Difficulty setting difference (EASY vs something else)
- Bet amount difference
- The user is reading a different UI element (e.g., the *next* multiplier, not current)

---

## 3. Known Structural Facts

| Fact | Evidence |
|------|----------|
| **Ladder is paged** — 5 visible slots, `<` `>` arrows | `image.png`, `EXECUTION_PLAN.md` T13 |
| **10 knives per level** (video) / **~12 slots in stack UI** (screenshots) | Video has 10 values; `LIVE_HARNESS_REPORT.md` T14 |
| **Skin changes at x1.56** (wooden → bullseye) | `KNIFE_TIMING_AND_GEOMETRY.md` §5.1, frame 1400 |
| **Level counter shows `x/3`** (3 levels per run?) | `KNIFE_TIMING_AND_GEOMETRY.md` §5.2 |
| **Ladder may or may not reset at level transition** | Unknown — Phase 0.1 Q2 |
| **Apples appear on rim, counted as obstacles** | `KNIFE_TIMING_AND_GEOMETRY.md` §2 (20–25° outliers) |

---

## 4. Projection Comparison

| Target | Ladder A (regular) | Ladder B (irregular, projected) | Ladder C (live 1.85 at knife 9 L2) |
|--------|-------------------|--------------------------------|-----------------------------------|
| Knife 10 | 1.55 | 1.56 (actual) | — |
| Knife 14 | **2.05** | ~1.80 | — |
| Knife 19 (9 L2) | ~2.80 | ~2.00 | **1.85** (actual) |
| Knife 21 | — | ~2.12 | — |
| Knife 23 | — | **~2.24** | — |

**Ladder A and Ladder C are mutually exclusive.** Ladder A predicts 2.80 at knife 19; live shows 1.85.
**Ladder B and Ladder C are consistent** — both point to ~21–23 knives for 2.00x.

---

## 5. What We Need to Resolve (Phase 0.1)

| Question | Method |
|----------|--------|
| What is the **exact base multiplier** at level start (knife 0)? | Read target centre text on fresh run |
| What is the **full paged sequence** from 1.00/1.01/1.10 to ≥2.00? | Click `>` arrow, screenshot each page |
| Does the **ladder reset** at level transition (after 10 knives)? | Complete level 1, read level 2 base |
| How many **knife slots** in the stack UI? | Count icons in top row |
| Is the **ladder identical every run**? | Repeat 2–3 times |

---

## 6. Template for Manual Verification

See `measurements/ladder.md` — fill in when you run the game.

---

## 7. Raw Data References

| File | Ladder Data |
|------|-------------|
| `measurements/SPEED_MEASUREMENT_REPORT.md` | Line 169: "rising multiplier ladder (x1.06 → x1.24)" |
| `measurements/KNIFE_TIMING_AND_GEOMETRY.md` | §5.1: skin change at x1.56; §5.2: ladder 1.01→1.56 (10 values) |
| `measurements/LIVE_HARNESS_REPORT.md` | §9: x1.85 at 9 knives, bullseye skin |
| `GEOMATORY-and-screen-resulation/details.md` | Line 17: "x1.01 in the middle" |
| `GEOMATORY-and-screen-resulation/image.png` | Visual: paged ladder UI with `<` `>` arrows |
| `recordings/live_*.csv` | No multiplier column — not captured |

---

## 8. Decision

**Do not trust any projection.** The only way to know the real knife count to 2.00x is **Phase 0.1 manual read**. The user's report of 1.10 base is a third data point that conflicts with both existing ladders.

**Next action:** You play one run, click `>` through the full ladder, tell me every value. I'll record it and Phase 1 begins.