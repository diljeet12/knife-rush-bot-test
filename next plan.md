# Product Requirements Document
## Knife Rush 2.00x Automation Bot

**Version:** 1.0  
**Date:** 2026-11-16  
**Author:** GS  
**Status:** Active Development  
**Classification:** Internal — Party Bet Execution

---

## 1. Executive Summary

### 1.1 Purpose
Build a vision-based automation bot that plays the browser game **Knife Rush** (demo mode, `knife-rush.onout.games`) and reaches the **2.00x multiplier** (~16–17 consecutive perfect throws) without a single miss.

### 1.2 Success Metric
**Binary:** The bot completes a full run to 2.00x multiplier with **zero misses**.  
Loser pays for the week's party. There is no partial credit.

### 1.3 Probability Requirement
Per-throw success probability **p ≥ 0.995** required for 95%+ run completion rate.
- p = 0.990 → 84% clean run
- p = 0.995 → 92% clean run  
- p = 0.999 → 98% clean run

---

## 2. System Architecture

### 2.1 High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                      KNIFE RUSH BOT                             │
├──────────────────┬──────────────────┬──────────────────────────┤
│   OBSERVER       │   ACTUATOR       │   CALIBRATION            │
│  (live_track.py) │  (actuator.py)   │  (measure_latency.py,    │
│                  │                  │   closed-loop in main)   │
│  - MSS capture   │  - pydirectinput │  - T_total measurement   │
│  - 1440-bin grid │  - ±1ms timing   │  - Landing error detect  │
│  - ω estimation  │  - Safety guards │  - T_total auto-adjust   │
│  - Gap prediction│  - Kill switch   │  - Persist to disk       │
│  - CSV telemetry │  - Rate limit    │                          │
└──────────────────┴──────────────────┴──────────────────────────┘
```

### 2.2 Data Flow
```
Game Screen → MSS (ROI) → OpenCV Polar Remap → Dual Estimator
                                                      ↓
                        ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
                        |                             |
                        v                             v
              Angle History (0.35s)            Occupancy Grid (1440 bins)
                        |                             |
                        v                             v
              Least-Squares ω (deg/s)          Gap Detection (0.25°)
                        |                             |
                        └──────────────┬──────────────┘
                                       v
                            Ghost Gap Prediction
                            (t_fire = t_gap_center - T_total)
                                       |
                                       v
                              ACTUATOR FIRING DECISION
                                       |
                                       v
                            pydirectinput.click()
                                       |
                                       v
                            Landing Error Detection → T_total Update
