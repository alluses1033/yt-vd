"""ANSI terminal image renderer for yt-vd.

Downloads YouTube thumbnails and converts them to 24-bit ANSI color escape
sequences using unicode half-blocks for terminal rendering.
"""

from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image


def get_ansi_thumbnail(url: str, width: int = 16, height: int = 6) -> str:
    """Download thumbnail from URL and render it to ANSI escape sequences.

    Resizes the image and uses half-block characters (upper/lower pixels per char)
    to achieve double vertical resolution. Cleans up temporary files immediately.

    Args:
        url: The thumbnail image URL.
        width: Number of character columns for the rendered image.
        height: Number of character rows for the rendered image.

    Returns:
        ANSI escape sequence string, or empty string on failure.
    """
    if not url or not url.startswith("http"):
        return ""

    temp_file = None
    try:
        suffix = ".jpg"
        if ".png" in url.lower():
            suffix = ".png"

        # Create safe temp file
        fd, temp_path_str = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        temp_file = Path(temp_path_str)

        # Download thumbnail image
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            temp_file.write_bytes(response.read())

        # Load and render using Pillow
        with Image.open(temp_file) as raw_img:
            rgb_img = raw_img.convert("RGB")
            # We need height * 2 because each char cell represents 2 vertical pixels
            resized_img = rgb_img.resize((width, height * 2), Image.Resampling.BILINEAR)

            lines = []
            for y in range(0, height * 2, 2):
                line_parts = []
                for x in range(width):
                    pixel1 = resized_img.getpixel((x, y))
                    pixel2 = resized_img.getpixel((x, y + 1))

                    # MyPy needs type narrowing to unpack
                    if isinstance(pixel1, tuple) and isinstance(pixel2, tuple):
                        r1, g1, b1 = pixel1[:3]
                        r2, g2, b2 = pixel2[:3]
                    else:
                        r1 = g1 = b1 = 0
                        r2 = g2 = b2 = 0

                    # \033[38;2;R;G;Bm sets foreground (lower half block)
                    # \033[48;2;R;G;Bm sets background (upper half block)
                    # \u2584 is the lower half block character
                    part = f"\033[38;2;{r2};{g2};{b2};48;2;{r1};{g1};{b1}m\u2584"
                    line_parts.append(part)
                line_parts.append("\033[0m")  # reset style
                lines.append("".join(line_parts))

            return "\n".join(lines)

    except Exception:
        # Fail silently and return empty string
        return ""
    finally:
        # Clean up temp file immediately after loading
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
