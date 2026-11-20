@echo off
REM -------------------------------------------------------------------------
REM Live tracker / calibration on the PC.
REM Always uses Python 3.13 -- the default "python" on this box is 3.8 and has
REM none of the dependencies installed.
REM
REM   run_track.cmd --preview                      auto-locate + preview
REM   run_track.cmd --bench 5                      headless 5 s timing report
REM   run_track.cmd --cx 1280 --cy 520 --r 168     manual calibration
REM -------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "TMPDIR=%~dp0temp"
set "MPLCONFIGDIR=%~dp0.cache\matplotlib"
set "XDG_CACHE_HOME=%~dp0.cache"
set "PIP_CACHE_DIR=%~dp0.cache\pip"

if not exist "%~dp0temp" mkdir "%~dp0temp"

py -3.13 -u "%~dp0live_track.py" %*

endlocal
