"""Fragment integrity protection for yt-vd.

Downloads are performed in a temporary directory and only moved to their
final destination after integrity verification.  Supports resume via
.part files and provides cleanup utilities.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from constants import TEMP_DIR_NAME

logger = logging.getLogger(__name__)

# Minimum valid file size (bytes) — anything smaller is likely corrupted
_MIN_VALID_SIZE = 1024  # 1 KiB

# Magic bytes for container format validation
_CONTAINER_SIGNATURES: dict[str, list[bytes]] = {
    ".mp4": [b"ftyp"],          # ISO Base Media — ftyp box at bytes 4-8
    ".mkv": [b"\x1a\x45\xdf\xa3"],  # Matroska / EBML header
    ".webm": [b"\x1a\x45\xdf\xa3"],  # WebM uses same EBML header
    ".mp3": [b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"ID3"],
    ".m4a": [b"ftyp"],          # ISO Base Media — ftyp box at bytes 4-8
    ".flac": [b"fLaC"],
    ".wav": [b"RIFF"],
    ".opus": [b"OggS"],
    ".ogg": [b"OggS"],
    ".srt": [],  # text format — no magic bytes
    ".vtt": [],  # text format — no magic bytes
    ".ass": [],  # text format — no magic bytes
}


class SafeDownloadManager:
    """Manages safe downloads through a temp directory.

    Files are downloaded into a temp directory, verified for integrity,
    then atomically moved to the final output location.

    Args:
        output_dir: The final destination directory for completed downloads.
    """

    __slots__ = ("_output_dir", "_temp_dir")

    def __init__(self, output_dir: str | Path, video_id: str | None = None) -> None:
        self._output_dir = Path(output_dir)
        if video_id:
            self._temp_dir = self._output_dir / TEMP_DIR_NAME / f"vid_{video_id}"
        else:
            self._temp_dir = self._output_dir / TEMP_DIR_NAME

    @property
    def output_dir(self) -> Path:
        """The final output directory."""
        return self._output_dir

    @property
    def temp_dir(self) -> Path:
        """The temporary download directory."""
        return self._temp_dir

    def setup(self) -> Path:
        """Create the temp directory and return its path.

        Returns:
            Path to the temporary download directory.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

        # Hide the .yt-vd-temp folder on Windows
        if self._temp_dir.name == TEMP_DIR_NAME:
            _hide_folder(self._temp_dir)
        elif self._temp_dir.parent.name == TEMP_DIR_NAME:
            _hide_folder(self._temp_dir.parent)

        return self._temp_dir

    def get_ydl_paths(self) -> dict[str, Any]:
        """Get yt-dlp-compatible path configuration.

        Returns a dict suitable for merging into yt-dlp options that
        directs downloads to the temp directory.

        Returns:
            Dict with ``'paths'`` key containing temp/home dir mapping.
        """
        self.setup()
        return {
            "paths": {
                "temp": str(self._temp_dir),
                "home": str(self._temp_dir),
            }
        }

    def move_to_final(self, temp_file: Path, final_name: str | None = None) -> Path:
        """Move a verified file from temp to the final output directory.

        Args:
            temp_file: Path to the file in the temp directory.
            final_name: Optional rename for the final file.  If ``None``,
                        the original filename is used.

        Returns:
            Path to the file in its final location.

        Raises:
            FileNotFoundError: If the temp file doesn't exist.
        """
        if not temp_file.exists():
            raise FileNotFoundError(f"Temp file not found: {temp_file}")

        dest_name = final_name or temp_file.name
        final_path = self._output_dir / dest_name

        try:
            if temp_file.resolve() == final_path.resolve():
                logger.debug("File is already at destination: %s", final_path)
                return final_path
        except Exception:
            pass

        # Avoid overwriting — append number suffix if needed
        if final_path.exists():
            stem = final_path.stem
            suffix = final_path.suffix
            counter = 1
            while final_path.exists():
                final_path = self._output_dir / f"{stem} ({counter}){suffix}"
                counter += 1

        shutil.move(str(temp_file), str(final_path))
        logger.info("Moved %s → %s", temp_file.name, final_path)
        return final_path

    def cleanup_temp(self, force: bool = False) -> None:
        """Remove the temp directory and all its contents.

        Only removes the temp directory; the output directory is preserved.
        If ``force`` is True, all files including .part files are deleted.
        """
        cleanup_temp(self._temp_dir, force=force)


# ──────────────────────────────────────────────
# Module-Level Functions
# ──────────────────────────────────────────────

