"""ANSI terminal image renderer for yt-vd.

Downloads YouTube thumbnails and converts them to 24-bit ANSI color escape
sequences using unicode half-blocks for terminal rendering.
"""

from __future__ import annotations

import os
import tempfile
import urllib.request
import base64
from io import BytesIO
from pathlib import Path

from PIL import Image
from rich.segment import Segment


class TerminalImage:
    """Rich renderable for terminal images.
    
    Supports inline graphics protocols (Kitty, WezTerm/iTerm2) and fallbacks to
    standard ANSI unicode half-block sequences.
    """
    def __init__(self, raw_sequence: str, width: int, height: int, is_inline: bool = False):
        self.raw_sequence = raw_sequence
        self.width = width
        self.height = height
        self.is_inline = is_inline

    def __rich_console__(self, console, options):
        if self.is_inline:
            # For inline graphics, output escape code, then reserve height - 1 lines
            yield Segment(self.raw_sequence + "\n")
            for i in range(self.height - 1):
                yield Segment("\n" if i < self.height - 2 else "")
        else:
            # Yield ANSI SGR lines directly as segments
            lines = self.raw_sequence.split("\n")
            for i, line in enumerate(lines):
                yield Segment(line + ("\n" if i < len(lines) - 1 else ""))


def get_terminal_protocol() -> str | None:
    """Detect if the terminal program supports high-resolution graphics protocol."""
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    
    if "kitty" in term or "kitty" in term_program:
        return "kitty"
    
    if "wezterm" in term_program or "iterm" in term_program or "iterm2" in term_program:
        return "iterm2"
        
    return None


def _image_to_base64_png(img: Image.Image) -> str:
    """Convert PIL image to base64 encoded PNG string."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def get_ansi_thumbnail(url: str, width: int = 16, height: int = 6) -> TerminalImage | None:
    """Download thumbnail from URL and render it as a TerminalImage.

    Resizes the image and uses Kitty/WezTerm inline graphics or falls back to
    half-block characters (upper/lower pixels per char) to achieve vertical resolution.
    Cleans up temporary files immediately.

    Args:
        url: The thumbnail image URL.
        width: Number of character columns for the rendered image.
        height: Number of character rows for the rendered image.

    Returns:
        TerminalImage object, or None on failure.
    """
    if not url or not url.startswith("http"):
        return None

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
            
            # Detect terminal protocol
            protocol = get_terminal_protocol()
            
            if protocol:
                # Target pixel resolution based on typical font size (8x16) for crisp rendering
                pixel_width = width * 8
                pixel_height = height * 16
                resized_img = rgb_img.resize((pixel_width, pixel_height), Image.Resampling.LANCZOS)
                
                base64_data = _image_to_base64_png(resized_img)
                
                if protocol == "kitty":
                    escape_seq = f"\033_Ga=T,f=100,c={width},r={height};{base64_data}\033\\"
                else: # iterm2 (WezTerm, iTerm2, etc.)
                    escape_seq = f"\033]1337;File=inline=1;width={width};height={height};preserveAspectRatio=1:{base64_data}\a"
                
                return TerminalImage(escape_seq, width, height, is_inline=True)

            # Fallback: ANSI Unicode half-block characters
            # We need height * 2 because each char cell represents 2 vertical pixels
            resized_img = rgb_img.resize((width, height * 2), Image.Resampling.LANCZOS)

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

            return TerminalImage("\n".join(lines), width, height, is_inline=False)

    except Exception:
        # Fail silently and return None
        return None
    finally:
        # Clean up temp file immediately after loading
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
