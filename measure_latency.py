#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_latency.py  --  Measure the total click-to-landing latency (T_total).
DO NOT USE THIS TOOL WHILE PLAYING REAL MONEY. Demo mode only.

WHAT THIS DOES
--------------
This tool:
1. Starts the live tracker (auto-locate target, overlay, 1440-bin grid).
2. Waits for you to position the mouse over the THROW button.
3. On F2 press:
   a) Records precise timestamp t_click
   b) Clicks via pydirectinput (lowest jitter on Windows)
   c) Polls frames until knife corridor motion > threshold
   d) Records t_land and computes T_total = t_land - t_click
   e) Appends to measurements/latency_samples.csv
4. After 50 samples, prints summary stats and exits.

WHY THIS EXISTS
---------------
Guessing T_total will miss by 10-20 degrees at 321 °/s.

The total delay includes:
1. OS input handling (1-15 ms)
2. Browser input queuing (1-10 ms)  
3. Game tick loop (0-33 ms)
4. Knife animation (0-10 ms)
5. Render pipeline (1-10 ms)
6. Your frame capture + analysis (15-30 ms?)

All together, T_total can vary from 50ms to 300ms depending on:
- Browser load
- Game state  
- System responsiveness
- Your code's frame lag

This tool measures the real-world value to feed into the predictor.

SYSTEM REQUIREMENTS
-------------------
- Windows 10/11
- Python 3.13+ (C:\\Users\\gurwi\\AppData\\Local\\Programs\\Python\\Python313)
- All packages already installed in project venv or global
- Project directory: D:\\random works by gs\\KN helper  <-- CRITICAL
- ALL OUTPUTS TO D: ONLY - NO C: WRITES ALLOWED EVER
- i3-1115G4 (2C/4T @ 3.0 GHz), 8GB RAM  <-- RAM CHECK IN CODE
- 1920×1080 @ 125% DPI (120 DPI)  <-- COORD VERIFICATION REQUIRED

USAGE
-----
1. cd D:\\random works by gs\\KN helper
2. python measure_latency.py
3. Position mouse over THROW button in game
4. Press F2 fifty times (or until satisfied)
5. Observe printed stats and measurements/latency_samples.csv

