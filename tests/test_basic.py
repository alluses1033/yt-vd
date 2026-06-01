from constants import DownloadStatus, VideoFormat
from core.config import AppConfig
from core.quality import resolve_format_string
from core.utils import detect_url_type, format_duration, format_file_size, validate_url


def test_url_validation():
    assert validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert validate_url("https://youtu.be/dQw4w9WgXcQ") is True
    assert validate_url("https://youtube.com/playlist?list=PL385A53B7C19C179A") is True
    assert validate_url("https://www.youtube.com/embed/dQw4w9WgXcQ") is True
    assert validate_url("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share") is True
    assert validate_url("https://www.youtube.com/@somechannel/videos") is True
    assert validate_url("https://not-youtube.com/watch?v=123") is False
    assert validate_url("https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ") is False

def test_url_type_detection():
    assert detect_url_type("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "video"
    assert detect_url_type("https://youtube.com/playlist?list=PL3") == "playlist"
    assert detect_url_type("https://youtube.com/shorts/12345") == "shorts"
    assert detect_url_type("https://youtube.com/@somechannel") == "channel"
    assert detect_url_type("https://not-youtube.com") == "unknown"

def test_formatting():
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "1:01:05"
    assert format_file_size(1024) == "1.00 KiB"
    assert format_file_size(1024 * 1024 * 5) == "5.00 MiB"

def test_quality_resolver():
    assert "height<=1080" in resolve_format_string("high")
    assert "height<=720" in resolve_format_string("720p")
    # Raw format strings are passed through with fallback appended
    assert resolve_format_string("bestvideo+bestaudio") == "bestvideo+bestaudio/best"

def test_config():
    config = AppConfig()
    assert config.format == VideoFormat.MP4
    assert config.parallel_workers > 0

    # Test dictionary conversion
    d = config.to_dict()
    assert d["format"] == "mp4"

    # Test from dict
    config2 = AppConfig.from_dict({"format": "mkv", "unknown_key": 123})
    assert config2.format == "mkv"


def test_history(tmp_path):
    from constants import DownloadResult
    from core.history import DownloadHistory

    # Create history DB in temporary path
    db_path = tmp_path / "test_history.db"
    history = DownloadHistory(db_path=db_path)

    # Insert a dummy record
    res = DownloadResult(
        url="https://youtube.com/watch?v=123",
        title="Test Video",
        status=DownloadStatus.COMPLETED,
        file_size=1024 * 1024,
        quality="1080p",
        format="mp4",
        duration=120.0,
    )
    history.add(res)

    # Query history
    assert history.exists("https://youtube.com/watch?v=123") is True
    assert history.exists("https://youtube.com/watch?v=456") is False

    entries = history.get_all(limit=10)
    assert len(entries) == 1
    assert entries[0]["title"] == "Test Video"
    assert entries[0]["quality"] == "1080p"

    # Get stats
    stats = history.get_stats()
    assert stats["total_count"] == 1
    assert stats["total_size"] == 1024 * 1024

    # Clear history
    history.clear()
    assert len(history.get_all()) == 0
