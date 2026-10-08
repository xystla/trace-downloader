import sys
from pathlib import Path

import pytest

from trace_grabber import scorebug, export
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
    assert export.video_info("game.mp4") == {"duration": 4480.13, "width": 1920, "height": 1080, "bitrate": 5183,
                                             "audio": True, "fps": 30.0}
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
    script = export.filter_script(PIECES, PLATES, LAY, "font.ttf", size=(1920, 1080), fps=30.0)
    lines = script.strip().split(";\n")
    assert lines[0] == "[0:v]fps=30,scale=1920:1080,format=yuv420p,setsar=1,fade=t=out:st=599.500:d=0.5[v0]"
    assert lines[1] == "[0:a]afade=t=out:st=599.500:d=0.5[a0]"
    assert lines[2] == "[1:v]fps=30,scale=1920:1080,format=yuv420p,setsar=1,fade=t=in:st=0:d=0.5[v1]"
    assert lines[3] == "[1:a]afade=t=in:st=0:d=0.5[a1]"
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


def test_an_untouched_picture_is_left_alone():
    assert export.grade_filter(None) == "" == export.grade_filter({"exposure": 0, "contrast": 0, "saturation": 0})
    script = export.filter_script(PIECES, PLATES, LAY, "font.ttf", grade={"exposure": 0, "contrast": 0, "saturation": 0})
    assert "lutyuv" not in script and "[cv][2:v]overlay=" in script


def test_the_picture_is_graded_before_the_bug_goes_on():
    lines = export.filter_script(PIECES, PLATES, LAY, "font.ttf", grade={"exposure": 100, "contrast": 0, "saturation": 0}).strip().split(";\n")
    assert lines[5].startswith("[cv]lutyuv=") and lines[5].endswith("[gv]")
    assert lines[6].startswith("[gv][2:v]overlay=60:48")                  # so the bug keeps its own colours


def _lut(grade):
    """What the grade does to a luma value and a chroma value, worked out from the filter's own formulas."""
    text = export.grade_filter(grade)
    parts = dict(p.split("=", 1) for p in text[len("lutyuv="):].replace("'", "").split(":"))
    clip = lambda v, lo, hi: max(lo, min(hi, v))
    run = lambda formula, val: eval(formula, {"val": val, "clip": clip})
    return (lambda y: run(parts["y"], y)), (lambda c: run(parts["u"], c)), parts


def test_exposure_contrast_and_saturation_do_what_they_say():
    luma, chroma, parts = _lut({"exposure": 100, "contrast": 0, "saturation": 0})          # one stop brighter
    assert parts["u"] == parts["v"] and luma(16) == 16 and abs(luma(66) - 116) < 0.01 and luma(200) == 235
    assert abs(chroma(138) - 148) < 0.01 and chroma(128) == 128                           # colours brighten with it
    luma, chroma, _ = _lut({"exposure": -100, "contrast": 0, "saturation": 0})
    assert abs(luma(116) - 66) < 0.01
    luma, chroma, _ = _lut({"exposure": 0, "contrast": 100, "saturation": 0})              # half as much contrast again
    assert abs(luma(125.5) - 125.5) < 0.01 and abs(luma(165.5) - 185.5) < 0.01 and abs(luma(85.5) - 65.5) < 0.01
    luma, chroma, _ = _lut({"exposure": 0, "contrast": -100, "saturation": 0})
    assert abs(luma(16) - 70.75) < 0.01                                                    # blacks lift, as on the page
    luma, chroma, _ = _lut({"exposure": 0, "contrast": 0, "saturation": 100})              # twice the colour
    assert luma(100) == 100 and abs(chroma(148) - 168) < 0.01 and chroma(250) == 240
    luma, chroma, _ = _lut({"exposure": 0, "contrast": 0, "saturation": -100})             # none: black and white
    assert chroma(200) == 128 and chroma(40) == 128


