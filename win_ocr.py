"""Screen capture and OCR using only what Windows already ships.

No Tesseract, no OpenCV, no extra downloads. Capture comes from
System.Drawing and recognition from Windows.Media.Ocr — the same engine
behind Snipping Tool's text actions — reached through PowerShell, exactly
the way this app already reaches System.Speech for TTS.

A note on DPI, because it decides whether any of this works:

The main app is deliberately DPI-unaware so its tkinter UI renders at a
sane size on a scaled display. But a DPI-unaware process capturing the
screen gets a *virtualized* image — on a 4K panel at 300% scaling that
means a blurry upscale of a 1280x720 view, which OCR reads badly.

The capture helper runs in its own short-lived PowerShell process, so it
can call SetProcessDPIAware() and capture true device pixels without
affecting the GUI at all. Bounding boxes therefore come back in the same
3840x2160 space as the measured coordinates, and feed straight into
``win_input.click_at(..., physical=True)``.
"""

import json
import subprocess
import time
import tempfile
from pathlib import Path


OCR_TIMEOUT_SECONDS = 25

# Below this mean brightness a capture is treated as a black frame, which is
# what exclusive-fullscreen games hand back when DWM will not composite them.
BLACK_FRAME_THRESHOLD = 4.0


_PS_SCRIPT = r'''
param(
    [int]$Left = 0,
    [int]$Top = 0,
    [int]$Width = 0,
    [int]$Height = 0,
    [string]$SavePath = "",
    [switch]$CaptureOnly
)

$ErrorActionPreference = "Stop"
$result = [ordered]@{
    ok = $false
    error = $null
    black = $false
    mean_brightness = 0.0
    ocr_available = $false
    language = $null
    lines = @()
    saved = $null
}

try {
    # --- capture in real device pixels ---------------------------------
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class KvpDpi {
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();
}
"@
    [void][KvpDpi]::SetProcessDPIAware()

    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms

    if ($Width -le 0 -or $Height -le 0) {
        $screen = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $Left = $screen.X; $Top = $screen.Y
        $Width = $screen.Width; $Height = $screen.Height
    }

    $bitmap = New-Object System.Drawing.Bitmap($Width, $Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($Left, $Top, 0, 0, $bitmap.Size)
    $graphics.Dispose()

    # --- black-frame detection on a coarse grid ------------------------
    $total = 0.0
    $samples = 0
    $stepX = [Math]::Max(1, [int]($Width / 40))
    $stepY = [Math]::Max(1, [int]($Height / 40))
    for ($y = 0; $y -lt $Height; $y += $stepY) {
        for ($x = 0; $x -lt $Width; $x += $stepX) {
            $pixel = $bitmap.GetPixel($x, $y)
            $total += ($pixel.R + $pixel.G + $pixel.B) / 3.0
            $samples++
        }
    }
    if ($samples -gt 0) { $result.mean_brightness = [Math]::Round($total / $samples, 2) }
    $result.black = ($result.mean_brightness -lt 4.0)

    $temp = [System.IO.Path]::GetTempFileName()
    $png = [System.IO.Path]::ChangeExtension($temp, ".png")
    Remove-Item $temp -ErrorAction SilentlyContinue
    $bitmap.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)

    if ($SavePath -ne "") {
        $bitmap.Save($SavePath, [System.Drawing.Imaging.ImageFormat]::Png)
        $result.saved = $SavePath
    }
    $bitmap.Dispose()

    if ($CaptureOnly) {
        $result.ok = $true
        Remove-Item $png -ErrorAction SilentlyContinue
        $result | ConvertTo-Json -Depth 5 -Compress
        exit 0
    }

    # --- Windows built-in OCR ------------------------------------------
    [void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    [void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
    [void][Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

    function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        [void]$netTask.Wait(-1)
        $netTask.Result
    }

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($engine -eq $null) {
        $result.error = "No OCR language pack is installed for the current user languages."
        $result | ConvertTo-Json -Depth 5 -Compress
        exit 0
    }

    $result.ocr_available = $true
    $result.language = $engine.RecognizerLanguage.LanguageTag

    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($png)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softwareBitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $ocr = Await ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = @()
    foreach ($line in $ocr.Lines) {
        $minX = [double]::MaxValue; $minY = [double]::MaxValue
        $maxX = 0.0; $maxY = 0.0
        foreach ($word in $line.Words) {
            $box = $word.BoundingRect
            if ($box.X -lt $minX) { $minX = $box.X }
            if ($box.Y -lt $minY) { $minY = $box.Y }
            if (($box.X + $box.Width) -gt $maxX) { $maxX = $box.X + $box.Width }
            if (($box.Y + $box.Height) -gt $maxY) { $maxY = $box.Y + $box.Height }
        }
        if ($minX -eq [double]::MaxValue) { continue }

        # Offset into absolute screen coordinates so callers can click directly.
        $lines += [ordered]@{
            text   = $line.Text
            left   = [int]($minX + $Left)
            top    = [int]($minY + $Top)
            width  = [int]($maxX - $minX)
            height = [int]($maxY - $minY)
        }
    }

    $result.lines = $lines
    $result.ok = $true
    $softwareBitmap.Dispose()
    $stream.Dispose()
    Remove-Item $png -ErrorAction SilentlyContinue
}
catch {
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 5 -Compress
'''


