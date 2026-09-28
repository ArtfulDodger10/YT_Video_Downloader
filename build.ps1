# Builds a standalone Windows app into dist\YTDown\ (no Python needed on the target PC).
# Usage:  .\build.ps1                                (uses .venv if present)
#         .\build.ps1 -OneFile                       (single YTDown.exe; starts slower)
#         .\build.ps1 -WithFfmpeg C:\ffmpeg\bin      (bundle ffmpeg.exe + ffprobe.exe)
#         .\build.ps1 -Zip                           (also create dist\YTDown-<version>-windows-x64.zip)
param([switch]$OneFile, [string]$WithFfmpeg = "", [switch]$Zip)
# Not "Stop": Windows PowerShell treats any stderr output of native tools (PyInstaller logs
# everything there) as an error. Exit codes are checked explicitly instead.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$py = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
& $py -m pip install --quiet --upgrade -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
& $py -m PyInstaller --noconfirm --clean --windowed $mode --name YTDown `
    --icon ytdown\assets\icon.ico `
    --add-data "ytdown\assets;ytdown\assets" `
    --collect-all yt_dlp_ejs `
    --exclude-module tkinter `
    YTDown.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$target = if ($OneFile) { "dist" } else { "dist\YTDown" }
# Qt's software-OpenGL fallback (20 MB) is never used by this widgets-only app.
Get-ChildItem $target -Recurse -Filter opengl32sw.dll | Remove-Item -ErrorAction SilentlyContinue
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md $target
if ($WithFfmpeg) {
    Copy-Item (Join-Path $WithFfmpeg "ffmpeg.exe"), (Join-Path $WithFfmpeg "ffprobe.exe") $target
    Write-Host "Bundled ffmpeg from $WithFfmpeg"
}
if ($Zip) {
    $version = & $py -c "import ytdown; print(ytdown.__version__)"
    $zipPath = "dist\YTDown-$version-windows-x64.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath }
    Compress-Archive -Path $target -DestinationPath $zipPath
    Write-Host "Zipped: $((Resolve-Path $zipPath).Path)"
}
Write-Host "Built: $((Resolve-Path $target).Path)"
