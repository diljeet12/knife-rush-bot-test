"""Hit rate per lead (t_total) from a --sweep run.

Every throw row already stores the lead that was used for it, so grouping by
that column compares leads under identical game conditions.  Also prints a
binomial standard error, so a difference of two throws is not mistaken for a
result.
"""
import csv
import math
import sys
from collections import defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else r"recordings\throws\*.csv"
rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))

throws = []
pend = None
for r in rows:
    ev = r["event"]
    if ev == "throw":
        pend = r
        continue
    if ev in ("landed", "no_launch_seen", "flight_stalled", "reload_stalled"):
        if pend is None:
            continue
        n0, n1 = int(pend["n_obs"]), int(r["n_obs"])
        throws.append((float(pend["t_total"]), n1 > n0, int(pend["n_obs"]),
                       float(pend["omega"] or "nan"),
                       float(pend["slack"] or "nan")))
        pend = None

print(f"{len(throws)} throws with a known outcome\n")
by = defaultdict(lambda: [0, 0])
for lead, hit, *_ in throws:
    by[lead][0] += int(hit)
    by[lead][1] += 1

print(f"{'lead':>8}  {'hits':>9}  {'rate':>7}  {'±1se':>6}")
best = None
for lead in sorted(by):
    h, n = by[lead]
    p = h / n
    se = math.sqrt(p * (1 - p) / n) * 100 if n else 0
    print(f"{lead*1000:7.0f}ms  {h:4d}/{n:<4d}  {100*p:6.1f}%  {se:5.1f}%")
    if best is None or p > best[1]:
        best = (lead, p, n)
if best:
    print(f"\nbest {best[0]*1000:.0f} ms at {100*best[1]:.1f}% over {best[2]} throws")

# Does the hit rate depend on spin rate instead? A wrong lead is worth
# omega*t degrees, so if timing were the limit, fast spins should be worse.
print()
byo = defaultdict(lambda: [0, 0])
for lead, hit, n0, om, sl in throws:
    k = "slow <230" if abs(om) < 230 else ("mid 230-300" if abs(om) < 300
                                           else "fast >300")
    byo[k][0] += int(hit)
    byo[k][1] += 1
for k in sorted(byo):
    h, n = byo[k]
    print(f"{k:12s} {h:3d}/{n:<3d}  {100*h/n:5.1f}%")

# And by gap width, which is the other thing that sets the margin.
print()
byg = defaultdict(lambda: [0, 0])
for lead, hit, n0, om, sl in throws:
    k = f"{int(sl//5)*5:2d}-{int(sl//5)*5+5:2d} deg slack"
    byg[k][0] += int(hit)
    byg[k][1] += 1
for k in sorted(byg):
    h, n = byg[k]
    print(f"{k:18s} {h:3d}/{n:<3d}  {100*h/n:5.1f}%")
