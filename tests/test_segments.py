from pathlib import Path

from trace_grabber import segments

PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION:2
#EXTINF:2.000000,
video_3000k000.ts
#EXTINF:2.000000,
video_3000k001.ts
#EXTINF:2.000000,
https://cdn.example/abs/video_3000k002.ts
#EXTINF:1.500000,
video_3000k003.ts
#EXT-X-ENDLIST
"""
BASE = "https://go.traceup.com/x/gamevideo1.hls/game_video_3000k.m3u8"


def test_playlist_is_read_as_timed_pieces_with_full_addresses():
    assert segments.parse(PLAYLIST, BASE) == [
        (2.0, "https://go.traceup.com/x/gamevideo1.hls/video_3000k000.ts"),
        (2.0, "https://go.traceup.com/x/gamevideo1.hls/video_3000k001.ts"),
        (2.0, "https://cdn.example/abs/video_3000k002.ts"),
        (1.5, "https://go.traceup.com/x/gamevideo1.hls/video_3000k003.ts")]


def test_window_takes_only_the_pieces_that_cover_the_moment():
    pieces = [(2.0, f"s{i}") for i in range(10)]           # 0-2, 2-4, ... 18-20 seconds
    assert segments.window(pieces, start=5, length=4) == ["s2", "s3", "s4"]     # 5s..9s
    assert segments.window(pieces, start=4, length=2) == ["s2"]                 # exactly one piece
    assert segments.window(pieces, start=19, length=30) == ["s9"]               # runs past the end
    assert segments.window(pieces, start=40, length=5) == []


class _FakeFfmpeg:
    """Stands in for the ffmpeg process: prints progress lines, writes the output file."""
    started = []

    def __init__(self, cmd, returncode=0, lines=()):
        self.cmd, self.returncode = cmd, returncode
        self.list_text = Path(cmd[cmd.index("-i") + 1]).read_text()
        self.stdout = iter(lines)
        Path(cmd[-1]).write_bytes(b"video" if returncode == 0 else b"half")
        _FakeFfmpeg.started.append(self)

    def wait(self):
        return self.returncode


def fake_ffmpeg(monkeypatch, **kwargs):
    _FakeFfmpeg.started = []
    monkeypatch.setattr(segments.subprocess, "Popen", lambda cmd, **kw: _FakeFfmpeg(cmd, **kwargs))
    return _FakeFfmpeg


def test_download_joins_the_pieces_end_to_end(tmp_path, monkeypatch):
    fake = fake_ffmpeg(monkeypatch)
    dest = tmp_path / "folder" / "clip.mp4"
    segments.download(["https://x/a.ts", "https://x/b.ts"], dest, total_secs=4)
    (proc,) = fake.started
    assert dest.read_bytes() == b"video"
    assert proc.cmd[proc.cmd.index("-f") + 1] == "concat"
    assert proc.list_text.splitlines() == ["file 'https://x/a.ts'", "file 'https://x/b.ts'"]


def test_download_reports_progress_as_a_share_of_the_length(tmp_path, monkeypatch):
    fake = fake_ffmpeg(monkeypatch, lines=["out_time=00:00:01.000000\n", "progress=continue\n",
                                           "out_time=00:00:03.000000\n", "progress=continue\n"])
    seen, procs = [], []
    segments.download(["https://x/a.ts", "https://x/b.ts"], tmp_path / "p.mp4", total_secs=4,
                      progress_cb=seen.append, on_proc=procs.append)
    assert seen == [25, 75, 100]
    assert procs == fake.started          # so a Stop can end the process


def test_failed_download_leaves_no_partial_file(tmp_path, monkeypatch):
    fake_ffmpeg(monkeypatch, returncode=1)
    try:
        segments.download(["https://x/a.ts"], tmp_path / "clip.mp4", total_secs=2)
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
    assert list(tmp_path.iterdir()) == []
