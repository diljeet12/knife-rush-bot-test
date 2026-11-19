"""Read a --trace CSV and print what the log actually does around a throw.

For each press (a reset of d_click) show the frames from a little before to a
little after, then report:
  * when the holder slot emptied   (knife released)
  * when n_obs went up             (knife landed)
  * how far the log rotated between press and landing, versus the 205 ms the
    aim model assumes.
"""
import csv
import sys

path = sys.argv[1] if len(sys.argv) > 1 else r"temp\trace.csv"
rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
print(f"{path}: {len(rows)} frames")


def f(r, k):
    v = r[k]
    return float(v) if v not in ("", None) else float("nan")


clicks = []
prev = -1.0
for i, r in enumerate(rows):
    dc = f(r, "d_click")
    if dc == dc and dc < prev - 0.05:      # d_click jumped back to ~0
        clicks.append(i)
    if dc == dc:
        prev = dc

print(f"{len(clicks)} presses\n")

for n, i in enumerate(clicks[:6]):
    base = f(rows[i], "d_click")
    n0 = int(rows[i]["n_obs"])
    slot0 = f(rows[i], "slot")
    print(f"--- press {n+1} at t={rows[i]['t']}  n_obs={n0} slot={slot0:.3f}")
    launch = land = None
    for j in range(i, min(len(rows), i + 45)):
        r = rows[j]
        dt = f(r, "t") - f(rows[i], "t")
        sl = f(r, "slot")
        if launch is None and sl < 0.5 * slot0:
            launch = dt
        nb = int(r["n_obs"])
        if land is None and nb > n0:
            land = dt
        mark = ""
        if launch is not None and abs(dt - launch) < 0.02:
            mark = " <-holder empty"
        if land is not None and abs(dt - land) < 0.02:
            mark += " <-LANDED"
        print(f"   +{dt*1000:6.0f}ms  ang {f(r,'angle'):7.2f}  "
              f"w {f(r,'omega'):7.1f}  slot {sl:.3f}  obs {nb:2d}  "
              f"{r['state']}{mark}")
    if launch and land:
        om = f(rows[i], "omega")
        print(f"   press->empty {launch*1000:.0f} ms   "
              f"press->land {land*1000:.0f} ms   "
              f"model assumes 205 ms   "
              f"omega {om:.0f} -> missing {om*(land-0.205):.0f} deg")
    print()
