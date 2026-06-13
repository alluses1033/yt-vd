# 🎥 yt-vd

[![License](https://img.shields.io/github/license/alluses1033/yt-vd)](LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/alluses1033/yt-vd)](https://github.com/alluses1033/yt-vd/releases/latest)
[![Tests Status](https://img.shields.io/github/actions/workflow/status/alluses1033/yt-vd/release.yml?label=tests)](https://github.com/alluses1033/yt-vd/actions)

A high-performance, feature-rich terminal YouTube downloader for videos, playlists, audio, clips, chapters, subtitles, and thumbnails. Built on top of `yt-dlp` and optimized for speed, safety, and a premium CLI experience.

> **Disclaimer**: *yt-vd is not affiliated with YouTube or Google. Please use this tool only for downloading content you have the legal right to access.*

---

## ✨ Features

- 💻 **Interactive TUI**: Simply run `yt-vd` to launch a guided selection menu.
- 🚀 **Parallel Downloads**: Speeds up playlist downloads using concurrent workers.
- 🛡️ **Fail-Safe Integrity**: Auto-checks downloaded file integrity and manages active temp directories safely.
- 🎨 **Rich Graphics**: Renders inline high-resolution Sixel/Kitty thumbnails on supported terminals with ANSI fallback.
- 📊 **Local History**: Kept in a local SQLite database for easy lookups and tracking.
- 🎵 **Audio Extraction**: High-fidelity extraction to MP3, M4A, OPUS, FLAC, or WAV.
- ✂️ **Clips & Chapters**: Download specific video timeframes or split videos automatically by chapters.
- 📝 **Subtitles & Captions**: Download and embed subtitles with automatic caption fallback.
- 🤖 **SponsorBlock**: Auto-skips sponsor segments during download.

---

## 🚀 Installation

### 1. Windows

You can install the compiled standalone binary via **Winget** or PowerShell:

- **Via Winget (Recommended):**
  ```cmd
  winget install alluses1033.yt-vd
  ```
- **Via PowerShell bootstrap script:**
  ```powershell
  irm https://raw.githubusercontent.com/alluses1033/yt-vd/main/install.ps1 | iex
  ```
  *(After installation, restart your terminal and run `yt-vd --help`)*

### 2. macOS

Install using **Homebrew** or the shell script:

- **Via Homebrew Tap:**
  ```bash
  brew tap alluses1033/tap
  brew install yt-vd
  ```
- **Via installation script:**
  ```bash
  curl -fsSL https://raw.githubusercontent.com/alluses1033/yt-vd/main/install.sh | sh
  ```

### 3. Linux

Install the standalone binary via curl:
```bash
curl -fsSL https://raw.githubusercontent.com/alluses1033/yt-vd/main/install.sh | sh
```
*(If `yt-vd` is not found after running the script on Linux/macOS, append `export PATH="$HOME/.local/bin:$PATH"` to your shell profile, e.g. `~/.bashrc` or `~/.zshrc`)*

---

## 📦 Required Dependency: FFmpeg

FFmpeg is **required** for merging video/audio formats, extracting audio, and embedding thumbnails/subtitles.

- **Windows**: `winget install Gyan.FFmpeg`
- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `sudo apt update && sudo apt install -y ffmpeg`

---

## 🛠️ Installation from Source

If you prefer to run or develop the Python codebase directly:

```bash
# Clone the repository
git clone https://github.com/alluses1033/yt-vd.git
cd yt-vd

# Sync dependencies using uv (recommended)
uv sync
uv run yt-vd --help
```

Without `uv`, standard pip tools can be used:
```bash
python -m venv .venv
# On Windows: .\.venv\Scripts\activate
# On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
yt-vd --help
```

---

## 📖 Quick Reference & Common Commands

```bash
# Start the interactive UI
yt-vd

# Launch GUI mode (if configured)
yt-vd-gui

# Download a video with default settings
yt-vd download "https://www.youtube.com/watch?v=VIDEO_ID"

# Download with subtitles & custom output directory
yt-vd download "URL" --subtitles --sub-lang en --output ~/Downloads

# Download a playlist using 4 concurrent download workers
yt-vd playlist "PLAYLIST_URL" --parallel 4 --start 1 --end 10

# Extract high-quality MP3 audio with embedded album art
yt-vd audio "URL" --format mp3 --bitrate 320k --thumbnail

# Search YouTube and select a result to download
yt-vd search "lofi coding music" --results 10

# Download a specific clip range
yt-vd clip "URL" --start 01:30 --end 03:45

# Download a video split automatically by chapters
yt-vd chapters "URL"

# View local download history database
yt-vd history
```
> ⚠️ **Note**: Always wrap YouTube URLs in double quotes (`"URL"`) in terminal shells to avoid parser errors with special characters like `&`.

---

## 📋 Command Reference

### `yt-vd download URL`
Download a single video.

| Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--quality` | `-q` | `best` | Preset quality (`best`, `high`, `medium`, `better`, `low`, `lowest`) or exact resolution cap (e.g. `1080p`, `720p`). |
| `--format` | `-f` | `mp4` | Output container format: `mp4`, `mkv`, `webm`. |
| `--output` | `-o` | `.` | Output directory for the finished file. |
| `--subtitles`| `-s` | `False` | Download and embed subtitles in the video. |
| `--sub-lang` | | `en` | Subtitle language code (e.g., `en`, `hi`, `ja`, `es`). |
| `--thumbnail`| | `False`| Download and embed video thumbnail. |
| `--sponsorblock`| | `False`| Remove sponsor segments using SponsorBlock API. |
| `--verbose`  | `-v` | `False`| Print verbose debugging output. |

### `yt-vd playlist URL`
Download videos from a playlist.

| Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--quality` | `-q` | `best` | Preset quality or resolution cap. |
| `--format` | `-f` | `mp4` | Output container format. |
| `--output` | `-o` | `.` | Output directory. |
| `--start` | | `1` | First playlist index to download (1-based). |
| `--end` | | `None` | Last playlist index to download (inclusive). |
| `--parallel`| `-p` | *CPU-based*| Number of parallel worker threads. |
| `--subtitles`| `-s` | `False` | Download subtitles. |
| `--sub-lang` | | `en` | Subtitle language. |
| `--thumbnail`| | `False`| Embed video thumbnails. |

### `yt-vd audio URL`
Extract audio track only.

| Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--format` | `-f` | `mp3` | Target audio format: `mp3`, `m4a`, `opus`, `flac`, `wav`. |
| `--bitrate` | `-b` | `320k` | Audio bitrate: `128k`, `192k`, `256k`, `320k`. |
| `--output` | `-o` | `.` | Output directory. |
| `--thumbnail`| | `False`| Embed thumbnail as audio album art. |

### Auxiliary Commands

| Command | Description |
| :--- | :--- |
| `yt-vd search QUERY` | Search YouTube and optionally choose a result to download. |
| `yt-vd channel URL --last 10` | Download the most recent uploads from a YouTube channel. |
| `yt-vd batch urls.txt` | Read and download list of URLs from a local text file. |
| `yt-vd clip URL --start 00:30 --end 01:00` | Download a specific clip time frame. |
| `yt-vd chapters URL` | Download a video split automatically into separate chapter files. |
| `yt-vd info URL` | Fetch and print video metadata without downloading. |
| `yt-vd history` | View local SQLite download logs (`--clear` flag empties logs). |
| `yt-vd uninstall` | Completely uninstall `yt-vd` (deletes binaries, configs, database, and cleans PATH). |

---

## ⚙️ Development & Testing

We enforce clean formatting and test coverage:

```bash
# Code linter check
uv run ruff check src tests

# Run unit and integration tests
uv run pytest
```

---

## 📝 License

This project is licensed under the [MIT License](LICENSE).
