$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "alluses1033/yt-vd"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$Bin = Join-Path $InstallDir "yt-vd.exe"
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) {
        return "{0:N1} GB" -f ($Bytes / 1GB)
    }

    if ($Bytes -ge 1MB) {
        return "{0:N1} MB" -f ($Bytes / 1MB)
    }

    if ($Bytes -ge 1KB) {
        return "{0:N1} KB" -f ($Bytes / 1KB)
    }

    return "$Bytes B"
}

function Get-ReleaseAsset {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $Asset = $Release.assets | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if (-not $Asset) {
        $Names = ($Release.assets | ForEach-Object { $_.name }) -join ", "
        if (-not $Names) {
            $Names = "none"
        }

        throw "Release $($Release.tag_name) does not include $Name. Available assets: $Names"
    }

    return $Asset
}

function Download-Asset {
    param(
        [Parameter(Mandatory = $true)]$Asset,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    $Name = $Asset.name
    $Url = $Asset.browser_download_url
    [long]$ExpectedSize = $Asset.size
    $TempFile = "$OutFile.download"

    Write-Host "Downloading $Name ($(Format-Bytes $ExpectedSize))..." -ForegroundColor Cyan

    if (Test-Path -LiteralPath $TempFile) {
        Remove-Item -LiteralPath $TempFile -Force
    }

    $Response = $null
    $InputStream = $null
    $OutputStream = $null

    try {
        $Request = [System.Net.HttpWebRequest]::Create($Url)
        $Request.UserAgent = "yt-vd-installer"
        $Request.AllowAutoRedirect = $true
        $Request.Timeout = 300000
        $Request.ReadWriteTimeout = 300000

        $Response = $Request.GetResponse()
        [long]$TotalSize = $Response.ContentLength
        if ($TotalSize -le 0 -and $ExpectedSize -gt 0) {
            $TotalSize = $ExpectedSize
        }

        $InputStream = $Response.GetResponseStream()
        $OutputStream = [System.IO.File]::Open(
            $TempFile,
            [System.IO.FileMode]::Create,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )

        $Buffer = New-Object byte[] 131072
        [long]$Downloaded = 0
        $LastUpdate = Get-Date

        while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
            $OutputStream.Write($Buffer, 0, $Read)
            $Downloaded += $Read

            $Now = Get-Date
            if (($Now - $LastUpdate).TotalMilliseconds -ge 200 -or ($TotalSize -gt 0 -and $Downloaded -eq $TotalSize)) {
                if ($TotalSize -gt 0) {
                    $Percent = [Math]::Min(100, [Math]::Round(($Downloaded / $TotalSize) * 100))
                    $Status = "${Name}: $(Format-Bytes $Downloaded) / $(Format-Bytes $TotalSize)"
                    Write-Progress -Activity "Installing yt-vd" -Status $Status -PercentComplete $Percent
                } else {
                    Write-Progress -Activity "Installing yt-vd" -Status "${Name}: $(Format-Bytes $Downloaded)"
                }

                $LastUpdate = $Now
            }
        }
    } finally {
        if ($OutputStream) { $OutputStream.Dispose() }
        if ($InputStream) { $InputStream.Dispose() }
        if ($Response) { $Response.Dispose() }
        Write-Progress -Activity "Installing yt-vd" -Completed
    }

    $ActualSize = (Get-Item -LiteralPath $TempFile).Length
    if ($ExpectedSize -gt 0 -and $ActualSize -ne $ExpectedSize) {
        Remove-Item -LiteralPath $TempFile -Force
        throw "Downloaded $Name but the size did not match. Expected $(Format-Bytes $ExpectedSize), got $(Format-Bytes $ActualSize)."
    }

    if (Test-Path -LiteralPath $OutFile) {
        try {
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction Stop
        } catch {
            Write-Host "Warning: Target binary $OutFile is locked. Re-attempting process termination..." -ForegroundColor Yellow
            Get-Process -Name "yt-vd" -ErrorAction SilentlyContinue | Stop-Process -Force
            Start-Sleep -Seconds 1
            Remove-Item -LiteralPath $OutFile -Force
        }
    }

    Move-Item -LiteralPath $TempFile -Destination $OutFile -Force
    Write-Host "Saved $Name to $OutFile" -ForegroundColor Green
}

Write-Host "Installing yt-vd..." -ForegroundColor Cyan
Write-Host "Repository: https://github.com/$Repo"

# Retrieve local version before we overwrite it
$LocalVersion = $null
if (Test-Path -LiteralPath $Bin) {
    try {
        $VersionOutput = & $Bin --version 2>&1
        if ($VersionOutput -match "version\s+([v\d\.\-]+)") {
            $LocalVersion = $Matches[1]
        }
    } catch {
        # ignore
    }
}

