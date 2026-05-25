# Error handling and preference setup
$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

$Repo = "alluses1033/yt-vd"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$UserAppDataDir = Join-Path $env:LOCALAPPDATA "yt-vd"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "           Uninstalling yt-vd            " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Kill any running processes of yt-vd or its gui
$RunningProcesses = Get-Process -Name "yt-vd", "yt-vd-gui" -ErrorAction SilentlyContinue
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
    # Exclude the install directory from the PATH list
    $CleanPaths = $Paths | Where-Object { $_ -ne $InstallDir -and $_ -ne "$InstallDir\" -and [string]::IsNullOrWhiteSpace($_) -eq $false }
    $NewUserPath = $CleanPaths -join ";"
    
    if ($UserPath -ne $NewUserPath) {
        try {
            [Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
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
