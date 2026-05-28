"""Entry point for yt-vd."""

import sys

# Force UTF-8 encoding for standard streams on Windows to prevent UnicodeEncodeError
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure verbose mode globally if requested
if "-v" in sys.argv or "--verbose" in sys.argv:
    import logging

    import core.ydl_options
    logging.basicConfig(level=logging.DEBUG)
    core.ydl_options.VERBOSE = True

from cli import app

if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        print("\n⚠ Interrupted — cleaning up...", file=sys.stderr)
        raise SystemExit(130)
