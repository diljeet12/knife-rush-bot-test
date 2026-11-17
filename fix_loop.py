with open('live_track.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('\r\n', '\n')

# ============================================================
# FIX 1: Sign normalisation - after omega_fit computation
# ============================================================
old1 = """                    # unwrap before fitting
                    un = np.unwrap(np.radians(a_arr))
                    A = np.column_stack([t_arr - t_arr[0], np.ones_like(t_arr)])
                    slope = np.linalg.lstsq(A, un, rcond=None)[0][0]
                    omega_fit = math.degrees(float(slope))

            # ---- occupancy / gaps ---------------------------------------- #"""

new1 = """                    # unwrap before fitting
                    un = np.unwrap(np.radians(a_arr))
                    A = np.column_stack([t_arr - t_arr[0], np.ones_like(t_arr)])
                    slope = np.linalg.lstsq(A, un, rcond=None)[0][0]
                    omega_fit = math.degrees(float(slope))

            # ---- FIX 1: sign normalisation ----
            # Decide rotation direction once from the first ~0.5 s of confident frames.
            # Rotation is one-directional; the correlation peak sign is arbitrary.
            if not sign_decided and good and abs(omega_fit) > 20.0:
                sign_buffer.append(omega_fit)
                if len(sign_buffer) >= 15:  # ~0.5 s at 30 Hz
                    median_fit = float(np.median(sign_buffer))
                    sign = 1.0 if median_fit > 0 else -1.0
                    sign_decided = True
                    print(f"[sign] rotation direction locked: {'CW' if sign > 0 else 'CCW'} (median {median_fit:.1f} deg/s)")
            if sign_decided:
                omega_fit *= sign
                omega_inst *= sign
                dtheta *= sign
                angle = (angle + dtheta) % 360.0  # re-apply with correct sign

            # ---- occupancy / gaps ---------------------------------------- #"""

if old1 in content:
    content = content.replace(old1, new1)
    print("FIX 1 applied")
else:
    print("FIX 1: OLD NOT FOUND")

# ============================================================
# FIX 2: Target-lost detection - after obs/gaps computed
# ============================================================
old2 = """            i0 = int(N_RING * OCC_IN_FRAC)
            occ = occ_full[i0:]           # only the outer part of the PRO ring
            obs = runs_of(occ, MIN_RUN_DEG, MAX_OBJ_DEG)
            gaps = gaps_of(occ, MIN_RUN_DEG)
            widest = max(gaps, key=lambda g: g[1]) if gaps else (0.0, 0.0)
            t_e = time.perf_counter()

            # ---- corridor motion ----------------------------------------- #"""

new2 = """            i0 = int(N_RING * OCC_IN_FRAC)
            occ = occ_full[i0:]           # only the outer part of the PRO ring
            obs = runs_of(occ, MIN_RUN_DEG, MAX_OBJ_DEG)
            gaps = gaps_of(occ, MIN_RUN_DEG)
            widest = max(gaps, key=lambda g: g[1]) if gaps else (0.0, 0.0)

            # ---- FIX 2: target-lost detection ----
            # We are "tracking" only if we see >= 8 knives (obstacles) AND
            # the sky annulus around the target centre is still >35% sky.
            # If not, we're blind - don't log zeros as data.
            sky_now = sky_annulus_frac(frame, cxl, cyl, r)
            tracking_ok = (len(obs) >= 8 and sky_now >= 0.35)

            if tracking_ok:
                target_lost = False
                target_lost_since = 0.0
            else:
                if not target_lost:
                    target_lost = True
                    target_lost_since = t_now
                elif t_now - target_lost_since > TARGET_LOST_THRESHOLD:
                    # Blind for > 0.3 s - force re-locate on next cycle
                    print(f"[lost] target lost for {t_now - target_lost_since:.1f}s (obs={len(obs)}, sky={100*sky_now:.0f}%) -> re-locating")
                    # The periodic re-locate logic will catch this, but we can
                    # also force it immediately by setting last_relocate = 0
                    last_relocate = 0.0

            t_e = time.perf_counter()

            # ---- corridor motion ----------------------------------------- #"""

if old2 in content:
    content = content.replace(old2, new2)
    print("FIX 2 applied")
else:
    print("FIX 2: OLD NOT FOUND")

# ============================================================
# FIX 3: Periodic re-locate - add after corridor motion
# ============================================================
old3 = """            else:
                corridor = 0.0

            ring.append(frame.copy())"""

new3 = """            else:
                corridor = 0.0

            # ---- FIX 3: periodic re-locate (every 0.5 s) ----
            if t_now - last_relocate >= RELOCATE_PERIOD:
                last_relocate = t_now
                # Verify the target is still where we think it is by checking
                # the sky annulus on the CURRENT frame (in ROI coords).
                sky_now = sky_annulus_frac(frame, cxl, cyl, r)
                if sky_now < 0.35:
                    print(f"[relocate] sky annulus dropped to {100*sky_now:.0f}% -> re-locating")
                    full = np.array(sct.grab(mon))[:, :, :3].copy()
                    got = find_target(full)
                    if got:
                        cx, cy, r = got
                        bbox = roi_for(cx, cy, r, sw, sh,
                                       args.pad_x, args.pad_up, args.pad_down)
                        x0, y0 = bbox["left"], bbox["top"]
                        cxl, cyl = cx - x0, cy - y0
                        geo = build_geometry(cxl, cyl, r)
                        mx_tex, my_tex = geo["tex"]
                        mx_pro, my_pro = geo["pro"]
                        cor_y0 = int(cyl + r * 1.02)
                        cor_y1 = int(min(bbox["height"], cyl + r * 1.95))
                        cor_x0 = int(max(0, cxl - 0.22 * r))
                        cor_x1 = int(min(bbox["width"], cxl + 0.22 * r))
                        prev_tex = prev_pro = None
                        angle_hist.clear()
                        sign_decided = False
                        sign_buffer = []
                        target_lost = False
                        print(f"[relocate] recalibrated ({cx:.1f}, {cy:.1f}) r={r:.1f}")

            ring.append(frame.copy())"""

if old3 in content:
    content = content.replace(old3, new3)
    print("FIX 3 applied")
else:
    print("FIX 3: OLD NOT FOUND")

# ============================================================
# FIX 4: Don't log zeros when target is lost
# ============================================================
old4 = """            rows.append((round(t_now - t_start, 4), round(dt * 1000.0, 2),
                          round(fps_shown, 1), round(polar_to_game(angle), 2),
                          round(dtheta, 3), round(omega_inst, 1),
                          round(omega_fit, 1), round(conf_tex, 3),
                          round(sharp_tex, 3), round(conf_pro, 3), len(obs),
                          round(widest[1], 2),
                          round(polar_to_game(widest[0] + widest[1] / 2.0), 2),
                          round(corridor, 4)))"""

new4 = """            # Only log real tracking data. When target_lost, write a marker
            # row with n_obstacles=-1 so analysis can filter it out.
            if target_lost:
                rows.append((round(t_now - t_start, 4), round(dt * 1000.0, 2),
                              round(fps_shown, 1), -1.0, 0.0, 0.0, 0.0,
                              0.0, 0.0, 0.0, -1, 0.0, 0.0, round(corridor, 4)))
            else:
                rows.append((round(t_now - t_start, 4), round(dt * 1000.0, 2),
                              round(fps_shown, 1), round(polar_to_game(angle), 2),
                              round(dtheta, 3), round(omega_inst, 1),
                              round(omega_fit, 1), round(conf_tex, 3),
                              round(sharp_tex, 3), round(conf_pro, 3), len(obs),
                              round(widest[1], 2),
                              round(polar_to_game(widest[0] + widest[1] / 2.0), 2),
                              round(corridor, 4)))"""

if old4 in content:
    content = content.replace(old4, new4)
    print("FIX 4 applied")
else:
    print("FIX 4: OLD NOT FOUND")

with open('live_track.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")