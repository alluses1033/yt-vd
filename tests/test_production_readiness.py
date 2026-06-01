import os
import time
from pathlib import Path

from constants import TEMP_DIR_NAME
from core.fragment_safety import SafeDownloadManager, cleanup_orphaned_temp_dirs


def _age_tree(path: Path, seconds_old: int) -> None:
    timestamp = time.time() - seconds_old
    for child in path.rglob("*"):
        os.utime(child, (timestamp, timestamp))
    os.utime(path, (timestamp, timestamp))


def test_cleanup_orphaned_temp_dirs_removes_only_stale_entries(tmp_path):
    temp_root = tmp_path / TEMP_DIR_NAME
    old_dir = temp_root / "vid_old"
    recent_dir = temp_root / "vid_recent"
    old_dir.mkdir(parents=True)
    recent_dir.mkdir(parents=True)
    (old_dir / "partial.mp4").write_text("old residue", encoding="utf-8")
    (recent_dir / "partial.part").write_text("active-ish residue", encoding="utf-8")
    _age_tree(old_dir, seconds_old=2 * 60 * 60)

    removed = cleanup_orphaned_temp_dirs(tmp_path, max_age_seconds=60 * 60)

    assert removed == 1
    assert not old_dir.exists()
    assert recent_dir.exists()


def test_safe_download_setup_sweeps_old_orphaned_temp_dirs(tmp_path):
    temp_root = tmp_path / TEMP_DIR_NAME
    old_dir = temp_root / "vid_abandoned"
    old_dir.mkdir(parents=True)
    (old_dir / "download.part").write_text("stale data", encoding="utf-8")
    _age_tree(old_dir, seconds_old=2 * 24 * 60 * 60)

    current_temp = SafeDownloadManager(tmp_path, video_id="current").setup()

    assert current_temp.exists()
    assert not old_dir.exists()


def test_installers_download_before_replacing_existing_binary():
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    install_ps1 = Path("install.ps1").read_text(encoding="utf-8")

    assert 'rm -f "$install_dir/yt-vd"' not in install_sh
    assert "mktemp -d" in install_sh
    assert "trap cleanup EXIT HUP INT TERM" in install_sh
    assert 'mv -f "$tmp_bin" "${install_dir}/yt-vd"' in install_sh

    assert "Remove-ExistingInstallation" not in install_ps1
    assert "Downloaded size mismatch" in install_ps1
    assert "Move-Item -LiteralPath $Bin -Destination $BackupBin -Force" in install_ps1
    assert "Move-Item -LiteralPath $TempBin -Destination $Bin -Force" in install_ps1
