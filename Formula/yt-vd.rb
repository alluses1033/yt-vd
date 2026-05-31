class YtVd < Formula
  desc "Powerful YouTube downloader CLI for videos, audio, playlists, and chapters"
  homepage "https://github.com/alluses1033/yt-vd"
  url "https://github.com/alluses1033/yt-vd/releases/latest/download/yt-vd-macos"
  version "latest"
  # Note: To submit to official taps or register locally, SHA256 can be calculated
  # and populated here on each version release. Since it uses "latest", we download
  # the compiled macOS binary directly.
  # sha256 "..."

  def install
    # Downloaded binary is named yt-vd-macos. We rename and install it under bin/yt-vd.
    bin.install "yt-vd-macos" => "yt-vd"
    # Ensure binary is executable
    chmod 0755, bin/"yt-vd"
  end

  test do
    assert_match "yt-vd", shell_output("#{bin}/yt-vd --help")
  end
end
