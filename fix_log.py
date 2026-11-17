with open('live_track.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('\r\n', '\n')

old = """rows.append((round(t_now - t_start, 4), round(dt * 1000.0, 2),
                         round(fps_shown, 1), round(polar_to_game(angle), 2),
                         round(dtheta, 3), round(omega_inst, 1),
                         round(omega_fit, 1), round(conf_tex, 3),
                         round(sharp_tex, 3), round(conf_pro, 3), len(obs),
                         round(widest[1], 2),
                         round(polar_to_game(widest[0] + widest[1] / 2.0), 2),
                         round(corridor, 4)))"""

new = """# Only log real tracking data. When target_lost, write a marker
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

if old in content:
    content = content.replace(old, new)
    print("FIX 4 applied")
else:
    print("FIX 4: OLD NOT FOUND")
    # Try without trailing spaces
    idx = content.find('rows.append((round(t_now - t_start')
    if idx >= 0:
        print("Found at", idx)
        print(repr(content[idx:idx+400]))

with open('live_track.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")