def test_sharpening_is_applied_to_the_picture_after_its_colour():
    assert export.grade_filter({"sharpen": 0}) == ""
    assert export.grade_filter({"sharpen": 100}) == "unsharp=5:5:1.500:5:5:0"
    assert export.grade_filter({"sharpen": 40}) == "unsharp=5:5:0.600:5:5:0"                 # the picture's detail, not its colour
    both = export.grade_filter({"exposure": 100, "sharpen": 50})
    assert both.startswith("lutyuv=") and both.endswith(",unsharp=5:5:0.750:5:5:0")
    lines = export.filter_script(PIECES, PLATES, LAY, "font.ttf", grade={"sharpen": 50}).strip().split(";\n")
    assert lines[5] == "[cv]unsharp=5:5:0.750:5:5:0[gv]" and lines[6].startswith("[gv][2:v]overlay=")      # the bug stays as drawn


def test_the_bug_slides_in_at_the_start_and_out_at_the_end():
    lay = {**LAY, "slide": [0.6, 0.5]}
    lines = export.filter_script(PIECES, PLATES, lay, "font.ttf", total=1200.0).strip().split(";\n")
    # It comes from off the left edge (60 + 418 away) as the game starts, and leaves that way in the last half second.
    move = "478*(pow(max(0,1-t/0.6),3)+pow(clip((t-1199.500)/0.5,0,1),3))"
    assert lines[5] == f"[cv][2:v]overlay=x='60-{move}':y=48:enable='between(t,0.000,290.000)'[o0]"
    assert lines[6] == f"[o0][3:v]overlay=x='60-{move}':y=48:enable='between(t,290.000,1201.000)'[o1]"
    assert lines[7].count(f"-text_w/2-{move}'") == 5 and f"x='79-text_w/2-{move}':y=71-text_h/2" in lines[7]
    # Not when the edit says no, when the length isn't known, or when there is hardly any game.
    for still in (export.filter_script(PIECES, PLATES, {**LAY, "slide": None}, "font.ttf", total=1200.0),
                  export.filter_script(PIECES, PLATES, lay, "font.ttf"),
                  export.filter_script(PIECES, PLATES, lay, "font.ttf", total=2.0)):
        assert "pow(" not in still and "overlay=60:48:enable=" in still and ":x=79-text_w/2:y=71" in still


def test_a_piece_with_nothing_to_fade_and_a_video_with_no_sound():
    script = export.filter_script([Piece(Path("/v/g.mp4"), 5, 60, False, False)], [("plate0.png", 0, 61)], LAY, "font.ttf",
                                  size=(1280, 720), fps=29.97, audio=False)
    lines = script.strip().split(";\n")
    assert lines[0] == "[0:v]fps=29.97,scale=1280:720,format=yuv420p,setsar=1[v0]" and lines[1] == "[v0]concat=n=1:v=1:a=0[cv]"
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
    def poll(self):
        return self.returncode
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
                                                           "bitrate": 5183, "audio": True, "fps": 30.0})
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
    assert ran["plate_size"] == scorebug.size(PROJECT["home"], PROJECT["away"])


def test_the_bug_is_scaled_for_a_smaller_picture(monkeypatch, tmp_path):
    ran = _fake_export(monkeypatch, height=720)
    export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out.mp4")
    assert ran["plate_size"] == scorebug.size(PROJECT["home"], PROJECT["away"], 720 / 1080) and ran["plate_size"][1] == 38
    assert "overlay=x='40-" in ran["graph"] and ":y=32:enable=" in ran["graph"] and "fontsize=24" in ran["graph"]


