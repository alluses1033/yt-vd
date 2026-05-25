"""Shared yt-dlp option helpers."""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

_YOUTUBE_EXTRACTOR_ARGS: dict[str, dict[str, list[str]]] = {
    "youtube": {"player_client": ["default"]},
}

_SUPPRESSED_WARNING_PARTS = (
    "No supported JavaScript runtime could be found",
    "YouTube extraction without a JS runtime has been deprecated",
)


VERBOSE = False


class QuietYDLLogger:
    """Small yt-dlp logger that keeps known noisy warnings out of the UI."""

    def debug(self, msg: str) -> None:
        logger.debug(msg)

    def info(self, msg: str) -> None:
        logger.debug(msg)

    def warning(self, msg: str) -> None:
        if any(part in msg for part in _SUPPRESSED_WARNING_PARTS):
            logger.debug("Suppressed yt-dlp warning: %s", msg)
            return
        if VERBOSE:
            logger.warning(msg)
        else:
            logger.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        logger.error(msg)


_YDL_LOGGER = QuietYDLLogger()


def base_ydl_opts() -> dict[str, Any]:
    """Return defaults used by every yt-dlp call in the app."""
    return {
        "quiet": True,
        "no_warnings": True,
        "logger": _YDL_LOGGER,
        "extractor_args": copy.deepcopy(_YOUTUBE_EXTRACTOR_ARGS),
    }


def with_base_ydl_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Merge app-wide yt-dlp defaults with call-specific options."""
    merged = base_ydl_opts()
    extractor_args = merged.pop("extractor_args")

    custom = opts.copy()
    custom_extractor_args = custom.pop("extractor_args", {})

    merged.update(custom)
    merged["extractor_args"] = _merge_extractor_args(
        extractor_args,
        custom_extractor_args,
    )
    return merged


def _merge_extractor_args(
    base: dict[str, dict[str, Any]],
    extra: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = copy.deepcopy(base)
    for extractor, args in (extra or {}).items():
        merged.setdefault(extractor, {})
        merged[extractor].update(args)
    return merged