_script_path = None


def _ensure_script():
    """Write the PowerShell helper to a temp file once per run.

    Running from a file with -ExecutionPolicy Bypass sidesteps the machine's
    script-execution policy, which is Restricted on many systems.
    """
    global _script_path
    if _script_path is not None and Path(_script_path).exists():
        return _script_path

    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    )
    handle.write(_PS_SCRIPT)
    handle.close()
    _script_path = handle.name
    return _script_path


def _run(args, timeout=OCR_TIMEOUT_SECONDS):
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", _ensure_script(),
    ] + args

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"OCR timed out after {timeout}s.", "lines": [], "elapsed": round(time.monotonic() - started, 2)}
    except FileNotFoundError:
        return {"ok": False, "error": "PowerShell was not found.", "lines": [], "elapsed": round(time.monotonic() - started, 2)}

    payload = (completed.stdout or "").strip()
    if not payload:
        detail = (completed.stderr or "").strip() or "no output"
        return {"ok": False, "error": f"Helper produced nothing ({detail}).", "lines": [],
                "elapsed": round(time.monotonic() - started, 2)}

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": f"Could not parse helper output: {payload[:300]}",
            "lines": [],
            "elapsed": round(time.monotonic() - started, 2),
        }

    # A single line comes back as a dict rather than a list from ConvertTo-Json.
    lines = data.get("lines")
    if isinstance(lines, dict):
        data["lines"] = [lines]
    elif lines is None:
        data["lines"] = []

    data["elapsed"] = round(time.monotonic() - started, 2)
    return data


def capture_region(left, top, width, height, save_path=None):
    """Capture a screen region without running OCR.

    Coordinates are physical device pixels. Useful on its own for the
    black-frame check, which is how exclusive-fullscreen failure shows up.
    """
    args = ["-Left", str(int(left)), "-Top", str(int(top)),
            "-Width", str(int(width)), "-Height", str(int(height)),
            "-CaptureOnly"]
    if save_path:
        args += ["-SavePath", str(save_path)]
    return _run(args, timeout=20)


def ocr_region(left, top, width, height, save_path=None):
    """Capture a region and read its text.

    Returns a dict with ``ok``, ``black``, ``mean_brightness``,
    ``ocr_available``, ``language``, ``error`` and ``lines``. Each line has
    ``text`` plus ``left``/``top``/``width``/``height`` in absolute physical
    screen pixels, ready to click.
    """
    args = ["-Left", str(int(left)), "-Top", str(int(top)),
            "-Width", str(int(width)), "-Height", str(int(height))]
    if save_path:
        args += ["-SavePath", str(save_path)]
    return _run(args)


def ocr_status():
    """Return ``(available, description)`` for display on the STAR MAP page."""
    data = ocr_region(0, 0, 64, 64)
    if data.get("ocr_available"):
        return True, f"Windows OCR available ({data.get('language') or 'unknown'})"

    error = data.get("error") or "unavailable"
    return False, f"Windows OCR unavailable — {error}"


def line_center(line):
    """Return the click point at the centre of an OCR line's box."""
    return (
        int(line["left"] + line["width"] / 2),
        int(line["top"] + line["height"] / 2),
    )
