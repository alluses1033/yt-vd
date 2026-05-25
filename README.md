# yt-vd

A terminal YouTube downloader for videos, playlists, audio, clips, chapters, subtitles, thumbnails, and download history.

Repository: <https://github.com/alluses1033/yt-vd>

> yt-vd is not affiliated with YouTube or Google. Use it only for content you have the right to download.

## Features

- Interactive CLI: run `yt-vd` and choose what to do.
- Standard CLI commands for scripts and power users.
- Video downloads with quality caps and automatic fallback.
- Playlist, channel, batch, chapter, and clip downloads.
- Audio extraction to MP3, M4A, OPUS, FLAC, and WAV.
- Subtitles with manual subtitle and auto-caption fallback.
- Thumbnail and metadata embedding.
- Download progress in CLI.
- Local SQLite download history.
- Standalone binary builds with PyInstaller.

## Quick Install

These installers download the latest release binaries from this repository.

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/alluses1033/yt-vd/main/install.ps1 | iex
```

Then open a new PowerShell window:

```powershell
yt-vd --help
```

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/alluses1033/yt-vd/main/install.sh | sh
```

If `yt-vd` is not found after install, add this to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Required Dependency

Install FFmpeg. It is required for merging video/audio streams, extracting audio, thumbnails, subtitles, and metadata.

### Windows

```powershell
winget install Gyan.FFmpeg
```

### macOS

```bash
brew install ffmpeg
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg
```

## Install From Source

Use this if you want to run or develop the Python project directly.

```bash
git clone https://github.com/alluses1033/yt-vd.git
cd yt-vd
uv sync
uv run yt-vd --help
```

Without `uv`:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
yt-vd --help
```

On Linux/macOS, activate with:

```bash
source .venv/bin/activate
```

## Common Commands

```bash
# Interactive menu
yt-vd

# GUI
yt-vd-gui

# Download one video
yt-vd download "https://www.youtube.com/watch?v=VIDEO_ID"

# Download video with subtitles
yt-vd download "URL" --subtitles --sub-lang en

# Download up to 1080p as MKV
yt-vd download "URL" --quality high --format mkv

# Download a playlist with 4 workers
yt-vd playlist "PLAYLIST_URL" --parallel 4

# Download playlist range
yt-vd playlist "PLAYLIST_URL" --start 5 --end 20

# Extract MP3 audio
yt-vd audio "URL" --format mp3 --bitrate 320k --thumbnail

# Search YouTube
yt-vd search "lofi coding music" --results 10

# Download a clip
yt-vd clip "URL" --start 01:30 --end 03:45

# Split by chapters
yt-vd chapters "URL"

# Show history
yt-vd history

# Clear history
yt-vd history --clear
```

Quote URLs in PowerShell, bash, and zsh. This matters when URLs contain `&`.

## Command Reference

### `yt-vd download URL`

Download a single video.

| Flag | Short | Default | Description |
| --- | --- | --- | --- |
| `--quality` | `-q` | `best` | Quality preset or resolution. |
| `--format` | `-f` | `mp4` | Output container: `mp4`, `mkv`, `webm`. |
| `--output` | `-o` | `.` | Output directory. |
| `--subtitles` | `-s` | off | Download and embed subtitles. |
| `--sub-lang` | | `en` | Subtitle language code, for example `en`, `hi`, `ja`. |
| `--thumbnail` | | off | Embed thumbnail. |
| `--sponsorblock` | | off | Remove sponsor segments when available. |
| `--verbose` | `-v` | off | Enable extra logs. |

### `yt-vd playlist URL`

Download videos from a playlist.

| Flag | Short | Default | Description |
| --- | --- | --- | --- |
| `--quality` | `-q` | `best` | Quality preset or resolution. |
| `--format` | `-f` | `mp4` | Output container. |
| `--output` | `-o` | `.` | Output directory. |
| `--start` | | `1` | First playlist item, 1-based. |
| `--end` | | all | Last playlist item, inclusive. |
| `--parallel` | `-p` | CPU based | Number of download workers. |
| `--subtitles` | `-s` | off | Download subtitles for each video. |
| `--sub-lang` | | `en` | Subtitle language. |
| `--thumbnail` | | off | Embed thumbnails. |
| `--sponsorblock` | | off | Remove sponsor segments when available. |

### `yt-vd audio URL`

Extract audio only.

| Flag | Short | Default | Description |
| --- | --- | --- | --- |
| `--format` | `-f` | `mp3` | `mp3`, `m4a`, `opus`, `flac`, `wav`. |
| `--bitrate` | `-b` | `320k` | `128k`, `192k`, `256k`, `320k`. |
| `--output` | `-o` | `.` | Output directory. |
| `--thumbnail` | | off | Embed thumbnail as album art. |

### Other Commands

| Command | Description |
| --- | --- |
| `yt-vd search QUERY` | Search YouTube and optionally download a result. |
| `yt-vd channel URL --last 10` | Download recent channel uploads. |
| `yt-vd batch urls.txt` | Download URLs from a text file. |
| `yt-vd clip URL --start 00:30 --end 01:00` | Download a time range. |
| `yt-vd chapters URL` | Download a video split by chapters. |
| `yt-vd info URL` | Show video information without downloading. |
| `yt-vd history` | Show local download history. |
| `yt-vd manual` | Show short built-in help. |

## Quality Values

| Value | Meaning |
| --- | --- |
| `best` | Best available quality. |
| `high` | Up to 1080p. |
| `medium` | Up to 720p. |
| `better` | Up to 480p. |
| `low` | Up to 360p. |
| `lowest` | Up to 240p. |
| `1080p`, `720p`, etc. | Direct resolution cap. |

If the exact quality is not available, yt-vd falls back to the closest available quality.

## Release Assets

The install scripts expect these files on the latest GitHub release:

| Platform | Asset |
| --- | --- |
| Windows CLI | `yt-vd.exe` |
| Linux CLI | `yt-vd` |

## Build Binaries

### Windows

```powershell
.\build.bat
```

### Linux / macOS

```bash
chmod +x build.sh
./build.sh
```

Build output is written to `dist/`.

## Publish a Release

The repository includes a GitHub Actions workflow that builds Windows and Linux binaries when a version tag is pushed.

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The workflow publishes these assets to the GitHub release:

- `yt-vd.exe`
- `yt-vd`

The PowerShell and Linux installers download from the latest release.

## Development Checks

```bash
uv run ruff check src tests
uv run pytest
```

## Uninstall

### Windows

Delete:

```powershell
$env:LOCALAPPDATA\Programs\yt-vd
```

Then remove that folder from your user `Path` environment variable.

### Linux / macOS

```bash
rm -f ~/.local/bin/yt-vd
```

## Troubleshooting

### `ffmpeg` not found

Install FFmpeg and restart your terminal.

### `yt-vd` not found after install

Restart your terminal. On Linux/macOS, ensure `~/.local/bin` is in `PATH`.

### Some formats are missing

Install a JavaScript runtime such as Node.js or Deno. yt-vd hides the repeated runtime warning, but the runtime can still help the downloader engine access more formats.

## License

MIT License.
