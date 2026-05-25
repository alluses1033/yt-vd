@echo off
chcp 65001 >nul
REM =========================================
REM Build script for yt-vd (Windows)
REM Builds standalone executable for CLI
REM =========================================

echo =========================================
echo ^|   yt-vd Build Script (Windows)        ^|
echo =========================================

REM Check for uv
where uv >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] uv is not installed. Install it from https://docs.astral.sh/uv/
    exit /b 1
)

REM Install dependencies including dev
echo.
echo [*] Installing dependencies...
uv sync --all-groups

REM Check for ffmpeg
where ffmpeg >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] FFmpeg found
) else (
    echo [WARN] FFmpeg not found. Install via: winget install FFmpeg
)

REM Build executables
echo.
echo [*] Building executable...
uv run pyinstaller yt-vd.spec --clean --noconfirm

echo.
echo [OK] Build complete!
echo.
echo Executable is in dist\:
dir /b dist\yt-vd* 2>nul
echo.
echo Usage:
echo   dist\yt-vd.exe --help        # CLI
