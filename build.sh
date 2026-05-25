#!/bin/bash
# ─────────────────────────────────────────────
# Build script for yt-vd
# Builds standalone executable for CLI
# ─────────────────────────────────────────────

set -e

echo "╔═══════════════════════════════════════╗"
echo "║   yt-vd Build Script                  ║"
echo "╚═══════════════════════════════════════╝"

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed. Install it from https://docs.astral.sh/uv/"
    exit 1
fi

# Install dependencies including dev
echo ""
echo "📦 Installing dependencies..."
uv sync --all-groups

# Check for ffmpeg (optional but recommended)
if command -v ffmpeg &> /dev/null; then
    echo "✅ FFmpeg found: $(ffmpeg -version | head -n1)"
else
    echo "⚠️  FFmpeg not found. It's required for video processing."
fi

# Build executables
echo ""
echo "🔨 Building executable..."
uv run pyinstaller yt-vd.spec --clean --noconfirm

echo ""
echo "✅ Build complete!"
echo ""
echo "Executable is in dist/:"
ls -la dist/yt-vd* 2>/dev/null || echo "  (check dist/ directory)"
echo ""
echo "Usage:"
echo "  ./dist/yt-vd --help        # CLI"
