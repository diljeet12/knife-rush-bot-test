# Hardware Scan — ASUS VivoBook X515EA

**Date:** 2026-11-16
**Purpose:** establish what this machine can actually do before building a 60 Hz vision loop.

---

## Raw results

### CPU

| | |
|---|---|
| Model | Intel Core i3-1115G4 @ 3.00 GHz |
| Cores / threads | **2 / 4** |
| Max / current clock | 2995 / 2995 MHz |
| L2 / L3 cache | 2.5 MB / 6 MB |
| Generation | Tiger Lake (11th gen, 2020), 15 W class |

### RAM

| | |
|---|---|
| Installed / visible | 8 GB / **7.7 GB** |
| Module 1 | 4 GB SK Hynix HMA851S6DJR6N-XN, DDR4-3200 |
| Module 2 | 4 GB SK Hynix HMA851S6DJR6N-XN, DDR4-3200 |
| Channel config | dual channel, both slots populated |
| **Free** | **1.3 GB** |
| **Used** | **6.41 GB (83.2%)** |
| Pagefile | 8.71 GB allocated, **1.27 GB in use**, peak 1.58 GB |

### Storage

| Volume | Total | Free | Used | Free % |
|---|---|---|---|---|
| **C:** (OS) | 170.43 GB | **14.43 GB** | 156.0 GB | **8.5%** |
| D: (New Volume) | 305.0 GB | **131.21 GB** | 173.79 GB | 43.0% |

Physical device: **NVMe INTEL SSDPEKNU512GZ, 477 GB, SSD**, health OK, RAID bus type.
One 512 GB drive split into C: (170 GB) and D: (305 GB).

### Display / GPU

| | |
|---|---|
| GPU | Intel UHD Graphics (integrated) |
| VRAM | 1 GB shared |
| Driver | 31.0.101.4255 |
| Resolution | 1920 × 1080 |
| **Refresh rate** | **60 Hz — CONFIRMED** |

### Top memory consumers at scan time

| Process | RAM |
|---|---|
| Memory Compression | 569 MB |
| opencode (×2) | 349 + 237 MB |
| VS Code (×4) | 257 + 140 + 89 + 89 MB |
| chrome | 190 MB |
| explorer | 186 MB |
| MsMpEng (Defender) | 160 MB |

---

## What this means for the project

### The refresh rate is confirmed

MSS benchmarked at exactly 60.2 FPS on every ROI size. That inference was correct —
the panel is **60 Hz**. Information rate is capped at **16.67 ms per frame, permanently**.
No code change fixes this.

Degrees of log rotation per captured frame:

| speed tier | °/frame @ 60 Hz | °/frame @ 30 Hz (recording) |
|---|---|---|
| 194.5 °/s | 3.24° | 6.48° |
| 321.2 °/s | 5.35° | 10.71° |

### The CPU is weak but adequate

The i3-1115G4 is a 2-core / 4-thread 15 W part. It is **not** capable of running a neural
network in a 16.7 ms loop. It **is** capable of classical correlation — the measured
9.6 ms/frame for the full offline path (including the cross-check estimator) was taken on
this exact machine, not estimated.

Implication: the lean real-time path (crop → grayscale → remap → one FFT) still needs its
own measurement. Do not quote a number for it until it is timed.

Threading note: only 2 physical cores, so the GIL matters. Capture, vision and input
should not fight over the same core.

### RAM is the biggest risk

**1.3 GB free, 83.2% used, and 1.27 GB already paged to disk.** The machine is under memory
pressure *before* the game and the bot are running.

Failure mode: when free RAM runs out, Windows pages to the NVMe. A page fault costs
0.1–1 ms and is not schedulable. In a 16.7 ms loop that is a missed throw.

A browser with the game plus Python/OpenCV/numpy will add roughly 1–1.5 GB. There is not
1.5 GB to spare.

### C: drive is nearly full

**14.43 GB free = 8.5%.** Windows wants 15–20% free for updates, the pagefile and temp
files. At 8.5%, pagefile growth is constrained and Windows Update will start failing.

Meanwhile D: has **131 GB free**. All recordings, outputs and caches belong on D:, not C:.

### Thermal throttling is a real hazard

A 15 W dual-core under sustained 100% Python load will heat up and clock down. If the CPU
drops from 3.0 GHz to 1.8 GHz mid-game, the vision loop stretches and timing consistency
dies. This must be monitored during any live run, not assumed away.

### No discrete GPU

No CUDA, no usable inference acceleration. Confirms the decision to keep neural networks
out of the runtime path entirely.

---

## Actions before any live run

1. **Close VS Code, extra Chrome tabs, and any other app.** Target ≥ 3 GB free RAM.
   Currently 1.3 GB. This is the single highest-value change.
2. **Put `gameplay*.mp4`, all outputs and the `measurements/` folder on D:**. 131 GB free
   versus 14 GB.
3. **Free space on C:** — clear `%TEMP%`, `C:\Windows\Temp`, and run Disk Cleanup including
   Windows Update leftovers. Target ≥ 25 GB free.
4. **Monitor thermals and clock during the first live run.** If the effective clock drops
   below ~2.5 GHz, the timing model must be rebuilt around the slower rate.
5. **Confirm 60 Hz in Windows display settings** — WMI reports 60, a human should eyeball
   it once.

---

*Scan performed read-only. No files were modified.*
