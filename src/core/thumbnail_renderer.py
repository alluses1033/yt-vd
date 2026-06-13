"""Terminal image renderer for yt-vd.

Downloads YouTube thumbnails and converts them to terminal graphics using
the best available protocol: Kitty, iTerm2/WezTerm, Sixel (Windows Terminal,
foot, mlterm, mintty), or ANSI unicode half-blocks as a universal fallback.
"""

from __future__ import annotations

import base64
import os
import re
import threading
import time
import urllib.request
from io import BytesIO
from typing import cast
from urllib.parse import urlparse

from PIL import Image, ImageEnhance, ImageFilter
from rich.segment import Segment


class ControlSegment(Segment):
    """Segment with cell length of zero, used to output raw escape sequences."""
    @property
    def cell_length(self) -> int:
        return 0

class TerminalImage:
    """Rich renderable for terminal images.

    Supports inline graphics protocols (Kitty, WezTerm/iTerm2, Sixel) and
    fallbacks to standard ANSI unicode half-block sequences.
    """
    def __init__(self, raw_sequence: str, width: int, height: int, is_inline: bool = False):
        self.raw_sequence = raw_sequence
        self.width = width
        self.height = height
        self.is_inline = is_inline

    def __rich_console__(self, console, options):
        if self.is_inline:
            # Yield empty lines to reserve space for the image in the table
            for i in range(self.height - 1):
                yield Segment(" " * self.width)
                yield Segment("\n")

            # On the last line, yield spaces, then the image sequence
            yield Segment(" " * self.width)

            # Now the cursor is at the bottom-right of the cell.
            # We want to move to the top-left of the cell to draw the image.
            # This ensures the image is drawn *after* Rich prints the spaces,
            # so the spaces don't overwrite the image pixels (critical for Sixel).
            move_up = f"\033[{self.height - 1}A" if self.height > 1 else ""
            move_left = f"\033[{self.width}D" if self.width > 0 else ""

            # We wrap the sequence in VT100 save/restore cursor codes
            yield ControlSegment(f"\0337{move_left}{move_up}{self.raw_sequence}\0338")
        else:
            # For fallback ANSI blocks, we delegate to Text.from_ansi, which parses them and handles layout perfectly!
            from rich.text import Text
            yield from Text.from_ansi(self.raw_sequence).__rich_console__(console, options)

_cell_size_lock = threading.Lock()
_cached_cell_size: tuple[int, int] | None = None
_cell_size_queried = False

def _parse_cell_size_response(response: bytes) -> tuple[int, int] | None:
    """Parse a CSI 16 t terminal cell-size response as (width, height)."""
    match = re.search(r"\x1b\[6;(\d+);(\d+)t", response.decode("ascii", errors="ignore"))
    if not match:
        return None

    height = int(match.group(1))
    width = int(match.group(2))
    if width > 0 and height > 0:
        return width, height
    return None

