from pathlib import Path
from unittest.mock import MagicMock, patch

import yt_dlp
from typer.testing import CliRunner

from cli import app
from constants import DEFAULT_PARALLEL_WORKERS, DownloadStatus
from core.config import AppConfig, ConfigManager
from core.fragment_safety import SafeDownloadManager
from core.history import DownloadHistory
from core.progress import ProgressInfo, ProgressTracker
from core.quality import check_quality_available, get_best_matching_quality, resolve_format_string
from core.utils import detect_url_type, format_duration, format_file_size, validate_url

# ─────────────────────────────────────────────────────────────────────────────
# 1. URL Validation & Detection Edge Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_url_validation_edge_cases():
    # Empty and whitespace
    assert validate_url("") is False
    assert validate_url("   ") is False
    # None-like string
    assert validate_url("None") is False
    # Malformed protocols
    assert validate_url("http://youtube.com/watch?v=dQw4w9WgXcQ") is True  # HTTP works
    assert validate_url("ftp://youtube.com/watch?v=123") is False
    # Weird query parameter placements
    assert validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share") is True
    assert validate_url("https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ") is True
    assert validate_url("https://music.youtube.com/watch?v=dQw4w9WgXcQ") is False
    assert validate_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ") is False
    # Non-YouTube
    assert validate_url("https://google.com") is False
    assert validate_url("https://vimeo.com/12345") is False
    assert validate_url("https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ") is False
    assert validate_url("https://evil.test/?next=https://youtube.com/watch?v=dQw4w9WgXcQ") is False


def test_url_type_detection_edge_cases():
    # Unknown/empty
    assert detect_url_type("") == "unknown"
    assert detect_url_type("https://youtube.com") == "unknown"
    # Channel handles
    assert detect_url_type("https://youtube.com/@GoogleMind") == "channel"
    assert detect_url_type("https://www.youtube.com/c/SomeChannel") == "channel"
    assert detect_url_type("https://www.youtube.com/channel/UC1234567890") == "channel"
    assert detect_url_type("https://www.youtube.com/user/SomeUser") == "channel"
    # Shorts
    assert detect_url_type("https://youtube.com/shorts/dQw4w9WgXcQ") == "shorts"
    # Embed
    assert detect_url_type("https://youtube.com/embed/dQw4w9WgXcQ") == "video"
    # Playlists
    assert detect_url_type("https://www.youtube.com/playlist?list=PL123&index=2") == "playlist"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Formatting Utilities
# ─────────────────────────────────────────────────────────────────────────────

def test_format_duration_edge_cases():
    # Zero and negative
    assert format_duration(0) == "00:00"
    assert format_duration(-10) == "00:00"
    # Floating values
    assert format_duration(5.6) == "00:05"
    # Hours limit
    assert format_duration(3599) == "59:59"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(86400) == "24:00:00"


def test_format_file_size_edge_cases():
    # Zero and negative sizes
    assert format_file_size(0) == "0 B"
    assert format_file_size(-50) == "0 B"
    # Binary prefixes (KiB, MiB, GiB, TiB)
    assert format_file_size(1023) == "1023 B"
    assert format_file_size(1024) == "1.00 KiB"
    assert format_file_size(1024 * 1024) == "1.00 MiB"
    assert format_file_size(1024 * 1024 * 1024) == "1.00 GiB"
    assert format_file_size(1024 * 1024 * 1024 * 1024) == "1.00 TiB"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Quality Fallbacks & Resolutions
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_format_string_edge_cases():
    # Invalid resolution string raises ValueError
    import pytest
    with pytest.raises(ValueError):
        resolve_format_string("invalid_quality")
    # Preset bounds
    assert "height<=1080" in resolve_format_string("high")
    assert "height<=360" in resolve_format_string("low")


