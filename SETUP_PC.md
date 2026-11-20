# PC Setup — 2026-11-19

This machine is the **PC**, not the ASUS laptop. The project was copied to
`E:\KN helper - Copy`. Everything below was measured on this box, not estimated.

## Hardware (measured)

| | |
|---|---|
| CPU | AMD Ryzen 5 5600X, 6 cores / 12 threads |
| RAM | 32 GB (22 GB free) |
| GPU | NVIDIA RTX 4060 |
| Display | 2560×1440 @ **100 Hz** (Windows reports 100, not 144) |
| DPI | 96 = 100 % scale (no CSS/DPI scaling problems) |
| Disks | C: 130 GB free, E: 414 GB free |

> **Action:** set the monitor to 144 Hz in Windows display settings. It is the
> single biggest accuracy lever in `accuracy_increaser_next_plan.md`. MSS caps
> at the panel rate, so today the ceiling is 100 fps.

## Python — do not use the default `python`

| | |
|---|---|
| `python` | **3.8.9 — has NONE of the dependencies** |
| `py -3.13` | **3.13.7 — has mss 10.2.0, cv2 5.1.0, numpy 2.3.2, Pillow 11.3.0** |

Always launch with the wrappers, which force 3.13:

```
run_track.cmd                 # live_track.py + preview
run_track.cmd --bench 5       # headless timing report
run_autoplay.cmd --trigger space --cashout-at 2.00 --rounds 1
```

`run.cmd` was also updated to use `py -3.13`.

## The optimization (applied 2026-11-19)

`raw.bgra` returns a **2.77 MB `bytes` copy on every access**. The old hot path
accessed it twice and then slice-copied the 3-channel view:

```python
frame = np.frombuffer(raw.bgra, ...).reshape(h, w, 4)[:, :, :3].copy()
```

Replaced with a zero-copy view + one SIMD conversion in **both** `live_track.py`
and `autoplay.py`:

```python
frame = cv2.cvtColor(np.asarray(raw), cv2.COLOR_BGRA2BGR)
```

| path | fps | ms/frame |
|---|---|---|
| grab only | 99.5 | 10.05 |
| grab + OLD extract | **50.0** | 19.99 |
| grab + NEW extract | **98.5** | 10.15 |
| grab + OLD → gray | 50.0 | 19.99 |
| grab + NEW → gray | **99.4** | 10.06 |

Proof the view is safe: `np.asarray(raw).base` is the temporary `bytearray`,
pixels are byte-identical, and the view survives later grabs and `del raw`.

Also removed one redundant `frame.copy()` in the ring buffer (the frame is a
fresh allocation each iteration).

## Real capture measurements (this PC)

MSS has a **~16 ms floor** and is **vsync-quantized**: a 32×32 grab is exactly
100.0 fps, a full-screen grab is ~28–33 fps, and anything that misses the 10 ms
budget snaps to 50 fps (100/2) or 33 fps (100/3).

Full vision pipeline (grab → gray → 2× remap → signatures → FFT → sky mask),
ROI pads `3.20R × 4.65R`, after the optimization:

| radius | ROI | MP | fps |
|---|---|---|---|
| ≤ 170 | 544×791 | 0.43 | **98–100** |
| 190 | 608×884 | 0.54 | **98** |
| 210 | 672×977 | 0.66 | 54 |
| ≥ 230 | 736×1070 | 0.79 | 50 (unstable) |
| full screen | 2560×1440 | 3.69 | 28–33 |

**Rule:** keep the capture ROI **≤ ~0.55 MP** to hold ~100 fps.
At the laptop-equivalent scale (`r ≈ 168 px` on 2560×1440) the ROI is ~0.42 MP,
so the bot should run at **~100 fps**.

## What to expect when shifting

* Target detection, ROI, GO button and cash-out are all **auto-detected** from
  pixels, so they adapt to 2560×1440. Only a first-run calibration is needed.
* `live_track.py` rewrites `measurements/calibration.json` on startup. The
  laptop values are backed up at
  `%TEMP%\opencode\calibration_laptop_backup.json`.
* The laptop calibration (`cx=959.6, cy=400.1, r=125.6`) is **not** valid here;
  recalibrate with `run_track.cmd` while the game is visible.

## Reproduce the numbers

```
py -3.13 temp\framerate_test.py            # full stage breakdown
py -3.13 temp\framerate_test.py --sweep    # ROI threshold sweep
py -3.13 check_env.py                      # deps + display + 4-size benchmark
```