def _enable_vt_mode_windows() -> None:
    """Enable Virtual Terminal Input and Processing on Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
        h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode_in = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode_in)):
            kernel32.SetConsoleMode(h_stdin, mode_in.value | 0x0200)

        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        h_stdout = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode_out = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode_out)):
            kernel32.SetConsoleMode(h_stdout, mode_out.value | 0x0004)
    except Exception:
        pass

def _drain_pending_terminal_input() -> None:
    """Discard already-buffered terminal input before sending a fresh query."""
    import sys

    if os.name == "nt":
        import msvcrt

        while msvcrt.kbhit():  # type: ignore[attr-defined]
            msvcrt.getch()  # type: ignore[attr-defined]
        return

    import select

    try:
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0.0)[0]:
            os.read(fd, 1)
    except Exception:
        try:
            while select.select([sys.stdin], [], [], 0.0)[0]:
                sys.stdin.read(1)
        except Exception:
            pass


def _read_vt_sequence_unix(query: str, end_char: bytes, timeout: float = 0.4) -> bytes:
    """Send a VT query and read the response in raw mode on Unix/Linux."""
    import sys

    if os.name == "nt":
        return b""

    try:
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore[attr-defined]
        has_termios = True
    except Exception:
        has_termios = False

    if has_termios:
        try:
            # Set raw mode to disable echo and line buffering
            tty.setraw(fd)  # type: ignore[attr-defined]

            # Drain any pending input at OS level while in raw mode
            while select.select([fd], [], [], 0.0)[0]:
                os.read(fd, 1)

            # Send query
            sys.stdout.write(query)
            sys.stdout.flush()

            response = b""
            start_time = time.monotonic()
            while time.monotonic() - start_time < timeout:
                r, _, _ = select.select([fd], [], [], timeout - (time.monotonic() - start_time))
                if r:
                    char = os.read(fd, 1)
                    if not char:
                        break
                    response += char
                    if response.endswith(end_char):
                        break
                else:
                    break
            return response
        except Exception:
            return b""
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore[attr-defined]
            except Exception:
                pass
    else:
        # Fallback for non-TTY or mock/test environment
        try:
            sys.stdout.write(query)
            sys.stdout.flush()
        except Exception:
            pass

        response = b""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            try:
                r, _, _ = select.select([sys.stdin], [], [], timeout - (time.monotonic() - start_time))
                if r:
                    char_str = sys.stdin.read(1)
                    if not char_str:
                        break
                    response += char_str.encode("utf-8", errors="ignore")
                    if response.endswith(end_char):
                        break
                else:
                    break
            except Exception:
                break
        return response


def query_terminal_cell_size() -> tuple[int, int] | None:
    """Query the terminal for the character cell size in pixels.

    Sends the CSI 16 t escape sequence and reads the response.
    Returns (width, height) in pixels, or None on failure/timeout.
    """
    import sys
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        return None

    try:
        _enable_vt_mode_windows()
        _drain_pending_terminal_input()

        if os.name == "nt":
            # Send CSI 16 t
            sys.stdout.write("\033[16t")
            sys.stdout.flush()

            response = b""
            start_time = time.monotonic()
            timeout = 0.4  # Slightly longer timeout for Windows conhost compatibility
            import msvcrt

            # Read response
            while time.monotonic() - start_time < timeout:
                if msvcrt.kbhit():  # type: ignore[attr-defined]
                    response += msvcrt.getch()  # type: ignore[attr-defined]
                    if response.endswith(b"t"):
                        break
                else:
                    time.sleep(0.002)
        else:
            response = _read_vt_sequence_unix("\033[16t", b"t", timeout=0.4)

        return _parse_cell_size_response(response)
    except Exception:
        pass
    return None


def get_cached_cell_size() -> tuple[int, int] | None:
    """Query and cache the terminal cell size in pixels thread-safely."""
    global _cached_cell_size, _cell_size_queried
    with _cell_size_lock:
        if not _cell_size_queried:
            _cached_cell_size = query_terminal_cell_size()
            _cell_size_queried = True
        return _cached_cell_size

_sixel_support_lock = threading.Lock()
_cached_sixel_support: bool | None = None
_sixel_support_queried = False

def _query_sixel_support() -> bool:
    """Query the terminal's Primary Device Attributes (DA1) to check for Sixel support.

    Sends ``CSI c`` and looks for ``4`` in the returned attribute list
    (``ESC [ ? 6 2 ; 4 ; ... c`` indicates Sixel graphics support, attribute 4).
    This is far more reliable than guessing from ``$TERM``/``$TERM_PROGRAM``,
    which causes garbled "pixelled" output on terminals that report a
    Sixel-ish TERM value but don't actually implement the protocol.
    """
    import sys

    if not sys.stdout.isatty() or not sys.stdin.isatty():
        return False

    try:
        _enable_vt_mode_windows()
        _drain_pending_terminal_input()

        if os.name == "nt":
            sys.stdout.write("\033[c")
            sys.stdout.flush()

            response = b""
            start_time = time.monotonic()
            timeout = 0.4  # Slightly longer timeout for Windows conhost compatibility
            import msvcrt

            while time.monotonic() - start_time < timeout:
                if msvcrt.kbhit():  # type: ignore[attr-defined]
                    response += msvcrt.getch()  # type: ignore[attr-defined]
                    if response.endswith(b"c"):
                        break
                else:
                    time.sleep(0.002)
        else:
            response = _read_vt_sequence_unix("\033[c", b"c", timeout=0.4)

        decoded = response.decode("ascii", errors="ignore")
        match = re.search(r"\x1b\[\?(\d+(?:;\d+)*)c", decoded)
        if not match:
            return False
        attrs = match.group(1).split(";")
        return "4" in attrs
    except Exception:
        return False

def get_cached_sixel_support() -> bool:
    """Query and cache whether the terminal supports Sixel graphics, thread-safely."""
    global _cached_sixel_support, _sixel_support_queried
    with _sixel_support_lock:
        if not _sixel_support_queried:
            _cached_sixel_support = _query_sixel_support()
            _sixel_support_queried = True
        return bool(_cached_sixel_support)

def get_terminal_protocol() -> str | None:
    """Detect if the terminal supports a high-resolution graphics protocol.

    Detection priority:
      1. Kitty — native graphics protocol (highest fidelity, 24-bit)
      2. iTerm2/WezTerm — iTerm2 inline image protocol (24-bit)
      3. Sixel — actively probed via the DA1 (``CSI c``) device-attributes
         query, so it's only used on terminals that actually advertise
         support (avoids garbled/"pixelled" output on terminals that merely
         *resemble* xterm).
      4. None — falls back to ANSI half-block characters
    """
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    # Kitty — native graphics protocol
    if "kitty" in term or "kitty" in term_program:
        return "kitty"

    # WezTerm / iTerm2 — iTerm2 inline image protocol
    if "wezterm" in term_program or "iterm" in term_program or "iterm2" in term_program:
        return "iterm2"

    # Fallback for modern Sixel-capable Windows Terminal and VS Code environments
    # where Sixel support is guaranteed. Checking these first avoids running active
    # terminal queries (which print raw '[c' characters if terminal processing is delayed).
    if "WT_SESSION" in os.environ:
        return "sixel"
    if os.environ.get("TERM_PROGRAM") == "vscode":
        return "sixel"

    # Sixel — actively probe via DA1 instead of guessing from TERM
    if get_cached_sixel_support():
        return "sixel"

    return None

def _image_to_base64_png(img: Image.Image) -> str:
    """Convert PIL image to base64 encoded PNG string."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")

