$ErrorActionPreference = "Stop"

$Repo = "alluses1033/yt-vd"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$Bin = Join-Path $InstallDir "yt-vd.exe"
$GuiBin = Join-Path $InstallDir "yt-vd-gui.exe"

Write-Host "Installing yt-vd..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$BaseUrl = "https://github.com/$Repo/releases/latest/download"
Invoke-WebRequest -Uri "$BaseUrl/yt-vd.exe" -OutFile $Bin
Invoke-WebRequest -Uri "$BaseUrl/yt-vd-gui.exe" -OutFile $GuiBin

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -notcontains $InstallDir) {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$InstallDir", "User")
    $env:Path = "$env:Path;$InstallDir"
    Write-Host "Added $InstallDir to your user PATH." -ForegroundColor Green
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "FFmpeg was not found. Install it with: winget install Gyan.FFmpeg" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "yt-vd installed successfully." -ForegroundColor Green
Write-Host "Open a new PowerShell window, then run:"
Write-Host "  yt-vd --help"
Write-Host "  yt-vd gui"
