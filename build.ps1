# Builds a standalone Windows app into dist\YTDown\ (no Python needed on the target PC).
# Usage:  .\build.ps1            (uses .venv if present)
#         .\build.ps1 -OneFile   (single YTDown.exe; starts slower)
#         .\build.ps1 -WithFfmpeg C:\path\to\ffmpeg\bin   (bundle ffmpeg.exe + ffprobe.exe)
param([switch]$OneFile, [string]$WithFfmpeg = "")
# Not "Stop": Windows PowerShell treats any stderr output of native tools (PyInstaller logs
# everything there) as an error. Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$py = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
& $py -m pip install --quiet --upgrade "yt-dlp[default]" sv-ttk pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
& $py -m PyInstaller --noconfirm --clean --windowed $mode --name YTDown `
    --collect-data sv_ttk `
    --collect-all yt_dlp_ejs `
    YTDown.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$target = if ($OneFile) { "dist" } else { "dist\YTDown" }
if ($WithFfmpeg) {
    Copy-Item (Join-Path $WithFfmpeg "ffmpeg.exe"), (Join-Path $WithFfmpeg "ffprobe.exe") $target
    Write-Host "Bundled ffmpeg from $WithFfmpeg"
}
Write-Host "Built: $((Resolve-Path $target).Path)"
