@echo off
REM -------------------------------------------------------------------------
REM Autoplay on the PC. Always Python 3.13 (default python is 3.8, no deps).
REM
REM   run_autoplay.cmd --trigger space --cashout-at 2.00 --rounds 1
REM   run_autoplay.cmd --trigger space --cashout-at 2.00 --rounds 10
REM
REM F10 stops the loop. Keep the Chrome window focused.
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

py -3.13 -u "%~dp0autoplay.py" %*

endlocal