def _image_to_sixel(img: Image.Image) -> str:
    """Convert a PIL Image to a Sixel escape sequence string.

    Uses adaptive palette quantization (max 256 colors, Floyd-Steinberg
    dithering) and encodes pixels into Sixel bands (6 vertical pixels
    per band).

    Args:
        img: A PIL Image in RGB mode.

    Returns:
        A complete Sixel escape sequence (DCS ... ST) ready to print.
    """
    # Quantize to 256-color palette with dithering for best visual quality
    quantized = img.quantize(
        colors=256,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.FLOYDSTEINBERG,
    )
    palette_data = quantized.getpalette()  # flat [R, G, B, R, G, B, ...] list
    pixels = quantized.load()
    if palette_data is None or pixels is None:
        return ""

    palette = cast(list[int], palette_data)
    width, height = quantized.size

    parts: list[str] = []

    # ── Sixel palette definitions: #idx;2;R%;G%;B% ──
    # Sixel uses percentage values 0-100 for each RGB channel
    num_colors = len(palette) // 3
    for i in range(num_colors):
        r = int(palette[i * 3] / 255 * 100)
        g = int(palette[i * 3 + 1] / 255 * 100)
        b = int(palette[i * 3 + 2] / 255 * 100)
        parts.append(f"#{i};2;{r};{g};{b}")

    # ── Sixel pixel data in bands of 6 rows ──
    # Each Sixel character encodes a column of 6 vertical pixels as a
    # 6-bit value offset by 63 (ASCII '?'). Bits 0-5 map to rows 0-5
    # within the band, top-to-bottom.
    for band_y in range(0, height, 6):
        # Collect which colors are used in this band and build their
        # Sixel character arrays (one character per column)
        color_runs: dict[int, list[int]] = {}
        band_height = min(6, height - band_y)

        for x in range(width):
            for row in range(band_height):
                y = band_y + row
                color_idx = int(cast(int, pixels[x, y]))
                if color_idx not in color_runs:
                    # Initialize all columns to sixel value 0 (char '?')
                    color_runs[color_idx] = [0] * width
                # Set the bit for this row within the sixel character
                color_runs[color_idx][x] |= (1 << row)

        # Emit each color's scanline for this band
        first_color = True
        for color_idx, col_bits in sorted(color_runs.items()):
            if not first_color:
                parts.append("$")  # Sixel carriage return (rewind to band start)
            first_color = False
            parts.append(f"#{color_idx}")

            # Convert bit values to Sixel characters and apply RLE compression
            chars: list[str] = []
            i = 0
            while i < width:
                ch = chr(col_bits[i] + 63)
                # Count consecutive identical characters for RLE
                run_len = 1
                while i + run_len < width and col_bits[i + run_len] == col_bits[i]:
                    run_len += 1
                if run_len >= 4:
                    # Sixel RLE: !<count><char>
                    chars.append(f"!{run_len}{ch}")
                else:
                    chars.append(ch * run_len)
                i += run_len
            parts.append("".join(chars))

        parts.append("-")  # Sixel line feed (advance to next band)

    sixel_data = "".join(parts)

    # Wrap in DCS (Device Control String): ESC P <params> q <data> ESC \
    # Parameters: P1=0 (normal aspect), P2=0 (no background), P3=0 (horizontal grid)
    return f"\033P0;0;0q\"1;1;{width};{height}{sixel_data}\033\\"

