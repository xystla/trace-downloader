from pathlib import Path
from unittest.mock import patch, MagicMock
from trace_grabber.download import build_ffmpeg_cmd, download

def test_build_cmd_basic():
    cmd = build_ffmpeg_cmd("https://x/v.m3u8", Path("/out/a.mp4"), headers={})
    assert cmd[0] == "ffmpeg"
    assert "https://x/v.m3u8" in cmd
    assert str(Path("/out/a.mp4")) in cmd
    assert "copy" in cmd

def test_build_cmd_includes_headers():
    cmd = build_ffmpeg_cmd("https://x/v.m3u8", Path("/out/a.mp4"),
                           headers={"Cookie": "sid=1", "Referer": "https://x"})
    joined = " ".join(cmd)
    assert "Cookie: sid=1" in joined
    assert "Referer: https://x" in joined

def test_download_raises_on_nonzero(tmp_path):
    with patch("trace_grabber.download.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stderr="boom")
        try:
            download("https://x/v.m3u8", tmp_path / "a.mp4", headers={})
            assert False, "should have raised"
        except RuntimeError as e:
            assert "ffmpeg" in str(e)

def test_cmd_has_progress_flags_when_streaming():
    from pathlib import Path
    cmd = build_ffmpeg_cmd("https://x/v.m3u8", Path("/o/a.mp4"), headers={}, stream_progress=True)
    assert "-progress" in cmd and "pipe:1" in cmd and "-nostats" in cmd

def test_cmd_no_progress_flags_by_default():
    from pathlib import Path
    cmd = build_ffmpeg_cmd("https://x/v.m3u8", Path("/o/a.mp4"), headers={})
    assert "-progress" not in cmd
