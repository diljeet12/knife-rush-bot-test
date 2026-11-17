with open('live_track.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('\r\n', '\n')

old = """# ---- state ----------------------------------------------------------- #
    prev_tex = prev_pro = None
    angle = 0.0
    angle_hist = collections.deque(maxlen=120)     # (t, angle)
    last_t = None
    flight_t = args.flight_t
    ring = collections.deque(maxlen=max(1, args.ring))
    rows = []
    fps_t0 = time.perf_counter()
    fps_n = 0
    fps_shown = 0.0
    last_show = 0.0
    show_spokes = False
    last_hud = 0.0
    hk = {}
    hud_period = 1.0 / max(1.0, args.hud_fps)
    omega_fit = 0.0
    t_start = time.perf_counter()

    csv_path = os.path.join(args.outdir, f"live_{stamp}.csv")"""

new = """# ---- state ----------------------------------------------------------- #
    prev_tex = prev_pro = None
    angle = 0.0
    angle_hist = collections.deque(maxlen=120)     # (t, angle)
    last_t = None
    flight_t = args.flight_t
    ring = collections.deque(maxlen=max(1, args.ring))
    rows = []
    fps_t0 = time.perf_counter()
    fps_n = 0
    fps_shown = 0.0
    last_show = 0.0
    show_spokes = False
    last_hud = 0.0
    hk = {}
    hud_period = 1.0 / max(1.0, args.hud_fps)
    omega_fit = 0.0
    t_start = time.perf_counter()

    # --- FIX 1: sign normalisation ---
    sign_decided = False
    sign = 1.0
    sign_buffer = []

    # --- FIX 2: target-lost detection ---
    target_lost = False
    target_lost_since = 0.0
    TARGET_LOST_THRESHOLD = 0.30

    # --- FIX 3: periodic re-locate ---
    last_relocate = t_start
    RELOCATE_PERIOD = 0.50

    csv_path = os.path.join(args.outdir, f"live_{stamp}.csv")"""

if old in content:
    content = content.replace(old, new)
    with open('live_track.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('REPLACED')
else:
    print('OLD NOT FOUND')
    idx = content.find('prev_tex = prev_pro = None')
    if idx >= 0:
        print('FOUND AT', idx)
        print(repr(content[idx:idx+600]))