def _is_safe_thumbnail_url(url: str) -> bool:
    """Validate that the thumbnail URL belongs to a trusted YouTube/Google CDN domain."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        host = host.rstrip(".").lower()
        allowed_suffixes = (".youtube.com", ".ytimg.com", ".googleusercontent.com", ".ggpht.com")
        allowed_exact = ("youtube.com", "youtu.be", "ytimg.com", "googleusercontent.com", "ggpht.com")
        if host in allowed_exact or any(host.endswith(suffix) for suffix in allowed_suffixes):
            return True
        return False
    except Exception:
        return False

_thumbnail_bytes_cache: dict[str, bytes] = {}

def get_ansi_thumbnail(
    url: str,
    width: int = 16,
    height: int = 6,
    *,
    force_ansi: bool = False,
) -> TerminalImage | None:
    """Download thumbnail from URL and render it as a TerminalImage.

    Resizes the image and uses the best available graphics protocol:
    Kitty, iTerm2/WezTerm, Sixel, or ANSI half-block fallback.

    Args:
        url: Thumbnail image URL.
        width: Target width in terminal columns.
        height: Target height in terminal rows.
        force_ansi: If True, always use ANSI half-block fallback regardless
            of terminal protocol. Useful for table-embedded thumbnails where
            inline graphics protocols (Sixel) cause layout corruption.
    """
    if not url or not url.startswith("http") or not _is_safe_thumbnail_url(url):
        return None

    # Retrieve from cache or download
    img_bytes = _thumbnail_bytes_cache.get(url)
    if img_bytes is None:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                # Limit thumbnail download to 10MB to avoid OOM DoS
                img_bytes = response.read(10 * 1024 * 1024)
                _thumbnail_bytes_cache[url] = img_bytes
        except Exception:
            return None

    try:
        # Load and render using Pillow directly from memory
        with Image.open(BytesIO(img_bytes)) as raw_img:
            rgb_img = raw_img.convert("RGB")

            # Detect terminal protocol (skip inline protocols if force_ansi)
            protocol = None if force_ansi else get_terminal_protocol()

            if protocol == "kitty":
                # Kitty native graphics protocol — highest fidelity (24-bit PNG)
                pixel_width = width * 8
                pixel_height = height * 16
                from PIL import ImageOps
                resized_img = ImageOps.fit(
                    rgb_img, (pixel_width, pixel_height), Image.Resampling.LANCZOS
                )

                base64_data = _image_to_base64_png(resized_img)
                escape_seq = f"\033_Ga=T,f=100,c={width},r={height},C=1;{base64_data}\033\\"

                return TerminalImage(escape_seq, width, height, is_inline=True)

            if protocol == "iterm2":
                # iTerm2 / WezTerm inline image protocol (24-bit PNG)
                pixel_width = width * 8
                pixel_height = height * 16
                from PIL import ImageOps
                resized_img = ImageOps.fit(
                    rgb_img, (pixel_width, pixel_height), Image.Resampling.LANCZOS
                )

                base64_data = _image_to_base64_png(resized_img)
                escape_seq = f"\033]1337;File=inline=1;width={width};height={height};preserveAspectRatio=1;doNotMoveCursor=1:{base64_data}\a"

                return TerminalImage(escape_seq, width, height, is_inline=True)

            if protocol == "sixel":
                # Sixel graphics — 256-color adaptive palette with dithering
                # Supported by Windows Terminal (Win 11+), foot, mlterm, mintty, xterm
                # Query cell pixel size to avoid stretching and blurriness; fallback to standard 10x20.
                # Bypass active cell size queries on WT/VSCode to prevent raw escape codes ([16t) on some shells.
                if "WT_SESSION" in os.environ or os.environ.get("TERM_PROGRAM") == "vscode":
                    cell_w, cell_h = (10, 20)
                else:
                    cell_size = get_cached_cell_size()
                    cell_w, cell_h = cell_size if cell_size else (10, 20)

                pixel_width = width * cell_w
                pixel_height = height * cell_h
                from PIL import ImageOps
                resized_img = ImageOps.fit(
                    rgb_img, (pixel_width, pixel_height), Image.Resampling.LANCZOS
                )
                sixel_seq = _image_to_sixel(resized_img)
                return TerminalImage(sixel_seq, width, height, is_inline=True)

            # Fallback: ANSI Unicode half-block characters
            # We need height * 2 because each char cell represents 2 vertical pixels
            from PIL import ImageOps
            resized_img = ImageOps.fit(
                rgb_img, (width, height * 2), Image.Resampling.LANCZOS
            )

            # Sharpen after downscale — LANCZOS is smooth but loses crispness at
            # small sizes.  UnsharpMask recovers edge definition without halos.
            resized_img = resized_img.filter(
                ImageFilter.UnsharpMask(radius=0.8, percent=160, threshold=2)
            )
            # Slight contrast boost so colours "pop" in the terminal
            resized_img = ImageEnhance.Contrast(resized_img).enhance(1.15)

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
