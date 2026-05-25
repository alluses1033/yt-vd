#!/usr/bin/env sh
set -eu

repo="alluses1033/yt-vd"
install_dir="${HOME}/.local/bin"
base_url="https://github.com/${repo}/releases/download/latest"

os="$(uname -s)"
if [ "$os" != "Linux" ]; then
    printf '%s\n' "This binary installer currently supports Linux."
    printf '%s\n' "For macOS, install from source with: uv sync && uv run yt-vd --help"
    exit 1
fi

printf '%s\n' "Installing yt-vd..."
mkdir -p "$install_dir"

download() {
    url="$1"
    out="$2"
    name="$(basename "$out")"
    printf '%s\n' "Downloading ${name}..."

    if command -v curl >/dev/null 2>&1; then
        curl -fL --progress-bar "$url" -o "$out"
    elif command -v wget >/dev/null 2>&1; then
        wget --show-progress "$url" -O "$out"
    else
        printf '%s\n' "Install curl or wget, then rerun this installer." >&2
        exit 1
    fi
}

download "${base_url}/yt-vd" "${install_dir}/yt-vd"
chmod +x "${install_dir}/yt-vd"

case ":$PATH:" in
    *":${install_dir}:"*) ;;
    *)
        printf '%s\n' "Add this to your shell profile if yt-vd is not found:"
        printf '%s\n' "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

if ! command -v ffmpeg >/dev/null 2>&1; then
    printf '%s\n' "FFmpeg was not found. Install it with your package manager, for example:"
    printf '%s\n' "  sudo apt install ffmpeg"
fi

printf '\n%s\n' "yt-vd installed successfully."
printf '%s\n' "Run:"
printf '%s\n' "  yt-vd --help"