```

---

## 3. Functional Requirements

### 3.1 Observer (FR-OBS)

| ID | Requirement | Specification |
|----|-------------|---------------|
| FR-OBS-01 | Screen capture | MSS, cropped ROI (1.60R × 4.65R), 60 fps max |
| FR-OBS-02 | Target auto-location | HoughCircles + radial refine + sky-annulus validation (≥35% sky) |
| FR-OBS-03 | Angle tracking | Dual estimator: texture annulus [0.55R, 0.92R] + protrusion [0.95R, 1.42R] |
| FR-OBS-04 | Angular resolution | 1440 bins (0.25°/bin) — NOT the 60-line L1–L60 grid |
| FR-OBS-05 | Rotation speed | Least-squares over 0.35s window, sign-normalised once per run |
| FR-OBS-06 | Gap detection | Runs of sky in occupancy grid; min run 3°, max object 60° |
| FR-OBS-07 | Ghost gap lead | `ghost = gap_center + ω × flight_t` |
| FR-OBS-08 | Telemetry logging | CSV: t, dt_ms, fps, angle, dθ, ω_inst, ω_fit, conf, n_obs, widest_gap, corridor |
| FR-OBS-09 | Overlay | Click-through Tk, WDA_EXCLUDEFROMCAPTURE, draws box/circle/ticks/gap labels |
| FR-OBS-10 | Target-lost detection | `n_obs < 8` OR sky annulus < 35% for > 0.3s → `target_lost = True` |
| FR-OBS-11 | Periodic re-locate | Every 0.5s verify sky annulus; if < 35%, re-run full-screen find_target |
| FR-OBS-12 | Sign normalisation | Collect 15 confident ω_fit samples (~0.5s), median → lock CW/CCW for run |

### 3.2 Actuator (FR-ACT)

| ID | Requirement | Specification |
|----|-------------|---------------|
| FR-ACT-01 | Input library | `pydirectinput` (raw input, lowest jitter on Windows) |
| FR-ACT-02 | Timing precision | Fire within ±1ms of target `t_fire` (measured via audio sync) |
| FR-ACT-03 | Foreground guard | `GetForegroundWindow() == game_hwnd` before every click |
| FR-ACT-04 | Canvas-relative coords | Click at canvas center + offset; auto-detect browser HWND |
| FR-ACT-05 | Confidence gate | Only fire if `conf_tex ≥ 0.30` AND `sharp_tex ≥ 0.04` AND `n_obs ≥ 8` |
| FR-ACT-06 | Frame freshness gate | Only fire if frame age < 20ms (timestamp at grab) |
| FR-ACT-07 | Kill switch | `F11` = immediate hard stop, sets `actuator_enabled = False` |
| FR-ACT-08 | Rate limit | Max 1 click per 800ms (game animation limit) |
| FR-ACT-09 | Click logging | Every click logged: `t_fire, t_target, ω, predicted_gap, confidence` |

### 3.3 Calibration & Closed-Loop (FR-CAL)

| ID | Requirement | Specification |
|----|-------------|---------------|
| FR-CAL-01 | Latency measurement | `measure_latency.py`: click → frame poll → knife appears in corridor → `T_total` |
| FR-CAL-02 | Sample size | ≥ 50 samples per session, median ± std, three sessions for stability |
| FR-CAL-03 | Component breakdown | OS input, browser, game loop, render, detection — each measured separately |
| FR-CAL-04 | Landing detection | New dark cluster at 1.0R ± 15°, persists ≥ 3 frames, not present pre-fire |
| FR-CAL-05 | Impact angle measurement | Cluster centroid → angle; target = 180° (game convention) |
| FR-CAL-06 | Error computation | `error_deg = actual_impact - predicted_impact` |
| FR-CAL-07 | T_total update rule | `T_total ← T_total - error_deg / ω` (clamped ±5ms/throw, bounds [50, 400]ms) |
| FR-CAL-08 | Convergence | Median |error| < 3° within 5 throws; std < 2° after 10 throws |
| FR-CAL-09 | Persistence | `T_total` saved to `measurements/calibration.json`; auto-loads on startup |

### 3.4 Safety & Abort (FR-SAF)

| ID | Requirement | Specification |
|----|-------------|---------------|
| FR-SAF-01 | Miss detection | No landing detected within `T_total + 50ms` after fire + corridor shows knife left |
| FR-SAF-02 | Consecutive miss counter | Reset on hit; increment on miss |
| FR-SAF-03 | Abort thresholds | 1 miss: warning log; 2 consecutive: pause + manual resume (`R`); 3 total: hard stop |
| FR-SAF-04 | Session limits | Max 20 throws/run; auto-save run summary JSON |
| FR-SAF-05 | Browser focus check | EnumWindows for "knife-rush" title; verify canvas visible |
| FR-SAF-06 | DPI/zoom handling | Detect CSS pixel ratio via JS injection or visual calibration; scale coords |

---

## 4. Non-Functional Requirements

### 4.1 Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| Capture-to-analysis latency | ≤ 20ms median | `live_track.py` internal timing |
| Loop rate (with overlay) | ≥ 30 fps sustained | FPS counter in CSV |
| RAM usage | ≤ 200 MB total | Ring buffer ≤ 20 frames (400×600×3×20 ≈ 14 MB) |
| CPU usage | ≤ 50% single core | i3-1115G4, 2C/4T @ 3.0 GHz |
| Actuator jitter | ≤ 1ms | High-speed camera or audio sync test |

### 4.2 Reliability

| Requirement | Target |
|-------------|--------|
| Observer uptime | 10 minutes continuous without crash |
| Auto-recovery from target loss | < 2 seconds (re-locate succeeds) |
| False positive click rate | 0 per hour (idle test) |
| Kill switch response | < 100ms from F11 to `enabled=False` |
| Data persistence | Zero CSV row loss on Ctrl-C or crash |

### 4.3 Usability

| Requirement | Specification |
|-------------|---------------|
| Startup | `python live_track.py` → auto-locate → overlay appears |
| Manual calibration | `--cx --cy --r` flags for instant restart |
| Headless benchmark | `--bench 5 --no-preview` → timing report |
| Hotkeys | F10=stop, F9=dump, F8=spokes, F11=kill switch, C=recalibrate, R=reset ω |
| Logs | Human-readable CSV + run summary JSON |

---

## 5. Hardware & Environment Constraints

| Constraint | Value | Impact |
|------------|-------|--------|
| CPU | i3-1115G4, 2C/4T, 3.0 GHz | No heavy ML; classical CV only |
| RAM | 8 GB (1.3 GB free typical) | Ring buffer ≤ 20 frames; no caching |
| GPU | Intel UHD (no CUDA) | OpenCV CPU only |
| Display | 1920×1080 @ 125% DPI (120 DPI) | All coords physical pixels; verified |
| OS | Windows 10/11 | `pydirectinput`, `ctypes` for HWND |
| Disk | Project on D: (131 GB free) | All outputs to D:\random works by gs\KN helper |
| Python | 3.13 @ C:\Users\gurwi\AppData\Local\Programs\Python\Python313 | Pre-existing; no C: writes |

---

## 6. Acceptance Criteria (Definition of Done)

### 6.1 Phase Gate: Latency Measurement (Phase 1)
- [ ] `measure_latency.py` produces `measurements/latency_samples.csv` with 50+ rows
- [ ] Median T_total stable across 3 sessions (±5ms)
- [ ] Component breakdown documented in `LATENCY_REPORT.md`
- [ ] Std deviation < 8ms

### 6.2 Phase Gate: Actuator (Phase 2)
- [ ] `actuator.py` fires within ±1ms of target (verified)
- [ ] Foreground guard blocks clicks when Alt-Tabbed
- [ ] Kill switch (F11) stops all clicks < 100ms
- [ ] 1-hour idle test: zero accidental clicks

### 6.3 Phase Gate: Closed-Loop (Phase 3)
- [ ] Landing detection ≥ 95% recall, < 2% false positive
- [ ] T_total converges within 5 throws (|error| < 3° median)
- [ ] T_total persists across restarts

### 6.4 Phase Gate: Safety (Phase 4)
- [ ] Miss detection catches 100% of actual misses
- [ ] Abort thresholds enforced (1 warn, 2 pause, 3 stop)
- [ ] Run summary JSON written on every exit

### 6.5 Phase Gate: Integration (Phase 5-6)
- [ ] 5 consecutive clean runs to 2.00x multiplier
- [ ] Zero misses, zero false aborts
- [ ] Total runtime per run < 60 seconds

---

## 7. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Browser blocks synthetic clicks | High | Fatal | Use `pydirectinput` (raw input); test in Phase 1 |
| Game canvas moves/resizes | High | Fatal | Canvas-relative coords + periodic HWND re-detect |
| T_total varies randomly > 20ms | Medium | Misses | Closed-loop adapts per throw; measure variance early |
| Overlay steals focus | Low | Clicks lost | WS_EX_NOACTIVATE verified; re-verify in safety phase |
| RAM exhaustion (8GB) | Medium | Crash | Ring buffer 20 frames; monitor in code |
| Game updates / skin changes | Low | Silent failure | Sky-annulus guard + periodic re-locate (already in) |
| Windows Defender / AV blocks input | Low | Fatal | Add exclusion for project folder; test early |

---

## 8. Deliverables

| Artifact | Location | Description |
|----------|----------|-------------|
| `live_track.py` | Root | Main observer (production) |
| `actuator.py` | Root | Clicker module (Phase 2) |
| `measure_latency.py` | Root | Latency calibration tool (Phase 1) |
| `find_speed.py` | Root | Offline video analysis |
| `measure_knife_geometry.py` | Root | Knife width/gap scanner |
| `shot.py` | Root | Screenshot utility |
| `run.cmd` | Root | Launcher with D:-only env vars |
| `measurements/LATENCY_REPORT.md` | measurements/ | Phase 1 results |
| `measurements/LIVE_HARNESS_REPORT.md` | measurements/ | Observer validation |
| `measurements/KNIFE_TIMING_AND_GEOMETRY.md` | measurements/ | Offline analysis |
| `measurements/calibration.json` | measurements/ | Persistent T_total, centre, radius |
| `recordings/live_*.csv` | recordings/ | Per-frame telemetry |
| `recordings/run_*.json` | recordings/ | Run summaries (Phase 4) |
| `PRD.md` | Root | This document |

---

## 9. Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| 1. Latency Measurement | 4.5h | 4.5h |
| 2. Actuator | 5h | 9.5h |
| 3. Closed-Loop Calibration | 5h | 14.5h |
| 4. Safety & Abort | 3h | 17.5h |
| 5. Focus/Context Safety | 3.5h | 21h |
| 6. Integration & Tuning | 4.5h | 25.5h |
| **Buffer (Windows quirks)** | **+30%** | **~33h** |

---

## 10. Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Developer | GS | 2026-11-16 | — |
| Stakeholder (Bet Counterparty) | — | — | — |

---

**END OF PRD**  
*Next action: Begin Phase 1.1 — write `measure_latency.py`*