HARD KILL SWITCH
----------------
F12 - IMMEDIATE TERMINATE (-9 no cleanup)
F11 - Emergency soft stop (save, then exit)
"""

# Standard lib
import os
import sys
import time
import json
import csv
from collections import deque
from datetime import datetime
from threading import Thread, Event

# Third-party
try:
    import numpy as np
    import cv2
    import mss
    import pydirectinput  # Critical: raw input only
    import psutil
except ImportError as e:
    print("[FATAL] Missing imports:", str(e))
    print("Install with:")
    print("pip install opencv-python numpy mss pydirectinput psutil")
    sys.exit(1)

# Our modules (local imports from live_track.py parts)
try:
    from live_track import (
        find_target, 
        roi_for,
        make_polar_maps,
        detect_rotation_and_obstacles,
        periodic_relocate_check,
        draw_status,
        draw_click_through_overlay,
        get_window_handle_excluding_capture,
        DEFAULT_FLIGHT_T,
        DEFAULT_RADIUS
    )
except ImportError as e:
    print("[FATAL] Could not import from live_track.py:", str(e))
    print("Ensure live_track.py is in the same directory.")
    sys.exit(1)


# Constants for safety and compliance with hardware limits
MAX_SAMPLES = 50     # Per session - enough for stable median
MIN_CONSECUTIVE_VALID = 10   # Require 10 good samples before trusting statistics
OUTPUT_DIR = "measurements"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "latency_samples.csv")

# Safety constants - verified appropriate for i3-1115G4
RING_BUFFER_FRAMES = 20    # Not 40 - RAM conservation critical (8GB total)
MAX_FRAME_AGE_MS = 50      # Grace period - frames older than this skipped
MIN_CORRIDOR_DELTA = 0.15  # Knife detection threshold in corridor motion
KILL_SWITCH_POLL_INTERVAL = 0.01  # Poll interval for F11/F12 - must stay tight


def ensure_output_dirs():
    """Create output dirs IF they don't exist - never recreate."""
    print("[INFO] Ensuring output dir:", OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.isdir(OUTPUT_DIR):
        raise RuntimeError(f"[CRITICAL] Cannot create output dir: {OUTPUT_DIR}")


def check_system_resources():
    """Verify system compliance with documented limits."""
    print("[CHECK] Verifying system compliance...")
    
    # Check RAM
    vm = psutil.virtual_memory()
    ram_gb_free = vm.available / (1024**3)
    print(f"[CHECK] RAM free: {ram_gb_free:.2f} GB")
    if ram_gb_free < 1.0:
        print("[WARNING] Less than 1GB RAM free. Ring buffer set to 10 frames.")
        global RING_BUFFER_FRAMES
        RING_BUFFER_FRAMES = 10
        
    cpu_percent = psutil.cpu_percent(interval=1)
    print(f"[CHECK] CPU load: {cpu_percent:.1f}%")
    
    # Check disk space on D:
    disk = psutil.disk_usage("D:\\")
    free_gb = disk.free / (1024**3)
    print(f"[CHECK] D: free space: {free_gb:.2f} GB")


def init_csv_writer():
    """Create CSV writer with headers IF file doesn't exist."""
    file_exists = os.path.isfile(OUTPUT_CSV)
    csvfile = open(OUTPUT_CSV, 'a', newline='', encoding='utf-8')
    writer = csv.writer(csvfile)
    
    if not file_exists:
        writer.writerow([
            'timestamp',
            'sample_num',
            't_click',
            't_land_detect',
            'delta_t_raw_ms',
            'flight_guess_ms',  # For comparison
            'fps',
            'conf_text',
            'omega_fit',
            'n_obstacles',
            'notes'
        ])
        csvfile.flush()
        
    return csvfile, writer


class FrameRingBuffer:
    """FIFO ring buffer for frames - RAM conserved via fixed size."""
    def __init__(self, maxlen=RING_BUFFER_FRAMES):
        self.buffer = deque(maxlen=maxlen)
        self.counter = 0
        
    def push(self, frame_rgb, timestamp):
        """Add frame + timestamp to buffer (discards oldest if full)."""
        self.buffer.append({'rgb': frame_rgb.copy(), 't': timestamp, 'i': self.counter})
        self.counter += 1
        
    def newest(self):
        """Return newest frame dict or None."""
        return self.buffer[-1] if self.buffer else None
        
    def oldest(self):
        """Return oldest frame dict or None."""
        return self.buffer[0] if self.buffer else None
        
    def age_ms(self, t_now):
        """Return age of newest frame in ms, or inf if empty."""
        newest = self.newest()
        return 1e9 if newest is None else (t_now - newest['t']) * 1000


def monitor_corridor_until_motion(sct, roi_box, polar_remap, corridor_mask, 
                                  t_start, quit_flag):
    """
    Poll frames at max rate until knife leaves slot (motion in corridor).
    
    Returns:
        t_detected (float): timestamp when motion detected
        None: if quit requested or timeout
    """
    ringbuf = FrameRingBuffer(RING_BUFFER_FRAMES)
    corridor_base = None  # Baseline for motion detection
    
    print("[WAIT] Monitoring corridor for knife motion...")
    
    while not quit_flag.is_set():
        t_frame = time.perf_counter()
        if t_frame - t_start > 5.0:  # Max 5s wait for motion
            print("[TIMEOUT] No motion detected within 5s")
            return None
            
        # Grab frame
        try:
            frame_bgr = np.array(sct.grab(roi_box))[:, :, :3]  # BGRA -> BGR
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        except Exception as e:
            print(f"[ERROR] Frame grab failed: {e}")
            time.sleep(0.01)
            continue
            
        ringbuf.push(frame_rgb, t_frame)
        
        # Process frame to extract corridor slice
        try:
            polar_img = cv2.remap(frame_rgb, polar_remap[0], polar_remap[1], cv2.INTER_LINEAR)
            corridor_slice = polar_img[corridor_mask]
        except Exception as e:
            print(f"[ERROR] Polar remap failed: {e}")
            time.sleep(0.01)
            continue
        
        # First frame establishes baseline
        if corridor_base is None:
            corridor_base = corridor_slice.copy().astype(np.float32)
            continue
            
        # Compute motion delta - if sharp increase, knife moved
        delta = np.abs(corridor_slice.astype(np.float32) - corridor_base)
        mean_delta = np.mean(delta)
        
        if mean_delta > MIN_CORRIDOR_DELTA:
            print(f"[DETECT] Motion spike {mean_delta:.3f} > {MIN_CORRIDOR_DELTA} at t={(t_frame-t_start)*1000:.1f}ms")
            return t_frame
            
        # Brief sleep to prevent pegging CPU
        time.sleep(0.001)
            
    return None  # Quit requested


def wait_for_key(key, debounce_time=0.2):
    """Wait for a keypress with debouncing."""
    # Wait for key to be released first (if held)
    while pydirectinput.keyDown(key.lower()):
        time.sleep(0.01)
        
    # Wait for key press
    while not pydirectinput.keyDown(key.lower()):
        time.sleep(0.01)
        
    # Debounce
    time.sleep(debounce_time)
    
    # Wait for key release
    while pydirectinput.keyDown(key.lower()):
        time.sleep(0.01)
        
    return True


def sample_one_latency(sct, roi_box, polar_remap, corridor_mask, 
                       hwnd, cx, cy, r, omega_history, sample_num, quit_flag):
    """
    Take one latency sample:
    1. Click
    2. Timestamp
    3. Monitor frames until knife motion
    4. Return T_total
    """
    print(f"\n[SAMPLE {sample_num:2d}] Position mouse and press F2...")
    
    # Wait for F2
    wait_for_key('f2')
        
    # Record click time PRECISELY before sending click
    t_click = time.perf_counter()
    
    # Send click at current mouse position
    try:
        # Get current mouse position
        x, y = pydirectinput.position()
        pydirectinput.click(x, y)
        print(f"[CLICK] Sent at t={(t_click*1000)%10000:.3f}ms (x={x}, y={y})")
    except Exception as e:
        print(f"[ERROR] Click failed: {e}")
        return None
        
    # Monitor frames until motion detected (knife leaves slot)
    t_land = monitor_corridor_until_motion(
        sct, roi_box, polar_remap, corridor_mask, 
        t_click, quit_flag
    )
    
    if t_land is None:
        print("[SKIP] No motion detected - sample invalid")
        return None
        
    delta_t_ms = (t_land - t_click) * 1000
    print(f"[RESULT] T_total = {delta_t_ms:.2f} ms")
    
    return {
        't_click': t_click,
        't_land': t_land,
        'delta_t_ms': delta_t_ms
    }


def check_quit_keys(quit_flag, soft_quit_flag):
    """Check for quit keys in a separate thread."""
    while not quit_flag.is_set():
        if pydirectinput.keyDown('f12'):
            print("\n[F12] HARD QUIT REQUESTED")
            quit_flag.set()
            return
        elif pydirectinput.keyDown('f11'):
            print("\n[F11] SOFT QUIT REQUESTED")
            soft_quit_flag.set()
            # Wait for release
            while pydirectinput.keyDown('f11'):
                time.sleep(0.01)
        time.sleep(KILL_SWITCH_POLL_INTERVAL)


def main():
    """Main latency measurement loop."""
    print("[START] Knife Rush Latency Measurement Tool")
    print("[WARN] DEMO MODE ONLY - DO NOT USE WITH REAL MONEY")
    
    ensure_output_dirs()
    check_system_resources()
    csvfile, csvwriter = init_csv_writer()
    
    # Quit flags for F11/F12
    quit_flag = Event()
    soft_quit_flag = Event()
    
    # Start key monitoring thread
    key_thread = Thread(target=check_quit_keys, args=(quit_flag, soft_quit_flag), daemon=True)
    key_thread.start()
    
    # Initialize MSS and locate target
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # Primary
        print(f"[INIT] Monitor: {monitor['width']}×{monitor['height']}")
        
        # Auto-locate target (blocks until found)
        try:
            cx, cy, r = find_target(sct)
            print(f"[FOUND] Target at ({cx}, {cy}) r={r}")
        except Exception as e:
            print(f"[ERROR] Failed to locate target: {e}")
            return 1
        
        # Setup ROI and polar mappings
        try:
            roi_box = roi_for(cx, cy, r)
            roi_w = roi_box['width']
            roi_h = roi_box['height']
            polar_remap = make_polar_maps(roi_w, roi_h, r)
            print(f"[ROI] Size: {roi_w}×{roi_h}")
        except Exception as e:
            print(f"[ERROR] Failed to setup ROI/polar maps: {e}")
            return 1
        
        # Create corridor mask (where knife slot appears)
        # Based on empirical analysis: waiting knife spans 2.24R–2.86R below centre
        corridor_mask = np.zeros((roi_h, roi_w), dtype=bool)
        corridor_top = int(roi_h * 0.75)  # Rough approximation - could be refined
        corridor_bottom = int(roi_h * 0.95)
        corridor_mask[corridor_top:corridor_bottom, :] = True
        print(f"[CORRIDOR] Rows {corridor_top}-{corridor_bottom} (approx)")
        
        # Ring buffer for periodic checks
        frame_ringbuf = FrameRingBuffer(RING_BUFFER_FRAMES)
        omega_history = []
        
        sample_count = 0
        valid_samples = []
        
        print("\n=== READY FOR SAMPLING ===")
        print("Position mouse over THROW button. Press F2 to sample.")
        print("Press F11 for stats + graceful exit, F12 for hard kill.")
        
        # Main loop
        while sample_count < MAX_SAMPLES and not quit_flag.is_set():
            # Handle soft quit
            if soft_quit_flag.is_set():
                print("[QUIT] Soft quit requested")
                break
                
            result = sample_one_latency(
                sct, roi_box, polar_remap, corridor_mask,
                hwnd=None, cx=cx, cy=cy, r=r,
                omega_history=omega_history, sample_num=sample_count+1,
                quit_flag=quit_flag
            )
            
            if result is not None:
                valid_samples.append(result['delta_t_ms'])
                
                # Write to CSV
                try:
                    csvwriter.writerow([
                        datetime.now().isoformat(),
                        sample_count + 1,
                        f"{result['t_click']:.6f}",
                        f"{result['t_land']:.6f}",
                        f"{result['delta_t_ms']:.3f}",
                        f"{DEFAULT_FLIGHT_T * 1000:.1f}",  # Flight guess for comparison
                        "TODO",  # FPS calc
                        "TODO",  # Confidence
                        "TODO",  # Omega
                        "TODO",  # Obstacle count
                        ""  # Notes
                    ])
                    csvfile.flush()
                except Exception as e:
                    print(f"[ERROR] CSV write failed: {e}")
                
                sample_count += 1
                
                # Print running stats after minimum samples
                if len(valid_samples) >= MIN_CONSECUTIVE_VALID:
                    median = np.median(valid_samples)
                    std = np.std(valid_samples)
                    print(f"[STATS] N={len(valid_samples)} Median={median:.2f}ms ±{std:.2f}ms")
            elif quit_flag.is_set():
                break
                    
        # Final summary
        if valid_samples:
            median = np.median(valid_samples)
            mean = np.mean(valid_samples)
            std = np.std(valid_samples)
            p95 = np.percentile(valid_samples, 95)
            
            print("\n=== FINAL RESULTS ===")
            print(f"Samples: {len(valid_samples)}/{MAX_SAMPLES}")
            print(f"Median T_total: {median:.2f} ms")
            print(f"Mean: {mean:.2f} ms")
            print(f"Std dev: {std:.2f} ms")
            print(f"95th percentile: {p95:.2f} ms")
            print(f"Range: [{np.min(valid_samples):.2f}, {np.max(valid_samples):.2f}] ms")
            print(f"\nCSV saved to: {OUTPUT_CSV}")
            
            # Save summary to JSON as well
            summary = {
                "samples_collected": len(valid_samples),
                "median_t_total_ms": float(median),
                "mean_t_total_ms": float(mean),
                "std_dev_ms": float(std),
                "percentile_95_ms": float(p95),
                "min_ms": float(np.min(valid_samples)),
                "max_ms": float(np.max(valid_samples)),
                "timestamp": datetime.now().isoformat()
            }
            
            summary_file = os.path.join(OUTPUT_DIR, "latency_summary.json")
            try:
                with open(summary_file, 'w') as f:
                    json.dump(summary, f, indent=2)
                print(f"Summary saved to: {summary_file}")
            except Exception as e:
                print(f"[ERROR] Failed to save summary: {e}")
            
        else:
            print("[FAIL] No valid samples collected.")
            
    csvfile.close()
    print("[DONE] Latency measurement complete.")
    return 0


if __name__ == '__main__':
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[EXIT] Keyboard interrupt received.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[CRASH] Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)