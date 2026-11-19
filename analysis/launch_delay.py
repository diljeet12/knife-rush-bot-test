"""Does the press->launch delay explain the aim error?

For every throw, find the next 'landed' row, read press_to_launch_ms from its
detail, and call it a hit when n_obs went up.  If the delay is part of the
flight time, hit rate must fall as the delay moves away from whatever value
the 205 ms model was calibrated on.
"""
import csv
import re
import sys
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else \
    r"recordings\throws_20261119_092658.csv"

rows = list(csv.DictReader(open(path, newline="")))
print(f"{path}: {len(rows)} rows\n")

throws = []          # (t, omega, gap_w, n_obs)
pend = None
for r in rows:
    ev = r["event"]
    if ev == "throw":
        pend = r
        continue
    if ev == "landed" and pend is not None:
        d = r["detail"]
        m = re.search(r"press_to_launch_ms=([\d.]+)", d)
        delay = float(m.group(1)) if m else float("nan")
        n0 = int(pend["n_obs"])
        n1 = int(r["n_obs"])
        throws.append((float(pend["t"]), float(pend["omega"] or "nan"),
                       float(pend["gap_w"] or "nan"), n0, n1,
                       delay, n1 > n0, float(pend["slot"] or "nan")))
        pend = None

print(f"{len(throws)} throws matched to a landing")
if not throws:
    sys.exit()

hits = sum(1 for x in throws if x[6])
print(f"hit rate {hits}/{len(throws)} = {100.0*hits/len(throws):.1f}%\n")

dl = sorted(x[5] for x in throws)
print(f"launch delay: min {dl[0]:.0f}  median {dl[len(dl)//2]:.0f}  "
      f"max {dl[-1]:.0f}  ms   (spread {dl[-1]-dl[0]:.0f} ms)")

# rotation the log does during the delay, if it spins the whole time
om = sorted(x[1] for x in throws)
med_om = om[len(om) // 2]
print(f"median omega {med_om:.0f} deg/s -> that spread is "
      f"{(dl[-1]-dl[0])/1000.0*abs(med_om):.0f} deg of rotation\n")

for lo, hi in [(0, 370), (370, 420), (420, 470), (470, 600)]:
    sel = [x for x in throws if lo <= x[5] < hi]
    if sel:
        h = sum(1 for x in sel if x[6])
        print(f"delay {lo:3d}-{hi:3d} ms : {h:2d}/{len(sel):2d} hit "
              f"({100.0*h/len(sel):5.1f}%)")

# Time from the previous reload to this press.  If early presses get buffered
# and land badly, misses should cluster at short reload->press.
seq = []
prev_reload_t = None
for x in throws:
    if prev_reload_t is not None:
        seq.append((x[5], (x[0] - prev_reload_t) * 1000.0, x[6], x[1]))
    prev_reload_t = x[0] + x[5] / 1000.0      # throw time + reload delay
print()
for lo, hi in [(0, 150), (150, 300), (300, 450), (450, 900)]:
    sel = [s for s in seq if lo <= s[1] < hi]
    if sel:
        h = sum(1 for s in sel if s[2])
        md = sum(s[0] for s in sel) / len(sel)
        print(f"reload->press {lo:3d}-{hi:3d} ms : {h:2d}/{len(sel):2d} hit "
              f"({100.0*h/len(sel):5.1f}%)   mean launch delay {md:.0f} ms")

# The throw row's `slot` column is the holder-knife colour fraction.
# ~0.16 = a knife is in the holder, ~0.00 = the holder is empty.
print()
for lo, hi in [(0.0, 0.05), (0.05, 0.12), (0.12, 0.20), (0.20, 1.0)]:
    sel = [x for x in throws if lo <= x[7] < hi]
    if sel:
        h = sum(1 for x in sel if x[6])
        md = sum(x[5] for x in sel) / len(sel)
        print(f"holder slot {lo:.2f}-{hi:.2f} : {h:2d}/{len(sel):2d} hit "
              f"({100.0*h/len(sel):5.1f}%)   mean launch delay {md:.0f} ms")

# Correlation between delay and hit, and between delay and omega.
import statistics
h = [x[5] for x in throws if x[6]]
m = [x[5] for x in throws if not x[6]]
if len(h) > 1 and len(m) > 1:
    print(f"\nmean delay on hits   {statistics.mean(h):.0f} ms "
          f"(sd {statistics.pstdev(h):.0f})")
    print(f"mean delay on misses {statistics.mean(m):.0f} ms "
          f"(sd {statistics.pstdev(m):.0f})")
