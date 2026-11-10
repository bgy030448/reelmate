param(
    [string]$Python,
    [switch]$Rebuild,
    [switch]$AI,
    [switch]$Whisper
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Assert-Success($operation) {
    if ($LASTEXITCODE -ne 0) { throw "$operation failed (exit $LASTEXITCODE)." }
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if ($Python) {
        & $Python -m venv .venv
    } elseif (Test-Path -LiteralPath 'C:\Python312\python.exe') {
        & 'C:\Python312\python.exe' -m venv .venv
    } else {
        py -3.12 -m venv .venv
    }
    Assert-Success 'Virtual environment creation'
}

$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $pythonExe -m pip --disable-pip-version-check --no-cache-dir install -r requirements.txt
Assert-Success 'ReelMate dependency installation'
if ($AI) {
    & $pythonExe -m pip --disable-pip-version-check --no-cache-dir install -r requirements-ai.txt
    Assert-Success 'CLIP dependency installation'
}
if ($Whisper) {
    & $pythonExe -m pip --disable-pip-version-check --no-cache-dir install -r requirements-whisper.txt
    Assert-Success 'Whisper dependency installation'
}

& $pythonExe -c "from reelmate.media import executable; executable('ffmpeg'); executable('ffprobe')" 2>$null
if ($LASTEXITCODE -ne 0) {
    if ($env:REELMATE_FFMPEG_BIN) { throw 'Check the configured REELMATE_FFMPEG_BIN.' }
    $ProgressPreference = 'SilentlyContinue'
    New-Item -ItemType Directory -Path '.tools' -Force | Out-Null
    $archive = '.tools\ffmpeg-essentials.zip'
    Invoke-WebRequest -UseBasicParsing 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath '.tools\ffmpeg' -Force
    Remove-Item -LiteralPath $archive
}
& $pythonExe -c "from reelmate.media import executable; print(executable('ffmpeg')); print(executable('ffprobe'))"
Assert-Success 'FFmpeg verification'

if ($Rebuild) {
    Push-Location frontend
    try {
        npm.cmd ci --no-audit --no-fund --cache .npm-cache
        Assert-Success 'React dependency installation'
        npm.cmd run build
        Assert-Success 'React build'
    } finally {
        Pop-Location
    }
}
Write-Host 'ReelMate is ready. Run .\start_windows.cmd and open http://127.0.0.1:8501.'
