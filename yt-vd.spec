# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for yt-vd.

Builds CLI executable.
Usage:
    uv run pyinstaller yt-vd.spec
"""

import sys
from pathlib import Path

block_cipher = None
src_dir = Path("src")

# ──────────────────────────────────────────────
# CLI Executable
# ──────────────────────────────────────────────

cli_analysis = Analysis(
    [str(src_dir / "__main__.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "yt_dlp",
        "typer",
        "rich",
        "questionary",
        "platformdirs",
        "core.config",
        "core.utils",
        "core.quality",
        "core.progress",
        "core.fragment_safety",
        "core.downloader",
        "core.parallel",
        "core.playlist",
        "core.audio",
        "core.subtitles",
        "core.metadata",
        "core.search",
        "core.history",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["customtkinter", "tkinter", "PIL"],  # Exclude GUI deps from CLI build
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data, cipher=block_cipher)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    cli_analysis.binaries,
    cli_analysis.zipfiles,
    cli_analysis.datas,
    [],
    name="yt-vd",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)


