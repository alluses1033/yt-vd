"""yt-vd — A powerful YouTube video & playlist downloader."""

try:
    from importlib.metadata import version
    __version__ = version("yt-vd")
except Exception:
    __version__ = "1.1.16"
