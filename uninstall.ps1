# Error handling and preference setup
$ErrorActionPreference = "Stop"

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$UserAppDataDir = Join-Path $env:LOCALAPPDATA "yt-vd\yt-vd"
$ParentAppDataDir = Join-Path $env:LOCALAPPDATA "yt-vd"

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$IsInPath = if ($UserPath) { ($UserPath -split ";") -contains $InstallDir -or ($UserPath -split ";") -contains "$InstallDir\" } else { $false }

if (-not (Test-Path -LiteralPath $InstallDir) -and -not (Test-Path -LiteralPath $UserAppDataDir) -and -not $IsInPath) {
    Write-Host "yt-vd is not currently installed."
    Exit 0
}

Write-Host "========================================="
Write-Host "           Uninstalling yt-vd            "
Write-Host "========================================="

# 1. Kill any running processes of yt-vd or its gui (with retry)
for ($i = 0; $i -lt 5; $i++) {
    $RunningProcesses = Get-Process -Name "yt-vd", "yt-vd-gui" -ErrorAction SilentlyContinue
    if ($RunningProcesses) {
        Write-Host "Stopping running yt-vd processes..."
        foreach ($proc in $RunningProcesses) {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction Stop
                Write-Host "Stopped process: $($proc.ProcessName) (PID: $($proc.Id))"
            } catch {
                Write-Host "Warning: Failed to stop process $($proc.ProcessName): $_"
            }
        }
        Start-Sleep -Milliseconds 500
    } else {
        break
    }
}

# 2. Clean up AppData Local folders (config, history, database) to leave zero residue (with retry)
if (Test-Path -LiteralPath $UserAppDataDir) {
    Write-Host "Removing configuration and history database at $UserAppDataDir..."
    for ($i = 0; $i -lt 10; $i++) {
        try {
            Remove-Item -LiteralPath $UserAppDataDir -Recurse -Force -ErrorAction Stop
            Write-Host "Successfully deleted config and database directory."
            break
        } catch {
            if ($i -eq 9) {
                Write-Host "Warning: Failed to remove some config files: $_"
            } else {
                Start-Sleep -Milliseconds 500
            }
        }
    }
}
if (Test-Path -LiteralPath $ParentAppDataDir) {
    $Items = Get-ChildItem -LiteralPath $ParentAppDataDir -ErrorAction SilentlyContinue
    if (-not $Items) {
        try {
            Remove-Item -LiteralPath $ParentAppDataDir -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

# 3. Remove binary installation folder (with retry)
if (Test-Path -LiteralPath $InstallDir) {
    Write-Host "Removing binary files at $InstallDir..."
    for ($i = 0; $i -lt 10; $i++) {
        try {
            Get-Process -Name "yt-vd", "yt-vd-gui" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction Stop
            Write-Host "Successfully deleted installation directory."
            break
        } catch {
            if ($i -eq 9) {
                Write-Host "Warning: Failed to remove installation directory completely: $_"
            } else {
                Start-Sleep -Milliseconds 500
            }
        }
    }
} else {
    Write-Host "Installation directory not found: $InstallDir"
}

# 4. Remove installation path from User PATH variable
Write-Host "Cleaning up PATH environment variable..."
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath) {
    $Paths = $UserPath -split ";"
    # Exclude the install directory from the PATH list
    $CleanPaths = $Paths | Where-Object { $_ -ne $InstallDir -and $_ -ne "$InstallDir\" -and [string]::IsNullOrWhiteSpace($_) -eq $false }
    $NewUserPath = $CleanPaths -join ";"
    
    if ($UserPath -ne $NewUserPath) {
        try {
            [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            Write-Host "Removed $InstallDir from user PATH."
        } catch {
            Write-Host "Warning: Failed to update PATH environment variable: $_"
        }
    } else {
        Write-Host "Installation directory was not in User PATH."
    }
}

Write-Host "========================================="
Write-Host " yt-vd has been successfully uninstalled. "
Write-Host "========================================="
