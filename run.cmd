@echo off
REM -------------------------------------------------------------------------
REM Launcher for find_speed.py that keeps EVERYTHING on the project drive.
REM No temp files, no caches, no matplotlib config on C:.
REM -------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "TMPDIR=%~dp0temp"
set "MPLCONFIGDIR=%~dp0.cache\matplotlib"
set "XDG_CACHE_HOME=%~dp0.cache"
set "PIP_CACHE_DIR=%~dp0.cache\pip"
set "HF_HOME=%~dp0.cache\huggingface"
set "TORCH_HOME=%~dp0.cache\torch"

if not exist "%~dp0temp" mkdir "%~dp0temp"
if not exist "%~dp0.cache\matplotlib" mkdir "%~dp0.cache\matplotlib"

python "%~dp0find_speed.py" %*

endlocal
