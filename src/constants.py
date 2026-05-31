"""Constants and configuration defaults for yt-vd."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# ──────────────────────────────────────────────
# Shared Regex Patterns
# ──────────────────────────────────────────────

# Precompiled YouTube video ID extraction — shared by all modules
VIDEO_ID_PATTERN = re.compile(
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/watch\?v=|/)([a-zA-Z0-9_-]{11})"
)

# ──────────────────────────────────────────────
# Quality Presets
# ──────────────────────────────────────────────

class QualityPreset(StrEnum):
    """Named quality presets mapping to resolution caps."""
    BEST = "best"
    HIGH = "high"        # 1080p
    MEDIUM = "medium"    # 720p
    BETTER = "better"    # 480p
    LOW = "low"          # 360p
    LOWEST = "lowest"    # 240p


# Maps preset names to yt-dlp format strings with automatic fallback
QUALITY_FORMAT_MAP: dict[str, str] = {
    QualityPreset.BEST: "bestvideo+bestaudio/best",
    QualityPreset.HIGH: "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best",
    QualityPreset.MEDIUM: "bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best",
    QualityPreset.BETTER: "bestvideo[height<=480]+bestaudio/bestvideo+bestaudio/best",
    QualityPreset.LOW: "bestvideo[height<=360]+bestaudio/bestvideo+bestaudio/best",
    QualityPreset.LOWEST: "bestvideo[height<=240]+bestaudio/bestvideo+bestaudio/best",
}

# Direct resolution to yt-dlp format string (with fallback appended)
RESOLUTION_FORMAT_MAP: dict[str, str] = {
    "2160p": "bestvideo[height<=2160]+bestaudio/bestvideo+bestaudio/best",
    "1440p": "bestvideo[height<=1440]+bestaudio/bestvideo+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best",
    "720p": "bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best",
    "480p": "bestvideo[height<=480]+bestaudio/bestvideo+bestaudio/best",
    "360p": "bestvideo[height<=360]+bestaudio/bestvideo+bestaudio/best",
    "240p": "bestvideo[height<=240]+bestaudio/bestvideo+bestaudio/best",
    "144p": "bestvideo[height<=144]+bestaudio/bestvideo+bestaudio/best",
}


# ──────────────────────────────────────────────
# Audio Formats & Bitrates
# ──────────────────────────────────────────────

class AudioFormat(StrEnum):
    MP3 = "mp3"
    M4A = "m4a"
    FLAC = "flac"
    WAV = "wav"
    OPUS = "opus"


class AudioBitrate(StrEnum):
    LOW = "128k"
    MEDIUM = "192k"
    HIGH = "256k"
    BEST = "320k"

AUDIO_BITRATE_MAP: dict[str, int] = {
    "128k": 128,
    "192k": 192,
    "256k": 256,
    "320k": 320,
}


# ──────────────────────────────────────────────
# Subtitle Formats
# ──────────────────────────────────────────────

class SubtitleFormat(StrEnum):
    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"


# ──────────────────────────────────────────────
# Output Formats
# ──────────────────────────────────────────────

class VideoFormat(StrEnum):
    MP4 = "mp4"
    MKV = "mkv"
    WEBM = "webm"


# ──────────────────────────────────────────────
# Parallelism
# ──────────────────────────────────────────────

# Default parallel workers = CPU count, capped at 8
MAX_PARALLEL_CAP = 8
DEFAULT_PARALLEL_WORKERS = min(os.cpu_count() or 4, MAX_PARALLEL_CAP)
DEFAULT_FRAGMENT_THREADS = 4

# ──────────────────────────────────────────────
# Retry & Network
# ──────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2.0  # seconds: 2, 4, 8
SOCKET_TIMEOUT = 30  # seconds
DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB

# ──────────────────────────────────────────────
# File Patterns
# ──────────────────────────────────────────────

# Output template for single videos
SINGLE_VIDEO_TEMPLATE = "%(title)s.%(ext)s"


# Temp directory name for fragment assembly
TEMP_DIR_NAME = ".yt-vd-temp"

# ──────────────────────────────────────────────
# App Paths
# ──────────────────────────────────────────────

APP_NAME = "yt-vd"
APP_AUTHOR = "yt-vd"

# History database filename
HISTORY_DB_NAME = "download_history.db"

# Config filename
CONFIG_FILE_NAME = "config.toml"

# ──────────────────────────────────────────────
# URL Patterns
# ──────────────────────────────────────────────

YOUTUBE_URL_PATTERNS = [
    r"(?:https?://)?(?:www\.)?youtube\.com/watch\?(?:[^&]+&)*v=[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?(?:[^&]+&)*list=[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/@[\w.-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/channel/[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/c/[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/user/[\w-]+",
    r"(?:https?://)?youtu\.be/[\w-]+",
]

# ──────────────────────────────────────────────
# Download Status
# ──────────────────────────────────────────────

class DownloadStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ──────────────────────────────────────────────
# Download Result Data Structure
# ──────────────────────────────────────────────

@dataclass(slots=True)
class DownloadResult:
    """Result of a single download operation."""
    url: str
    title: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    file_path: Path | None = None
    file_size: int = 0
    quality: str = ""
    format: str = ""
    duration: float = 0.0
    error_message: str = ""
    elapsed_seconds: float = 0.0


@dataclass(slots=True)
class PlaylistInfo:
    """Metadata for a YouTube playlist."""
    title: str
    uploader: str
    url: str
    video_count: int
    entries: list[dict] = field(default_factory=list)
    description: str = ""
    total_duration: float = 0.0


@dataclass(slots=True)
class VideoInfo:
    """Metadata for a single YouTube video."""
    title: str
    url: str
    video_id: str
    uploader: str
    duration: float
    view_count: int
    upload_date: str
    description: str = ""
    thumbnail_url: str = ""
    formats: list[dict] = field(default_factory=list)
    available_qualities: list[str] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)
    subtitles: dict = field(default_factory=dict)
    file_size_approx: int = 0


@dataclass(slots=True)
class ProgressInfo:
    """Real-time progress information for a download."""
    video_id: str = ""
    title: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0  # bytes per second
    eta: float = 0.0  # seconds remaining
    percent: float = 0.0
    fragment_index: int = 0
    fragment_count: int = 0
    elapsed: float = 0.0

    @property
    def speed_str(self) -> str:
        """Human-readable download speed."""
        if self.speed <= 0:
            return "-- B/s"
        units = [("GB/s", 1e9), ("MB/s", 1e6), ("KB/s", 1e3), ("B/s", 1)]
        for unit, threshold in units:
            if self.speed >= threshold:
                return f"{self.speed / threshold:.1f} {unit}"
        return f"{self.speed:.0f} B/s"

    @property
    def eta_str(self) -> str:
        """Human-readable ETA."""
        if self.eta <= 0:
            return "--:--"
        minutes, seconds = divmod(int(self.eta), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def size_str(self) -> str:
        """Human-readable downloaded / total size."""
        def _fmt(b: int) -> str:
            if b <= 0:
                return "-- MB"
            if b >= 1e9:
                return f"{b / 1e9:.1f} GB"
            if b >= 1e6:
                return f"{b / 1e6:.1f} MB"
            if b >= 1e3:
                return f"{b / 1e3:.1f} KB"
            return f"{b} B"
        return f"{_fmt(self.downloaded_bytes)} / {_fmt(self.total_bytes)}"
