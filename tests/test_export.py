import sys
from pathlib import Path

import pytest

from trace_grabber import export
from trace_grabber.export import Piece

INFO = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'game.mp4':
  Duration: 01:14:40.13, start: 0.000000, bitrate: 5183 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 5050 kb/s, 30 fps, 30 tbr, 90k tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, mono, fltp, 125 kb/s (default)
At least one output file must be specified
"""


def _ffmpeg_says(monkeypatch, text):
    monkeypatch.setattr(export.subprocess, "run", lambda cmd, **kwargs: type("R", (), {"stderr": text, "returncode": 1})())


def test_a_videos_facts_are_read_from_ffmpeg(monkeypatch):
    _ffmpeg_says(monkeypatch, INFO)
    assert export.video_info("game.mp4") == {"duration": 4480.13, "width": 1920, "height": 1080, "bitrate": 5183, "audio": True}
    _ffmpeg_says(monkeypatch, INFO.replace("  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, mono, fltp, 125 kb/s (default)\n", "")
                 .replace("1920x1080", "1280x720"))
    silent = export.video_info("game.mp4")
    assert (silent["audio"], silent["width"], silent["height"]) == (False, 1280, 720)
    _ffmpeg_says(monkeypatch, "game.mp4: No such file or directory")
    with pytest.raises(RuntimeError, match="couldn't be read"):
        export.video_info("game.mp4")


def test_each_stretch_of_play_is_a_piece_that_fades_only_at_a_break():
    made = export.pieces([(10, 610), (700, 1300), (1400, 1500)], [("game.mp4", 5000)])
    assert made == [Piece(Path("game.mp4"), 10, 600, False, True),
                    Piece(Path("game.mp4"), 700, 600, True, True),
                    Piece(Path("game.mp4"), 1400, 100, True, False)]


def test_a_stretch_that_crosses_the_join_of_two_half_files_is_split_without_a_fade():
    files = [("h1.mp4", 1500), ("h2.mp4", 1600)]
    made = export.pieces([(100, 1400), (1450, 1700), (1800, 3000)], files)
    assert made == [Piece(Path("h1.mp4"), 100, 1300, False, True),
                    Piece(Path("h1.mp4"), 1450, 50, True, False),              # runs up to the join…
                    Piece(Path("h2.mp4"), 0, 200, False, True),                # …and carries on in the next file
                    Piece(Path("h2.mp4"), 300, 1200, True, False)]


LAY = {"x": 60, "y": 48, "width": 418, "height": 46,
       "clock": {"slots": [19, 35, 46, 57, 73], "y": 23, "size": 27, "color": "#1c1226"}}
PIECES = [Piece(Path("/v/game.mp4"), 10, 600, False, True), Piece(Path("/v/game.mp4"), 700, 600, True, False)]
PLATES = [("plate0.png", 0, 290), ("plate1.png", 290, 1201)]


def test_the_graph_fades_joins_overlays_and_writes_the_clock():
    script = export.filter_script(PIECES, PLATES, LAY, "font.ttf")
    lines = script.strip().split(";\n")
    assert lines[0] == "[0:v]fade=t=out:st=599.500:d=0.5,setsar=1[v0]"
    assert lines[1] == "[0:a]afade=t=out:st=599.500:d=0.5[a0]"
    assert lines[2] == "[1:v]fade=t=in:st=0:d=0.5,setsar=1[v1]" and lines[3] == "[1:a]afade=t=in:st=0:d=0.5[a1]"
    assert lines[4] == "[v0][a0][v1][a1]concat=n=2:v=1:a=1[cv][ca]"
    assert lines[5] == "[cv][2:v]overlay=60:48:enable='between(t,0.000,290.000)'[o0]"
    assert lines[6] == "[o0][3:v]overlay=60:48:enable='between(t,290.000,1201.000)'[o1]"
    clock = lines[7]
    assert clock.startswith("[o1]drawtext=") and clock.endswith("[out]") and clock.count("drawtext=") == 5
    assert "fontfile=font.ttf" in clock and "fontsize=27" in clock and "fontcolor=0x1c1226" in clock
    assert r"text='%{eif\:floor(t/600)\:d}':x=79-text_w/2:y=71-text_h/2" in clock          # tens of minutes, first slot
    assert r"text='%{eif\:mod(floor(t/60)\,10)\:d}':x=95-text_w/2" in clock
    assert r"text='\:':x=106-text_w/2" in clock
    assert r"text='%{eif\:floor(mod(t\,60)/10)\:d}':x=117-text_w/2" in clock
    assert r"text='%{eif\:mod(floor(t)\,10)\:d}':x=133-text_w/2" in clock


def test_a_piece_with_nothing_to_fade_and_a_video_with_no_sound():
    script = export.filter_script([Piece(Path("/v/g.mp4"), 5, 60, False, False)], [("plate0.png", 0, 61)], LAY, "font.ttf", audio=False)
    lines = script.strip().split(";\n")
    assert lines[0] == "[0:v]setsar=1[v0]" and lines[1] == "[v0]concat=n=1:v=1:a=0[cv]"
    assert "[0:a]" not in script and "[ca]" not in script


def test_the_command_for_the_best_quality():
    cmd = export.build_cmd(PIECES, ["plate0.png", "plate1.png"], Path("/out/game (edited).part.mp4"), "best")
    assert cmd[:3] == ["ffmpeg", "-y", "-hide_banner"]
    assert cmd[3:9] == ["-ss", "10.000", "-t", "600.000", "-i", str(Path("/v/game.mp4"))]
    assert cmd[9:15] == ["-ss", "700.000", "-t", "600.000", "-i", str(Path("/v/game.mp4"))]
    assert cmd[15:19] == ["-i", "plate0.png", "-i", "plate1.png"]
    assert cmd[19:25] == ["-filter_complex_script", "graph.txt", "-map", "[out]", "-map", "[ca]"]
    assert cmd[25:33] == ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p"]
    assert cmd[33:] == ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
                        str(Path("/out/game (edited).part.mp4"))]


def test_the_faster_quality_uses_the_macs_video_hardware_and_plain_speed_elsewhere(monkeypatch):
    monkeypatch.setattr(export.sys, "platform", "darwin")
    mac = export.build_cmd(PIECES, ["plate0.png"], Path("/o.mp4"), "faster", bitrate=5183)
    assert mac[mac.index("-c:v"):mac.index("-c:a")] == ["-c:v", "h264_videotoolbox", "-b:v", "6737k", "-pix_fmt", "yuv420p"]
    monkeypatch.setattr(export.sys, "platform", "win32")
    win = export.build_cmd(PIECES, ["plate0.png"], Path("/o.mp4"), "faster", bitrate=5183)
    assert win[win.index("-c:v"):win.index("-c:a")] == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    silent = export.build_cmd(PIECES, ["plate0.png"], Path("/o.mp4"), "best", audio=False)
    assert "[ca]" not in silent and "-c:a" not in silent


class _Ffmpeg:
    def __init__(self, lines, code):
        self.stdout, self.returncode, self._code = iter(lines), None, code
    def wait(self):
        self.returncode = self._code
        return self._code


def test_progress_follows_the_exported_time(monkeypatch, tmp_path):
    lines = ["out_time=00:00:30.000000\n", "progress=continue\n", "out_time=00:01:00.000000\n", "progress=end\n"]
    started = []
    def popen(cmd, **kwargs):
        started.append((cmd, kwargs["cwd"]))
        return _Ffmpeg(lines, 0)
    monkeypatch.setattr(export.subprocess, "Popen", popen)
    seen, procs = [], []
    export.run(["ffmpeg", "x"], 120, tmp_path, progress_cb=lambda pct, done: seen.append((pct, done)), on_proc=procs.append)
    assert seen == [(25, 30.0), (50, 60.0)] and len(procs) == 1 and started[0][1] == str(tmp_path)


def test_an_export_that_fails_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(export.subprocess, "Popen", lambda cmd, **kwargs: _Ffmpeg([], 1))
    with pytest.raises(RuntimeError, match="The export didn't finish"):
        export.run(["ffmpeg", "x"], 120, tmp_path)


PROJECT = {"home": {"name": "T", "code": "TIG", "color": "#16a05a"}, "away": {"name": "B", "code": "BLU", "color": "#1e5ac8"},
           "marks": [{"id": "a", "kind": "start", "t": 10}, {"id": "b", "kind": "break", "t": 610},
                     {"id": "c", "kind": "resume", "t": 700}, {"id": "d", "kind": "goal_home", "t": 300},
                     {"id": "e", "kind": "end", "t": 1300}]}


def _fake_export(monkeypatch, outcome="ok", height=1080):
    """video_info and run replaced; `ran` records what run was given and what was in its folder."""
    ran = {}
    monkeypatch.setattr(export, "video_info", lambda path: {"duration": 5000.0, "width": height * 16 // 9, "height": height,
                                                           "bitrate": 5183, "audio": True})
    def run(cmd, total, cwd, progress_cb=None, on_proc=None):
        ran.update(cmd=cmd, total=total, files=sorted(p.name for p in Path(cwd).iterdir()),
                   graph=(Path(cwd) / "graph.txt").read_text(), plate_size=None)
        from PIL import Image
        ran["plate_size"] = Image.open(Path(cwd) / "plate0.png").size
        if outcome == "fail":
            Path(cmd[-1]).write_bytes(b"half a vid")
            raise RuntimeError("The export didn't finish.")
        Path(cmd[-1]).write_bytes(b"the edited game")
    monkeypatch.setattr(export, "run", run)
    return ran


def test_an_export_cuts_the_breaks_and_changes_the_plate_at_each_goal(monkeypatch, tmp_path):
    ran = _fake_export(monkeypatch)
    dest = tmp_path / "Edited" / "game (edited).mp4"
    export.export(PROJECT, ["/v/game.mp4"], dest, "best")
    assert dest.read_bytes() == b"the edited game" and [p.name for p in dest.parent.iterdir()] == ["game (edited).mp4"]
    assert ran["total"] == 1200 and ran["files"] == ["font.ttf", "graph.txt", "plate0.png", "plate1.png"]
    assert "between(t,0.000,290.000)" in ran["graph"] and "between(t,290.000,1201.000)" in ran["graph"]
    assert ran["cmd"][-1].endswith("game (edited).part.mp4") and Path(ran["cmd"][-1]).is_absolute()
    assert ran["plate_size"] == (418, 46)


def test_the_bug_is_scaled_for_a_smaller_picture(monkeypatch, tmp_path):
    ran = _fake_export(monkeypatch, height=720)
    export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out.mp4")
    assert ran["plate_size"] == (279, 31) and "overlay=40:32" in ran["graph"] and "fontsize=18" in ran["graph"]


def test_a_failed_export_leaves_no_file_and_keeps_the_earlier_one(monkeypatch, tmp_path):
    _fake_export(monkeypatch, outcome="fail")
    dest = tmp_path / "game (edited).mp4"
    dest.write_bytes(b"last week's export")
    with pytest.raises(RuntimeError):
        export.export(PROJECT, ["/v/game.mp4"], dest)
    assert dest.read_bytes() == b"last week's export" and [p.name for p in tmp_path.iterdir()] == ["game (edited).mp4"]


def test_marks_that_do_not_make_sense_are_never_exported(monkeypatch, tmp_path):
    ran = _fake_export(monkeypatch)
    broken = {**PROJECT, "marks": [m for m in PROJECT["marks"] if m["kind"] != "end"]}
    with pytest.raises(RuntimeError, match="Mark where the game ends."):
        export.export(broken, ["/v/game.mp4"], tmp_path / "out.mp4")
    assert ran == {} and list(tmp_path.iterdir()) == []


def test_the_faster_quality_never_starves_the_picture(monkeypatch, tmp_path):
    # A source with a very low bitrate (little detail) still gets enough for the
    # score bug's lettering to stay sharp.
    monkeypatch.setattr(export.sys, "platform", "darwin")
    ran = _fake_export(monkeypatch)
    monkeypatch.setattr(export, "video_info", lambda path: {"duration": 5000.0, "width": 1920, "height": 1080,
                                                           "bitrate": 232, "audio": True})
    export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out.mp4", "faster")
    asked = int(ran["cmd"][ran["cmd"].index("-b:v") + 1].rstrip("k"))
    assert 4000 <= asked <= 5000                        # about 0.07 bits a pixel a frame at 1080 lines
    monkeypatch.setattr(export, "video_info", lambda path: {"duration": 5000.0, "width": 1920, "height": 1080,
                                                           "bitrate": 5183, "audio": True})
    export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out2.mp4", "faster")
    assert ran["cmd"][ran["cmd"].index("-b:v") + 1] == "6737k"      # a normal source: 1.3 times its own
