# Knife Rush - target rotation speed

- video: `gameplay1.mp4`
- resolution: 1916 x 868
- frame rate: 30.000 fps
- frames analysed: 44
- target centre: (958.33, 247.47) px
- wood radius: 121.80 px
- annulus: 67.0 -> 112.1 px

```
==========================================================================
OVERALL ROTATION SPEED
==========================================================================
valid frames      : 44 / 44 (100.0%)
jitter frames     : 3 repaired (duplicated / catch-up frames)
raw per-frame med : 195.0 deg/s  (inflated by capture jitter - NOT used below)
rotation sign     : positive = clockwise on screen
measured over     : 1.0 s in 0.5 s windows

                       deg/s       rev/s         RPM
min                   194.91      0.5414       32.49
median                195.06      0.5418       32.51
mean                  195.27      0.5424       32.55
max                   201.97      0.5610       33.66
p95                   195.22      0.5423       32.54
std                     1.25      0.0035        0.21

==========================================================================
DETECTED SPEED TIERS: 1
==========================================================================
tier  mean deg/s     rev/s      RPM      min      max     std   share
   1      195.27     0.542     32.5    194.9    202.0     1.2  100.0%

plateau coverage  : 100.0% of frames sit within 8% of a tier centre
  > 70%  -> the game really does use discrete speed steps
  < 40%  -> the speed ramps continuously; 'tiers' are only a summary

direction reversals: none detected (log may spin one way only, or the clip is too short)

cross-check (method A vs B): median disagreement 0.005 deg, 95th pct 0.014 deg over 44 frames
  frames disagreeing by > 2 deg: 0 (0.00%)
```

## Speed tiers

| tier | mean deg/s | rev/s | RPM | min | max | share |
|---|---|---|---|---|---|---|
| 1 | 195.27 | 0.542 | 32.5 | 194.9 | 202.0 | 100.0% |
