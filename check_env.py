"""PC bring-up check: interpreter, deps, display, and real capture speed.

Run with:  py -3.13 check_env.py
"""
from __future__ import annotations

import ctypes
import platform
import sys
import time

import numpy as np


def display_info():
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetDC(0)
    try:
        w = gdi32.GetDeviceCaps(hdc, 8)      # HORZRES
        h = gdi32.GetDeviceCaps(hdc, 10)     # VERTRES
        hz = gdi32.GetDeviceCaps(hdc, 116)   # VREFRESH
        dpi = gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
    finally:
        user32.ReleaseDC(0, hdc)
    return w, h, hz, dpi


def main():
    print("=" * 68)
    print("Knife Rush bot - PC environment check")
    print("=" * 68)
    print(f"OS           : {platform.platform()}")
    print(f"Python       : {sys.version.split()[0]}  ({sys.executable})")

    ok = True
    for name in ("mss", "cv2", "numpy", "PIL"):
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", "?")
            print(f"dependency   : {name:6s} {ver}")
        except Exception as exc:                     # noqa: BLE001
            ok = False
            print(f"dependency   : {name:6s} MISSING ({exc})")

    w, h, hz, dpi = display_info()
    print(f"display      : {w}x{h} @ {hz} Hz  (logical DPI {dpi} = "
          f"{dpi / 96.0 * 100:.0f}% scale)")

    if not ok:
        print("\nFAIL: install dependencies with")
        print("      py -3.13 -m pip install -r requirements.txt")
        return 1

    import mss
    import cv2

    sct = mss.MSS()
    mon = sct.monitors[1]

    def bench(box, seconds=1.0):
        for _ in range(15):
            sct.grab(box)
        t0 = time.perf_counter()
        n = 0
        while time.perf_counter() - t0 < seconds:
            raw = sct.grab(box)
            cv2.cvtColor(np.asarray(raw), cv2.COLOR_BGRA2BGR)
            n += 1
        return n / (time.perf_counter() - t0)

    print("\ncapture benchmark (grab + zero-copy BGRA->BGR):")
    for label, box in (
        ("full screen", mon),
        ("800x1162", {"top": 139, "left": 880, "width": 800, "height": 1162}),
        ("672x977", {"top": 232, "left": 944, "width": 672, "height": 977}),
        ("544x791", {"top": 325, "left": 1008, "width": 544, "height": 791}),
    ):
        fps = bench(box)
        print(f"  {label:14s} {fps:6.1f} fps")

    print("\nNotes:")
    print(f"  * capture cannot exceed the panel: {hz} Hz")
    print("  * keep the game ROI under ~0.55 MP for a sustained 100 fps")
    print("  * run the bot with run_track.cmd / run_autoplay.cmd (py -3.13)")
    print("\nOK" if ok else "\nFAIL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
