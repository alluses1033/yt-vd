$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "alluses1033/yt-vd"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$Bin = Join-Path $InstallDir "yt-vd.exe"
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) { return "{0:N1} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N1} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N1} KB" -f ($Bytes / 1KB) }

    return "$Bytes B"
}

function Get-ReleaseAsset {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $Asset = $Release.assets |
        Where-Object { $_.name -eq $Name } |
        Select-Object -First 1

    if (-not $Asset) {
        throw "Release does not contain asset: $Name"
    }

    return $Asset
}

function Stop-ExistingProcesses {

    Write-Host "Stopping running yt-vd processes..."

    Get-Process -Name "yt-vd", "yt-vd-gui" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 1
}

function Download-Asset {
    param(
        [Parameter(Mandatory = $true)]$Asset,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    $Name = $Asset.name
    $Url = $Asset.browser_download_url
    $Size = Format-Bytes -Bytes $Asset.size

    Write-Host "Downloading $Name ($Size)..."

    Invoke-WebRequest `
        -Uri $Url `
        -OutFile $OutFile `
        -Headers @{ "User-Agent" = "yt-vd-installer" }

    if (-not (Test-Path -LiteralPath $OutFile)) {
        throw "Download did not create expected file: $OutFile"
    }

    $DownloadedSize = (Get-Item -LiteralPath $OutFile).Length
    if ($Asset.size -gt 0 -and $DownloadedSize -ne [int64]$Asset.size) {
        throw "Downloaded size mismatch for $Name. Expected $($Asset.size) bytes, got $DownloadedSize bytes."
    }
}

Write-Host "Installing yt-vd..."

# Fetch release
$Release = Invoke-RestMethod `
    -Uri $ApiUrl `
    -Headers @{ "User-Agent" = "yt-vd-installer" }

$RemoteVersion = $Release.tag_name

Write-Host "Latest version: $RemoteVersion"

# Stop old binaries before replacement, but keep the existing install until the
# new asset is downloaded and validated.
Stop-ExistingProcesses

# Create install directory
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Download CLI
$CliAsset = Get-ReleaseAsset `
    -Release $Release `
    -Name "yt-vd-windows.exe"

$TempDir = Join-Path $InstallDir ".yt-vd-install-$PID"
$TempBin = Join-Path $TempDir "yt-vd.exe"
$BackupBin = Join-Path $InstallDir "yt-vd.exe.bak"

try {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

    Download-Asset `
        -Asset $CliAsset `
        -OutFile $TempBin

    if (Test-Path -LiteralPath $BackupBin) {
        Remove-Item -LiteralPath $BackupBin -Force -ErrorAction SilentlyContinue
    }

    if (Test-Path -LiteralPath $Bin) {
        Move-Item -LiteralPath $Bin -Destination $BackupBin -Force
    }

    try {
        Move-Item -LiteralPath $TempBin -Destination $Bin -Force
    } catch {
        if ((Test-Path -LiteralPath $BackupBin) -and -not (Test-Path -LiteralPath $Bin)) {
            Move-Item -LiteralPath $BackupBin -Destination $Bin -Force
        }
        throw
    }

    if (Test-Path -LiteralPath $BackupBin) {
        Remove-Item -LiteralPath $BackupBin -Force -ErrorAction SilentlyContinue
    }
} finally {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Add PATH if missing
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")

if (($UserPath -split ";") -notcontains $InstallDir) {

    [Environment]::SetEnvironmentVariable(
        "Path",
        "$UserPath;$InstallDir",
        "User"
    )

    $env:Path += ";$InstallDir"

    Write-Host "Added to PATH."
}

# Create uninstaller
$UninstallScript = @'
$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$UserAppDataDir = Join-Path $env:LOCALAPPDATA "yt-vd\yt-vd"
$ParentAppDataDir = Join-Path $env:LOCALAPPDATA "yt-vd"

Get-Process -Name "yt-vd", "yt-vd-gui" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $UserAppDataDir) {
    Remove-Item -LiteralPath $UserAppDataDir -Recurse -Force
}

if (Test-Path -LiteralPath $ParentAppDataDir) {
    $Items = Get-ChildItem -LiteralPath $ParentAppDataDir -ErrorAction SilentlyContinue
    if (-not $Items) {
        Remove-Item -LiteralPath $ParentAppDataDir -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")

if ($UserPath) {

    $NewPath = (
        ($UserPath -split ";") |
        Where-Object {
            $_ -ne $InstallDir -and
            $_ -ne "$InstallDir\"
        }
    ) -join ";"

    [Environment]::SetEnvironmentVariable(
        "Path",
        $NewPath,
        "User"
    )
}

Write-Host "yt-vd uninstalled successfully."
'@

$UninstallScript |
    Out-File `
    -FilePath (Join-Path $InstallDir "uninstall.ps1") `
    -Encoding utf8 `
    -Force

# FFmpeg warning
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "FFmpeg not found."
    Write-Host "Install using:"
    Write-Host "winget install Gyan.FFmpeg"
}

Write-Host ""
Write-Host "yt-vd installed successfully."
Write-Host "Restart PowerShell and run:"
Write-Host "yt-vd --help"