def test_the_export_uses_the_edit_own_size_and_typeface(monkeypatch, tmp_path):
    ran = _fake_export(monkeypatch)
    styled = {**PROJECT, "bug": {"size": 1.5, "font": "anton"}}
    def run(cmd, total, cwd, progress_cb=None, on_proc=None, keep=export.run):
        ran["font"] = (Path(cwd) / "font.ttf").read_bytes()
        keep(cmd, total, cwd, progress_cb, on_proc)
    monkeypatch.setattr(export, "run", run)
    export.export(styled, ["/v/game.mp4"], tmp_path / "out.mp4")
    lay = scorebug.layout(1.0, PROJECT["home"], PROJECT["away"], styled["bug"])
    assert ran["font"] == scorebug.font_path("anton").read_bytes()
    assert ran["plate_size"] == (lay["width"], lay["height"]) and lay["height"] == 86
    assert f"fontsize={lay['clock']['size']}" in ran["graph"] and f"x='{60 + lay['clock']['slots'][0]}-text_w/2-" in ran["graph"]
    assert "(t-1199.500)/0.5" in ran["graph"]                             # the bug leaves as the 1200 seconds of play end
    export.export({**styled, "bug": {**styled["bug"], "animate": False}}, ["/v/game.mp4"], tmp_path / "still.mp4")
    assert "pow(" not in ran["graph"] and "lutyuv" not in ran["graph"]
    export.export({**styled, "grade": {"exposure": 20, "contrast": 10, "saturation": 30}}, ["/v/game.mp4"], tmp_path / "graded.mp4")
    assert "[cv]lutyuv=" in ran["graph"]


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
                                                           "bitrate": 232, "audio": True, "fps": 30.0})
    export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out.mp4", "faster")
    asked = int(ran["cmd"][ran["cmd"].index("-b:v") + 1].rstrip("k"))
    assert 4000 <= asked <= 5000                        # about 0.07 bits a pixel a frame at 1080 lines
    monkeypatch.setattr(export, "video_info", lambda path: {"duration": 5000.0, "width": 1920, "height": 1080,
                                                           "bitrate": 5183, "audio": True, "fps": 30.0})
    export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out2.mp4", "faster")
    assert ran["cmd"][ran["cmd"].index("-b:v") + 1] == "6737k"      # a normal source: 1.3 times its own


class _Running:
    """An ffmpeg that is still going: it only ends when it is told to."""
    def __init__(self, lines=()):
        self.stdout, self.returncode, self.ended = iter(lines), None, []
    def poll(self):
        return self.returncode
    def terminate(self):
        self.ended.append("terminated")
        self.returncode = -15
    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else 0


def test_ffmpeg_is_never_left_running_when_following_it_fails(monkeypatch, tmp_path):
    # The window may be gone by the time progress is reported: the export must not carry on unseen.
    proc = _Running(["out_time=00:00:30.000000\n"])
    monkeypatch.setattr(export.subprocess, "Popen", lambda cmd, **kwargs: proc)
    def gone(percent, done):
        raise RuntimeError("the window was closed")
    with pytest.raises(RuntimeError, match="window was closed"):
        export.run(["ffmpeg", "x"], 120, tmp_path, progress_cb=gone)
    assert proc.ended == ["terminated"]


def test_what_ffmpeg_said_is_kept_in_the_log_when_an_export_fails(monkeypatch, tmp_path, caplog):
    def popen(cmd, **kwargs):
        kwargs["stderr"].write("frame=  10\n[concat] Input link parameters do not match\nConversion failed!\n")
        return _Ffmpeg([], 1)
    monkeypatch.setattr(export.subprocess, "Popen", popen)
    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="The export didn't finish"):
        export.run(["ffmpeg", "x"], 120, tmp_path)
    assert "Input link parameters do not match" in caplog.text and "Conversion failed!" in caplog.text


def test_an_export_that_cannot_replace_an_open_file_says_so(monkeypatch, tmp_path):
    # On Windows a video that is open in a player can't be replaced.
    _fake_export(monkeypatch)
    from contextlib import contextmanager
    @contextmanager
    def in_use(dest):
        yield Path(tmp_path / "x.part.mp4")
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(export, "complete_or_nothing", in_use)
    with pytest.raises(RuntimeError, match="open in a player"):
        export.export(PROJECT, ["/v/game.mp4"], tmp_path / "out.mp4")
