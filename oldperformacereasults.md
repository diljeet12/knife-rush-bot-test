Microsoft Windows [Version 10.0.26200.9974]
(c) Microsoft Corporation. All rights reserved.

C:\Users\gurwi>python -c "import mss, time; sct = mss.MSS(); mon = sct.monitors[1]; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: sct.grab(mon); f += 1'); print('Resolution:', mon['width'], 'x', mon['height'], '| Speed:', round(f/5, 1), 'FPS')"
Resolution: 1920 x 1080 | Speed: 30.0 FPS

C:\Users\gurwi>python -c "import mss, time; sct = mss.MSS(); mon = sct.monitors[1]; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: sct.grab(mon); f += 1'); print('Resolution:', mon['width'], 'x', mon['height'], '| Speed:', round(f/5, 1), 'FPS')"
Resolution: 1920 x 1080 | Speed: 30.2 FPS

C:\Users\gurwi>python -c "import mss, time; sct = mss.MSS(); box = {'top': 340, 'left': 760, 'width': 400, 'height': 400}; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: sct.grab(box); f += 1'); print('400x400 Speed:', round(f/5, 1), 'FPS')"
400x400 Speed: 60.2 FPS

C:\Users\gurwi>python -c "import mss, time; sct = mss.MSS(); hd = {'top': 180, 'left': 320, 'width': 1280, 'height': 720}; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: sct.grab(hd); f += 1'); print('HD (1280x720) Speed:', round(f/5, 1), 'FPS')"
HD (1280x720) Speed: 60.2 FPS

C:\Users\gurwi>python -c "import mss, cv2, numpy as np, time; sct = mss.MSS(); hd = {'top': 180, 'left': 320, 'width': 1280, 'height': 720}; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: img = cv2.cvtColor(np.array(sct.grab(hd)), cv2.COLOR_BGRA2BGR); f += 1'); print('HD + OpenCV Speed:', round(f/5, 1), 'FPS')"
HD + OpenCV Speed: 58.8 FPS

C:\Users\gurwi>python -c "import mss, cv2, numpy as np, time; sct = mss.MSS(); half_hd = {'top': 180, 'left': 320, 'width': 640, 'height': 720}; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: img = cv2.cvtColor(np.array(sct.grab(half_hd)), cv2.COLOR_BGRA2BGR); f += 1'); print('720p Half-Screen (640x720) + OpenCV Speed:', round(f/5, 1), 'FPS')"
720p Half-Screen (640x720) + OpenCV Speed: 59.8 FPS

C:\Users\gurwi>python -c "import mss, cv2, numpy as np, time; sct = mss.MSS(); half_hd = {'top': 180, 'left': 320, 'width': 640, 'height': 720}; t0 = time.time(); f = 0; exec('while time.time() - t0 < 5: img = np.asarray(sct.grab(half_hd))[:, :, :3]; f += 1'); print('720p Half-Screen Fast Slice Speed:', round(f/5, 1), 'FPS')"
720p Half-Screen Fast Slice Speed: 60.0 FPS

C:\Users\gurwi>