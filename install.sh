#!/usr/bin/env sh
set -eu

repo="alluses1033/yt-vd"
install_dir="${HOME}/.local/bin"
base_url="https://github.com/${repo}/releases/download/latest"

os="$(uname -s)"
if [ "$os" = "Linux" ]; then
    asset_name="yt-vd-linux"
elif [ "$os" = "Darwin" ]; then
    asset_name="yt-vd-macos"
else
    printf '%s\n' "This binary installer supports Linux and macOS."
    printf '%s\n' "For other platforms, please install from source."
    exit 1
fi

printf '%s\n' "Installing yt-vd for $os ($asset_name)..."
mkdir -p "$install_dir"

tmp_dir="$(mktemp -d "${install_dir}/.yt-vd-install.XXXXXX")"
cleanup() {
    rm -rf "$tmp_dir"
}
trap cleanup EXIT HUP INT TERM

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

tmp_bin="${tmp_dir}/yt-vd"
download "${base_url}/${asset_name}" "$tmp_bin"

if [ ! -s "$tmp_bin" ]; then
    printf '%s\n' "Downloaded binary is empty; leaving existing installation untouched." >&2
    exit 1
fi

chmod 0755 "$tmp_bin"
mv -f "$tmp_bin" "${install_dir}/yt-vd"

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
