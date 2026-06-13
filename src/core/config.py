"""Configuration management for yt-vd.

Thread-safe singleton that loads/saves settings from a TOML config file
located in the platform-appropriate user config directory.
"""

from __future__ import annotations

import logging
import threading
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import platformdirs

from constants import (
    APP_AUTHOR,
    APP_NAME,
    CONFIG_FILE_NAME,
    DEFAULT_PARALLEL_WORKERS,
    AudioBitrate,
    AudioFormat,
    QualityPreset,
    VideoFormat,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Default Configuration Values
# ──────────────────────────────────────────────

@dataclass(slots=True)
class AppConfig:
    """Application configuration with sensible defaults."""

    output_dir: str = field(default_factory=lambda: str(Path.home() / "Downloads" / "yt-vd"))
    quality: str = QualityPreset.BEST
    format: str = VideoFormat.MP4
    parallel_workers: int = DEFAULT_PARALLEL_WORKERS
    audio_format: str = AudioFormat.MP3
    audio_bitrate: str = AudioBitrate.BEST
    subtitle_lang: str = "en"
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    sponsorblock: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Create config from a dictionary, ignoring unknown keys."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


# ──────────────────────────────────────────────
# TOML Serializer (manual — avoids extra deps)
# ──────────────────────────────────────────────

def _toml_value(value: Any) -> str:
    """Serialize a single Python value to TOML literal."""
    match value:
        case bool():
            return "true" if value else "false"
        case int():
            return str(value)
        case float():
            return str(value)
        case str():
            # Escape backslashes and quotes for TOML
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        case _:
            return f'"{value}"'


def _write_toml(data: dict[str, Any]) -> str:
    """Serialize a flat dictionary to TOML format."""
    lines: list[str] = [
        "# yt-vd configuration file",
        "# Edit values below to change default behavior.",
        "",
    ]
    for key, value in data.items():
        lines.append(f"{key} = {_toml_value(value)}")
    lines.append("")  # trailing newline
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Config Manager (Thread-Safe Singleton)
# ──────────────────────────────────────────────

class ConfigManager:
    """Thread-safe singleton configuration manager.

    Usage::

        config = ConfigManager.get_instance()
        print(config.current.output_dir)
        config.update(quality="high")
    """

    _instance: ConfigManager | None = None
    _init_lock: threading.Lock = threading.Lock()

    _lock: threading.Lock
    _config: AppConfig
    _config_path: Path
    _loaded: bool

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            with cls._init_lock:
                # Double-checked locking
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._lock = threading.Lock()
                    instance._config = AppConfig()
                    instance._config_path = cls._resolve_config_path()
                    instance._loaded = False
                    cls._instance = instance
        assert cls._instance is not None
        return cls._instance

    @classmethod
    def get_instance(cls) -> ConfigManager:
        """Get or create the singleton ConfigManager instance."""
        return cls()

    @classmethod
    def _resolve_config_path(cls) -> Path:
        """Determine the config file path using platformdirs."""
        config_dir = Path(platformdirs.user_config_dir(APP_NAME, APP_AUTHOR))
        return config_dir / CONFIG_FILE_NAME

    @property
    def config_path(self) -> Path:
        """Path to the config file on disk."""
        return self._config_path

    @property
    def current(self) -> AppConfig:
        """Get the current configuration, loading from disk on first access."""
        if not self._loaded:
            self.load()
        return self._config

    def load(self) -> AppConfig:
        """Load configuration from the TOML file on disk.

        If the file doesn't exist, creates it with default values.
        If the file is invalid, falls back to defaults and overwrites.

        Returns:
            The loaded (or default) AppConfig.
        """
        with self._lock:
            if not self._config_path.exists():
                logger.info("Config file not found — creating defaults at %s", self._config_path)
                self._config = AppConfig()
                self._save_locked()
                self._loaded = True
                return self._config

            try:
                raw = self._config_path.read_text(encoding="utf-8")
                data = tomllib.loads(raw)
                self._config = AppConfig.from_dict(data)
                logger.info("Configuration loaded from %s", self._config_path)
            except Exception:
                logger.exception("Failed to parse config file — resetting to defaults")
                self._config = AppConfig()
                self._save_locked()

            self._loaded = True
            return self._config

    def save(self) -> None:
        """Persist the current configuration to disk."""
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        """Internal save — must be called while holding ``self._lock``."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        content = _write_toml(self._config.to_dict())
        import os
        import tempfile
        temp_fd, temp_file_path = tempfile.mkstemp(
            dir=self._config_path.parent,
            prefix=".config_temp_",
            suffix=".toml"
        )
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                f.write(content)
            os.replace(temp_file_path, self._config_path)
        except Exception:
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
            raise
        logger.debug("Configuration saved to %s", self._config_path)

    def update(self, **kwargs: Any) -> AppConfig:
        """Update one or more config values and persist.

        Args:
            **kwargs: Config field names and their new values.

        Returns:
            The updated AppConfig.

        Raises:
            AttributeError: If an unknown config key is provided.
        """
        with self._lock:
            for key, value in kwargs.items():
                if not hasattr(self._config, key):
                    raise AttributeError(f"Unknown config key: {key!r}")
                setattr(self._config, key, value)
            self._save_locked()
            return self._config

    def reset(self) -> AppConfig:
        """Reset all settings to defaults and persist."""
        with self._lock:
            self._config = AppConfig()
            self._save_locked()
            return self._config

    @classmethod
    def _reset_singleton(cls) -> None:
        """Reset the singleton instance (for testing only)."""
        with cls._init_lock:
            cls._instance = None


# ──────────────────────────────────────────────
# Global Configuration Helpers
# ──────────────────────────────────────────────

def load_config() -> dict[str, Any]:
    """Helper for GUI settings loading to retrieve configuration dictionary."""
    data = ConfigManager.get_instance().current.to_dict()
    if "subtitle_lang" in data:
        data["subtitle_language"] = data.pop("subtitle_lang")
    return data


def save_config(config_dict: dict[str, Any]) -> None:
    """Helper for GUI settings saving to persist settings from dictionary."""
    manager = ConfigManager.get_instance()
    data = dict(config_dict)
    if "subtitle_language" in data:
        data["subtitle_lang"] = data.pop("subtitle_language")
    manager.update(**data)
