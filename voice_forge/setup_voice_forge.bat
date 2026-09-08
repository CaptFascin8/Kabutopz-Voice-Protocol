@echo off
setlocal EnableDelayedExpansion
title Kabutopz Voice Protocol - Voice Forge setup
cd /d "%~dp0"

rem  Usage:
rem    setup_voice_forge.bat          detect the hardware and pick a build
rem    setup_voice_forge.bat cuda     force the NVIDIA build
rem    setup_voice_forge.bat cpu      force the CPU build
rem
rem  CPU is not just a fallback. On a machine with unified memory - a GMK
rem  EVO-X2 or similar handheld/mini-PC where the CPU and GPU share one
rem  pool - the CPU build is often the sensible choice, because there is
rem  no separate VRAM to win by moving the model onto the GPU, and the
rem  CUDA wheels are 2.5 GB you would never use.

set "MODE=%~1"

echo ==============================================
echo   VOICE FORGE - optional voice cloning sidecar
echo ==============================================
echo.
echo Chatterbox (MIT licensed) is installed into its own Python
echo environment inside this folder. Nothing is installed system-wide.
echo The main app is untouched and keeps working with the Windows voice
echo whether or not this succeeds.
echo.

python --version
if errorlevel 1 (
    echo.
    echo ERROR: Python was not found on PATH.
    pause
    exit /b 1
)

rem ---- decide which build to install -------------------------------
if /i "%MODE%"=="cuda" goto :chose
if /i "%MODE%"=="cpu"  goto :chose

echo Looking for an NVIDIA GPU...
nvidia-smi --query-gpu=name --format=csv,noheader >nul 2>&1
if errorlevel 1 (
    set "MODE=cpu"
    echo   none found - installing the CPU build.
) else (
    set "MODE=cuda"
    for /f "delims=" %%G in ('nvidia-smi --query-gpu^=name^,memory.total --format^=csv^,noheader 2^>nul') do echo   found %%G
    echo   installing the CUDA build.
)

:chose
echo.
if /i "%MODE%"=="cuda" (
    echo Build:      CUDA ^(NVIDIA^)   about 3.5 GB of download
    echo Rendering:  seconds per line
) else (
    echo Build:      CPU only        about 1 GB of download
    echo Rendering:  roughly 20 seconds per line - fine for a one-off
    echo             render, slow if you re-render often
)
echo.
echo The model weights themselves are fetched the first time you render
echo a voice, not now.
echo.
pause

if not exist ".venv" (
    echo Creating the environment...
    python -m venv ".venv"
    if errorlevel 1 goto :error
)

set "VPY=.venv\Scripts\python.exe"

echo Upgrading pip...
"%VPY%" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :error

rem  Install torch FIRST, from the right index. chatterbox-tts pins
rem  torch 2.6.0; if that is already satisfied pip leaves it alone, so
rem  installing the CUDA wheel up front is what stops the plain
rem  dependency resolve from quietly pulling the CPU one.
echo.
if /i "%MODE%"=="cuda" (
    echo Installing PyTorch with CUDA. This is the long part.
    "%VPY%" -m pip install --disable-pip-version-check --force-reinstall ^
        torch==2.6.0 torchaudio==2.6.0 ^
        --index-url https://download.pytorch.org/whl/cu126
) else (
    echo Installing PyTorch, CPU build.
    "%VPY%" -m pip install --disable-pip-version-check ^
        torch==2.6.0 torchaudio==2.6.0 ^
        --index-url https://download.pytorch.org/whl/cpu
)
if errorlevel 1 goto :error

echo.
echo Installing Chatterbox...
"%VPY%" -m pip install --disable-pip-version-check chatterbox-tts
if errorlevel 1 goto :error

echo.
echo Checking the install...
"%VPY%" -c "import torch, chatterbox; print('  torch      ', torch.__version__); print('  CUDA usable', torch.cuda.is_available()); print('  device     ', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
if errorlevel 1 goto :error

echo.
echo ==============================================
echo   VOICE FORGE READY
echo ==============================================
echo.
echo Open the app, go to the VOICE CLONES page, and create a voice.
echo.
if /i "%MODE%"=="cuda" (
    echo If "CUDA usable" says False above, the driver and the wheel
    echo disagree. Re-run as:  setup_voice_forge.bat cpu
    echo and it will work, just more slowly.
)
pause
exit /b 0

:error
echo.
echo SETUP FAILED
echo.
echo The main app is unaffected and still works with the Windows voice.
echo If the CUDA install was the problem, try:  setup_voice_forge.bat cpu
pause
exit /b 1