Write-Host "Checking latest release..." -ForegroundColor Cyan
$Headers = @{ "User-Agent" = "yt-vd-installer" }
$Release = Invoke-RestMethod -Uri $ApiUrl -Headers $Headers
$RemoteVersion = $Release.tag_name
Write-Host "Found remote version: $RemoteVersion" -ForegroundColor Green

if ($LocalVersion) {
    Write-Host "Currently installed local version: $LocalVersion" -ForegroundColor Green
    if ($RemoteVersion -eq "latest") {
        Write-Host "Installing the latest release. Local version $LocalVersion will be updated if needed." -ForegroundColor Yellow
    } elseif ($LocalVersion -eq $RemoteVersion) {
        Write-Host "yt-vd is already at the latest version ($LocalVersion). Reinstalling to ensure a clean installation..." -ForegroundColor Yellow
    } else {
        Write-Host "Upgrading: $LocalVersion -> $RemoteVersion" -ForegroundColor Cyan
    }
} else {
    if ($RemoteVersion -eq "latest") {
        Write-Host "Installing the latest release..." -ForegroundColor Green
    } else {
        Write-Host "Installing version $RemoteVersion..." -ForegroundColor Green
    }
}

# Stop any running processes to prevent file locking
$RunningProcesses = Get-Process -Name "yt-vd" -ErrorAction SilentlyContinue
if ($RunningProcesses) {
    Write-Host "Stopping running yt-vd process(es) to allow overwrite..." -ForegroundColor Yellow
    foreach ($proc in $RunningProcesses) {
        try {
            Stop-Process -Id $proc.Id -Force
        } catch {}
    }
    Start-Sleep -Seconds 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

$CliAsset = Get-ReleaseAsset -Release $Release -Name "yt-vd.exe"

Download-Asset -Asset $CliAsset -OutFile $Bin

# Generate a local copy of the uninstaller script in the installation directory
$UninstallScriptPath = Join-Path $InstallDir "uninstall.ps1"
$UninstallScriptContent = @'
# Error handling and preference setup
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

$Repo = "alluses1033/yt-vd"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$UserAppDataDir = Join-Path $env:LOCALAPPDATA "yt-vd"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "           Uninstalling yt-vd            " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Kill any running yt-vd processes
$RunningProcesses = Get-Process -Name "yt-vd" -ErrorAction SilentlyContinue
if ($RunningProcesses) {
    Write-Host "Stopping running yt-vd processes..." -ForegroundColor Yellow
    foreach ($proc in $RunningProcesses) {
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            Write-Host "Stopped process: $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Green
        } catch {
            Write-Host "Warning: Failed to stop process $($proc.ProcessName): $_" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 1
}

# 2. Clean up AppData Local folders (config, history, database) to leave zero residue
if (Test-Path -LiteralPath $UserAppDataDir) {
    Write-Host "Removing configuration and history database at $UserAppDataDir..." -ForegroundColor Cyan
    try {
        Remove-Item -LiteralPath $UserAppDataDir -Recurse -Force -ErrorAction Stop
        Write-Host "Successfully deleted config and database directory." -ForegroundColor Green
    } catch {
        Write-Host "Warning: Failed to remove some config files: $_" -ForegroundColor Yellow
    }
}

# 3. Remove binary installation folder
if (Test-Path -LiteralPath $InstallDir) {
    Write-Host "Removing binary files at $InstallDir..." -ForegroundColor Cyan
    try {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction Stop
        Write-Host "Successfully deleted installation directory." -ForegroundColor Green
    } catch {
        Write-Host "Warning: Failed to remove installation directory completely: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "Installation directory not found: $InstallDir" -ForegroundColor Yellow
}

# 4. Remove installation path from User PATH variable
Write-Host "Cleaning up PATH environment variable..." -ForegroundColor Cyan
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath) {
    $Paths = $UserPath -split ";"
    $CleanPaths = $Paths | Where-Object { $_ -ne $InstallDir -and $_ -ne "$InstallDir\" -and [string]::IsNullOrWhiteSpace($_) -eq $false }
    $NewUserPath = $CleanPaths -join ";"
    
    if ($UserPath -ne $NewUserPath) {
        try {
            [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
            Write-Host "Removed $InstallDir from user PATH." -ForegroundColor Green
        } catch {
            Write-Host "Warning: Failed to update PATH environment variable: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Installation directory was not in User PATH." -ForegroundColor Yellow
    }
}

Write-Host "=========================================" -ForegroundColor Green
Write-Host " yt-vd has been successfully uninstalled. " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
'@

$UninstallScriptContent | Out-File -FilePath $UninstallScriptPath -Encoding utf8 -Force
Write-Host "Created uninstaller at $UninstallScriptPath" -ForegroundColor Green

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