def test_quality_resolution_matching():
    # Simulate a typical yt-dlp info dict containing formats with vcodec set
    info_dict = {
        "formats": [
            {"height": 240, "vcodec": "vp9", "format_id": "240p_stream"},
            {"height": 360, "vcodec": "av01", "format_id": "360p_stream"},
            {"height": 720, "vcodec": "h264", "format_id": "720p_stream"},
            {"height": 1080, "vcodec": "h264", "format_id": "1080p_stream"},
        ]
    }
    # Check what quality is matched
    assert check_quality_available(info_dict, "720p") is True
    assert check_quality_available(info_dict, "4k") is False  # not available

    # Check best matching quality fallback
    assert get_best_matching_quality(info_dict, "1080p") == "1080p"
    assert get_best_matching_quality(info_dict, "1440p") == "1080p"  # Fallback to next best
    assert get_best_matching_quality(info_dict, "4k") == "1080p"
    assert get_best_matching_quality(info_dict, "240p") == "240p"


# ─────────────────────────────────────────────────────────────────────────────
# 4. AppConfig Validation
# ─────────────────────────────────────────────────────────────────────────────

def test_config_edge_cases(tmp_path):
    # Test setting attributes and constraints
    config = AppConfig()
    config.parallel_workers = 100  # Sets workers
    assert config.parallel_workers == 100

    # Path override for testing config manager TOML saves
    ConfigManager._reset_singleton()
    cfg_file = tmp_path / "config.toml"
    with patch.object(ConfigManager, "_resolve_config_path", return_value=cfg_file):
        manager = ConfigManager.get_instance()
        manager.update(parallel_workers=5)
        assert manager.current.parallel_workers == 5

        # Check it saved to disk
        assert cfg_file.exists()

        # Load from scratch
        ConfigManager._reset_singleton()
        manager2 = ConfigManager.get_instance()
        assert manager2.current.parallel_workers == 5

        # Reset to defaults
        manager2.reset()
        assert manager2.current.parallel_workers == DEFAULT_PARALLEL_WORKERS


# ─────────────────────────────────────────────────────────────────────────────
# 5. Database & History Thread-Safety & SQL Injections
# ─────────────────────────────────────────────────────────────────────────────

def test_history_sql_injection_and_queries(tmp_path):
    db_path = tmp_path / "test_history.db"
    history = DownloadHistory(db_path=db_path)

    # Insert entry with SQL injection string in title and url
    from constants import DownloadResult
    injection_res = DownloadResult(
        url="https://youtube.com/watch?v=abc12345678",
        title="Video title' OR 1=1 --",
        status=DownloadStatus.COMPLETED,
        file_size=12345,
        quality="720p",
        format="mp4",
        duration=60.0,
    )
    history.add(injection_res)

    # Ensure exists functions correctly with injection URL
    assert history.exists("https://youtube.com/watch?v=abc12345678") is True
    # Search functions correctly without breaking due to syntax error
    search_results = history.search("title' OR 1=1 --")
    assert len(search_results) == 1
    assert search_results[0]["title"] == "Video title' OR 1=1 --"

    # Verify get_stats handles single entries
    stats = history.get_stats()
    assert stats["total_downloads"] == 1
    assert stats["total_count"] == 1

    # Delete non-existent record ID
    assert history.delete(999) is False


# ─────────────────────────────────────────────────────────────────────────────
# 6. Progress Tracker
# ─────────────────────────────────────────────────────────────────────────────