def _hide_folder(path: Path) -> None:
    """Set the hidden attribute on a folder (Windows only)."""
    import os
    if os.name == "nt":
        import ctypes
        file_attribute_hidden = 0x02
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), file_attribute_hidden)
        except Exception:
            pass


def verify_file_integrity(filepath: str | Path) -> bool:
    """Verify that a downloaded file is not corrupted.

    Performs the following checks:
    1. File exists
    2. File size is above minimum threshold
    3. File has valid container magic bytes (if the extension is recognised)

    Args:
        filepath: Path to the file to verify.

    Returns:
        True if the file passes all integrity checks.
    """
    path = Path(filepath)

    # 1. Existence check
    if not path.exists():
        logger.warning("Integrity check failed — file does not exist: %s", path)
        return False

    # 2. Size check
    file_size = path.stat().st_size
    if file_size < _MIN_VALID_SIZE:
        logger.warning(
            "Integrity check failed — file too small (%d bytes): %s",
            file_size,
            path,
        )
        return False

    # 3. Magic bytes / container check
    suffix = path.suffix.lower()
    if suffix in _CONTAINER_SIGNATURES:
        signatures = _CONTAINER_SIGNATURES[suffix]
        if signatures:  # text formats have empty sig lists — skip
            if not _check_magic_bytes(path, signatures):
                logger.warning(
                    "Integrity check failed — invalid container signature: %s",
                    path,
                )
                return False

    logger.debug("Integrity check passed: %s (%d bytes)", path, file_size)
    return True


def cleanup_temp(temp_dir: str | Path, force: bool = False) -> None:
    """Remove temporary download files, preserving .part files for resume unless forced.

    Args:
        temp_dir: Path to the temp directory to clean.
        force: If True, delete all files including .part files.
    """
    temp_path = Path(temp_dir)
    if not temp_path.exists():
        return

    part_files: list[Path] = []
    import time

    # Helper to delete file with retries (handles Windows / antivirus locks)
    def _delete_file_with_retry(file_path: Path) -> bool:
        for i in range(5):
            try:
                file_path.unlink()
                return True
            except OSError:
                time.sleep(0.1)
        return False

    # Helper to delete dir with retries
    def _delete_dir_with_retry(dir_path: Path) -> bool:
        for i in range(5):
            try:
                shutil.rmtree(dir_path)
                return True
            except OSError:
                time.sleep(0.1)
        return False

    for item in temp_path.iterdir():
        if item.is_file():
            if not force and item.suffix == ".part":
                part_files.append(item)
                logger.debug("Preserving .part file for resume: %s", item.name)
            else:
                if not _delete_file_with_retry(item):
                    logger.warning("Failed to remove temp file %s after retries", item.name)
        elif item.is_dir():
            if not _delete_dir_with_retry(item):
                logger.warning("Failed to remove temp dir %s after retries", item.name)

    # Remove the temp dir itself only if empty (no .part files left)
    if not part_files:
        for i in range(5):
            try:
                temp_path.rmdir()
                logger.debug("Removed temp directory: %s", temp_path)
                break
            except OSError:
                time.sleep(0.1)

        # Try to remove parent .yt-vd-temp if it's empty
        parent = temp_path.parent
        if parent.name == TEMP_DIR_NAME:
            for i in range(5):
                try:
                    parent.rmdir()
                    logger.debug("Removed parent temp directory: %s", parent)
                    break
                except OSError:
                    time.sleep(0.1)


# ──────────────────────────────────────────────
# Internal Helpers
# ──────────────────────────────────────────────

def _check_magic_bytes(filepath: Path, signatures: list[bytes]) -> bool:
    """Check if a file starts with one of the expected magic byte sequences.

    For ISO BMFF (MP4/M4A), also looks for the ``ftyp`` box identifier
    within the first 12 bytes.

    Args:
        filepath: The file to check.
        signatures: List of valid magic byte prefixes.

    Returns:
        True if any signature matches.
    """
    try:
        with open(filepath, "rb") as f:
            header = f.read(32)
    except OSError:
        return False

    if len(header) < 4:
        return False

    for sig in signatures:
        if sig == b"ftyp":
            # ISO BMFF: the ftyp atom type appears at byte offset 4
            # First 4 bytes are the box size, next 4 are "ftyp"
            if len(header) >= 8 and header[4:8] == b"ftyp":
                return True
        elif header.startswith(sig):
            return True

    return False
