@echo off
setlocal
title Kabutopz Voice Protocol - Voice Forge setup
cd /d "%~dp0"

echo ==============================================
echo   VOICE FORGE - optional voice cloning sidecar
echo ==============================================
echo.
echo This installs Chatterbox (MIT licensed) into its own Python
echo environment inside this folder. Nothing is installed system-wide,
echo and the main app is untouched - it keeps working with the Windows
echo voice whether or not this succeeds.
echo.
echo Expect roughly 3 GB of download. The model itself is fetched the
echo first time you render a voice, not now.
echo.
pause

python --version
if errorlevel 1 (
    echo.
    echo ERROR: Python was not found on PATH.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating the environment...
    python -m venv ".venv"
    if errorlevel 1 goto :error
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :error

echo.
echo Installing Chatterbox. This is the long part.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check chatterbox-tts
if errorlevel 1 goto :error

echo.
echo Checking the install...
".venv\Scripts\python.exe" -c "import torch, chatterbox; print('  torch', torch.__version__); print('  CUDA available:', torch.cuda.is_available())"
if errorlevel 1 goto :error

echo.
echo ==============================================
echo   VOICE FORGE READY
echo ==============================================
echo.
echo Open the app, go to the VOICE CLONES page, and create a voice.
echo If "CUDA available" said False above, rendering will still work
echo but will take considerably longer - it runs on the CPU instead.
echo.
pause
exit /b 0

:error
echo.
echo SETUP FAILED
echo.
echo The main app is unaffected and still works with the Windows voice.
pause
exit /b 1