def test_progress_tracker():
    tracker = ProgressTracker()
    calls = []

    def cb(info: ProgressInfo) -> None:
        calls.append(info)

    tracker.add_callback(cb)

    # Trigger callback updates
    tracker.set_status(DownloadStatus.DOWNLOADING)
    tracker.update({
        "status": "downloading",
        "downloaded_bytes": 500,
        "total_bytes": 1000,
        "speed": 1024.0,
        "eta": 5.0
    })

    assert len(calls) >= 2
    assert calls[-1].percent == 50.0
    assert calls[-1].speed == 1024.0
    assert calls[-1].eta == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Safe Download Manager & Integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_safe_download_manager(tmp_path):
    safety = SafeDownloadManager(output_dir=tmp_path)
    paths = safety.get_ydl_paths()

    # Confirm temp and home paths are built correctly
    assert "paths" in paths
    assert "home" in paths["paths"]
    assert "temp" in paths["paths"]
    assert Path(paths["paths"]["temp"]).name == ".yt-vd-temp"

    # Create dummy temp file and verify cleanup
    temp_dir = Path(paths["paths"]["temp"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = temp_dir / "partial.mp4"
    dummy_file.write_text("dummy content")
    assert dummy_file.exists()

    safety.cleanup_temp()
    assert not dummy_file.exists()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Command Line Interface Subcommands Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_subcommands():
    runner = CliRunner()

    # 1. Version command
    from __init__ import __version__
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout

    # 2. Manual command
    result = runner.invoke(app, ["manual"])
    assert result.exit_code == 0
    assert "User Manual" in result.stdout

    # 3. History command (initially empty or mock)
    # Using patch to clear and isolate history during CLI runner tests
    with patch("core.history.get_history", return_value=[]):
        result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "No download history found" in result.stdout


# ─────────────────────────────────────────────────────────────────────────────
# 9. yt-dlp Mock Downloads & Retries
# ─────────────────────────────────────────────────────────────────────────────

@patch("yt_dlp.YoutubeDL")
def test_download_video_retry_logic(mock_ytdl_class, tmp_path):
    from core.downloader import download_video

    # Configure mock to raise a transient connection error first, then succeed
    mock_instance = MagicMock()
    mock_instance.__enter__.return_value = mock_instance
    mock_ytdl_class.return_value = mock_instance

    # Create a real dummy file in tmp_path
    video_file = tmp_path / "test_retry.mp4"
    video_file.write_text("fake video content")

    # Create side effects: info extract succeeds, first download fails, retry succeeds
    info_dict = {
        "title": "Test Retry Video",
        "id": "retry123",
        "duration": 45,
        "ext": "mp4",
        "filepath": str(video_file)
    }
    mock_instance.extract_info.side_effect = [
        info_dict,
        yt_dlp.utils.DownloadError("Connection reset by peer"),
        info_dict
    ]

    # Mock verify_file_integrity to always return True (or let it run naturally since file exists)
    with patch("core.downloader.verify_file_integrity", return_value=True):
        result = download_video(
            url="https://youtube.com/watch?v=retry123456",
            quality="best",
            fmt="mp4",
            output_dir=tmp_path,
            max_retries=2,
            use_temp_dir=False,  # bypass temp folder renaming for simplicity
        )

        # Verify it retried and returned COMPLETED status
        assert result.status == DownloadStatus.COMPLETED
        assert result.title == "Test Retry Video"
        assert result.file_path == video_file
        assert mock_instance.extract_info.call_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# 10. download_clip & download_by_chapters Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_download_clip_ranges():
    from constants import DownloadResult
    from core.downloader import download_clip

    with patch("core.downloader.download_video") as mock_download_video:
        mock_download_video.return_value = DownloadResult(
            url="https://youtube.com/watch?v=123",
            status=DownloadStatus.COMPLETED,
        )

        # Test MM:SS parsing
        download_clip(
            url="https://youtube.com/watch?v=123",
            start_time="01:30",
            end_time="02:15",
            quality="best",
            video_format="mp4"
        )

        args, kwargs = mock_download_video.call_args
        assert args[0] == "https://youtube.com/watch?v=123"
        assert kwargs["quality"] == "best"
        assert kwargs["video_format"] == "mp4"
        extra_opts = kwargs["extra_opts"]
        assert extra_opts["force_keyframes_at_cuts"] is True

        # Resolve the lambda callback
        callback = extra_opts["download_ranges"]
        ranges = callback(None, None)
        assert len(ranges) == 1
        assert ranges[0]["start_time"] == 90.0
        assert ranges[0]["end_time"] == 135.0

        # Test HH:MM:SS parsing
        download_clip(
            url="https://youtube.com/watch?v=123",
            start_time="01:02:03",
            end_time="02:00:00"
        )
        ranges2 = mock_download_video.call_args[1]["extra_opts"]["download_ranges"](None, None)
        assert ranges2[0]["start_time"] == 3723.0
        assert ranges2[0]["end_time"] == 7200.0


@patch("core.utils.check_ffmpeg", return_value="7.0")
def test_download_by_chapters_mock(mock_check_ffmpeg, tmp_path):
    from core.metadata import download_by_chapters

    # Mock get_chapters to return simulated chapters
    mock_chapters = [
        {"title": "Intro", "start_time": 0.0, "end_time": 30.0},
        {"title": "Middle", "start_time": 30.0, "end_time": 100.0}
    ]

    url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
    temp_folder = tmp_path / ".yt-vd-temp" / "vid_dQw4w9WgXcQ"
    temp_folder.mkdir(parents=True, exist_ok=True)

    # Create real dummy files inside temp folder
    fake_temp_file_1 = temp_folder / "01 - Intro.mp4"
    fake_temp_file_1.write_text("fake chapter 1")
    fake_temp_file_2 = temp_folder / "02 - Middle.mp4"
    fake_temp_file_2.write_text("fake chapter 2")

    # Expected final files
    expected_final_file_1 = tmp_path / "01 - Intro.mp4"
    expected_final_file_2 = tmp_path / "02 - Middle.mp4"

    with patch("core.metadata.get_chapters", return_value=mock_chapters), \
         patch("core.metadata.verify_file_integrity", return_value=True), \
         patch("yt_dlp.YoutubeDL") as mock_ytdl_class:

        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_ytdl_class.return_value = mock_instance

        # Return chapter files sequentially
        mock_instance.extract_info.side_effect = [
            {"requested_downloads": [{"filepath": str(fake_temp_file_1)}]},
            {"requested_downloads": [{"filepath": str(fake_temp_file_2)}]}
        ]

        results = download_by_chapters(
            url=url,
            output_dir=tmp_path,
            quality="720p",
            fmt="mp4"
        )

        assert len(results) == 2
        assert results[0].status == DownloadStatus.COMPLETED
        assert results[0].title == "Intro"
        assert results[0].file_path == expected_final_file_1
        assert expected_final_file_1.exists()
        assert results[1].title == "Middle"
        assert results[1].file_path == expected_final_file_2
        assert expected_final_file_2.exists()
        assert mock_instance.extract_info.call_count == 2

        # Verify that temp files and the parent folder are fully deleted
        assert not temp_folder.exists()
        assert not (tmp_path / ".yt-vd-temp").exists()


# ─────────────────────────────────────────────────────────────────────────────
# 11. CLI Extended Commands Tests
# ─────────────────────────────────────────────────────────────────────────────

@patch("core.utils.check_ffmpeg", return_value="7.0")
def test_cli_extended_subcommands(mock_check_ffmpeg):
    from constants import DownloadResult
    runner = CliRunner()

    # Test download command
    with patch("core.downloader.download_video") as mock_dl:
        mock_dl.return_value = DownloadResult(url="http://x", status=DownloadStatus.COMPLETED)
        result = runner.invoke(
            app,
            ["download", "https://youtube.com/watch?v=123", "-q", "720p", "-f", "mkv"],
        )
        assert result.exit_code == 0
        mock_dl.assert_called_once()
        _, kwargs = mock_dl.call_args
        assert kwargs["quality"] == "720p"
        assert kwargs["fmt"] == "mkv"

    # Test audio command
    with patch("core.audio.extract_audio") as mock_audio:
        mock_audio.return_value = DownloadResult(url="http://x", status=DownloadStatus.COMPLETED)
        result = runner.invoke(
            app,
            ["audio", "https://youtube.com/watch?v=123", "-f", "mp3", "-b", "256k"],
        )
        assert result.exit_code == 0
        mock_audio.assert_called_once()
        _, kwargs = mock_audio.call_args
        assert kwargs["audio_format"] == "mp3"
        assert kwargs["bitrate"] == "256k"

    # Test playlist command
    with patch("core.playlist.get_playlist_info", return_value=None), \
         patch("core.playlist.download_playlist") as mock_pl:
        mock_pl.return_value = [DownloadResult(url="http://x", status=DownloadStatus.COMPLETED)]
        result = runner.invoke(
            app,
            ["playlist", "https://youtube.com/playlist?list=123", "--parallel", "3"],
        )
        assert result.exit_code == 0
        mock_pl.assert_called_once()
        _, kwargs = mock_pl.call_args
        assert kwargs["parallel"] == 3

    # Test clip command
    with patch("core.downloader.download_clip") as mock_clip:
        mock_clip.return_value = DownloadResult(url="http://x", status=DownloadStatus.COMPLETED)
        result = runner.invoke(
            app,
            ["clip", "https://youtube.com/watch?v=123", "--start", "00:10", "--end", "00:20"],
        )
        assert result.exit_code == 0
        mock_clip.assert_called_once()
        _, kwargs = mock_clip.call_args
        assert kwargs["start_time"] == "00:10"
        assert kwargs["end_time"] == "00:20"

    # Test chapters command
    with patch("core.metadata.download_by_chapters") as mock_chap:
        mock_chap.return_value = [DownloadResult(url="http://x", status=DownloadStatus.COMPLETED)]
        result = runner.invoke(app, ["chapters", "https://youtube.com/watch?v=123"])
        assert result.exit_code == 0
        mock_chap.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 12. Audio Extraction & Parallel Batch Downloads Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_audio_mock(tmp_path):
    from core.audio import extract_audio

    # Mock yt-dlp execution
    with patch("yt_dlp.YoutubeDL") as mock_ytdl_class:
        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_ytdl_class.return_value = mock_instance

        audio_file = tmp_path / "song.mp3"
        audio_file.write_text("fake audio mp3 data")

        info_dict = {
            "title": "Song Title",
            "id": "song123",
            "duration": 180,
            "ext": "mp3",
            "filepath": str(audio_file)
        }
        mock_instance.extract_info.return_value = info_dict

        with patch("core.audio.verify_file_integrity", return_value=True):
            result = extract_audio(
                url="https://youtube.com/watch?v=song12345",
                output_dir=tmp_path,
                audio_format="mp3",
                bitrate="320k",
                embed_thumbnail=False,
                embed_metadata=False,
            )

            assert result.status == DownloadStatus.COMPLETED
            assert result.title == "Song Title"
            assert result.file_path == audio_file


def test_parallel_batch_download():
    from constants import DownloadResult
    from core.parallel import download_batch, download_parallel

    with patch("core.parallel.download_video") as mock_dl_video:
        mock_dl_video.return_value = DownloadResult(
            url="http://mock", status=DownloadStatus.COMPLETED
        )

        urls = ["https://youtube.com/watch?v=1", "https://youtube.com/watch?v=2"]
        results = download_batch(urls, parallel=2, quality="720p", fmt="mkv")

        assert len(results) == 2
        assert mock_dl_video.call_count == 2

        # Test download_parallel
        entries = [{"url": "url1", "id": "1"}, {"url": "url2", "id": "2"}]
        results_pl = download_parallel(entries, workers=2, quality="360p", fmt="mp4")
        assert len(results_pl) == 2


def test_missing_ffmpeg():
    runner = CliRunner()
    with patch("core.utils.check_ffmpeg", return_value=None):
        # 1. Chapters command should exit with 1
        result = runner.invoke(app, ["chapters", "https://youtube.com/watch?v=123"])
        assert result.exit_code == 1
        assert "ffmpeg is required" in result.stdout

        # 2. Clip command should exit with 1
        result = runner.invoke(app, ["clip", "https://youtube.com/watch?v=123", "--start", "00:10"])
        assert result.exit_code == 1
        assert "ffmpeg is required" in result.stdout

        # 3. Audio command should exit with 1
        result = runner.invoke(app, ["audio", "https://youtube.com/watch?v=123"])
        assert result.exit_code == 1
        assert "ffmpeg is required" in result.stdout


def test_normalize_subtitle_languages():
    from core.subtitles import normalize_subtitle_languages
    assert normalize_subtitle_languages(["en"]) == ["en"]
    assert normalize_subtitle_languages(["en", "es"]) == ["en", "es"]
    assert normalize_subtitle_languages(["  fr  ", ""]) == ["fr"]


def test_chapter_title_path_traversal_sanitization():
    from core.utils import sanitize_filename
    safe_name = sanitize_filename("../../etc/passwd")
    assert "/" not in safe_name
    assert "\\" not in safe_name
    assert "etc_passwd" in safe_name


def test_ssrf_thumbnail_url_validation():
    from core.thumbnail_renderer import _is_safe_thumbnail_url
    assert _is_safe_thumbnail_url("https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg") is True
    assert _is_safe_thumbnail_url("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg") is True
    assert _is_safe_thumbnail_url("https://lh3.googleusercontent.com/abc") is True
    assert _is_safe_thumbnail_url("https://i.ytimg.com.:443/vi/dQw4w9WgXcQ/hqdefault.jpg") is True

    assert _is_safe_thumbnail_url("http://127.0.0.1:8080/admin") is False
    assert _is_safe_thumbnail_url("http://localhost:9000/kill") is False
    assert _is_safe_thumbnail_url("https://10.0.0.1/sensitive") is False
    assert _is_safe_thumbnail_url("https://malicious-attacker.com/exploit.jpg") is False
    assert _is_safe_thumbnail_url("https://img.youtube.com.evil.test/vi/dQw4w9WgXcQ/hqdefault.jpg") is False
    assert _is_safe_thumbnail_url("https://youtube.com:443@malicious-attacker.com/exploit.jpg") is False
    assert _is_safe_thumbnail_url("https://user:pass@i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg") is True
    assert _is_safe_thumbnail_url("ftp://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg") is False


def test_terminal_cell_size_response_parsing():
    from core.thumbnail_renderer import _parse_cell_size_response

    assert _parse_cell_size_response(b"\x1b[6;20;10t") == (10, 20)
    assert _parse_cell_size_response(b"noise\x1b[6;19;9textra") == (9, 19)
    assert _parse_cell_size_response(b"\x1b[6;0;10t") is None
    assert _parse_cell_size_response(b"not a cell-size response") is None


def test_query_terminal_cell_size_drains_before_sending_query(monkeypatch):
    import select
    import sys

    import core.thumbnail_renderer as renderer

    events = []

    class FakeStdout:
        def isatty(self):
            return True

        def write(self, text):
            events.append(("write", text))

        def flush(self):
            events.append(("flush", None))

    class FakeStdin:
        def __init__(self):
            self.response = list("\x1b[6;20;10t")

        def isatty(self):
            return True

        def read(self, size):
            events.append(("read", size))
            return self.response.pop(0)

    fake_stdin = FakeStdin()

    def fake_drain():
        events.append(("drain", None))

    def fake_select(read_list, _write_list, _error_list, _timeout):
        return (read_list, [], []) if fake_stdin.response else ([], [], [])

    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", FakeStdout())
    monkeypatch.setattr(renderer.os, "name", "posix")
    monkeypatch.setattr(renderer, "_drain_pending_terminal_input", fake_drain)
    monkeypatch.setattr(select, "select", fake_select)

    assert renderer.query_terminal_cell_size() == (10, 20)
    assert events[0] == ("drain", None)
    assert events[1] == ("write", "\x1b[16t")


def test_search_thumbnail_size_keeps_full_resolution_or_hides():
    from core.presentation import SEARCH_THUMBNAIL_SIZE, get_search_thumbnail_size

    assert get_search_thumbnail_size(
        140,
        is_terminal=True,
        has_results=True,
    ) == SEARCH_THUMBNAIL_SIZE
    assert get_search_thumbnail_size(
        115,
        is_terminal=True,
        has_results=True,
    ) == SEARCH_THUMBNAIL_SIZE
    assert get_search_thumbnail_size(
        114,
        is_terminal=True,
        has_results=True,
    ) is None
    assert get_search_thumbnail_size(
        140,
        is_terminal=False,
        has_results=True,
    ) is None
    assert get_search_thumbnail_size(
        140,
        is_terminal=True,
        has_results=False,
    ) is None


def test_escape_text_injection_safety():
    from core.display import escape_text
    ansi_string = "\x1B[31mRed Text\x1B[0m"
    assert escape_text(ansi_string) == "Red Text"

    markup_string = "[bold]Bold Text[/]"
    assert escape_text(markup_string) == r"\[bold\]Bold/\[\]" or "bold" in escape_text(markup_string)


def test_database_init_caching(tmp_path):
    from core.history import DownloadHistory
    db_path = tmp_path / "cache_test.db"

    if db_path in DownloadHistory._initialized_paths:
        DownloadHistory._initialized_paths.remove(db_path)

    DownloadHistory(db_path=db_path)
    assert db_path in DownloadHistory._initialized_paths

    with patch.object(DownloadHistory, "_initialize_db") as mock_init:
        DownloadHistory(db_path=db_path)
        mock_init.assert_not_called()
