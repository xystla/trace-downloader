import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

GB = 1_000_000_000


@pytest.fixture
def ed(monkeypatch, tmp_path):
    """A worker with one saved game; video facts and the export itself are faked."""
    from trace_grabber import paths
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "data_dir", lambda: data)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", data)
    root = tmp_path / "library"
    w = worker.Worker.__new__(worker.Worker)
    w._accounts = SimpleNamespace(active=SimpleNamespace(
        id="demo", label="Tiger Sharks", output_dir=lambda base: root, state_path=lambda r: data / "state.json"))
    w._cfg = SimpleNamespace(output_dir=root, combine_halves=False, quality="highest", file_name="")
    w._cancel = threading.Event()
    w.module, w.root, w.data = worker, root, data
    w.args = ("demo-7", "2026-09-22", "Rivals")
    w.game_root = root / "2026-09-22_vs-rivals"
    monkeypatch.setattr(worker.export, "video_info", lambda path: {
        "duration": 1500.0 if "half" in Path(path).name else 4480.0, "width": 1920, "height": 1080, "bitrate": 5000, "audio": True, "fps": 30.0})
    monkeypatch.setattr(worker.space, "free", lambda folder: 500 * GB)
    w.exports = []
    w.sounds = []
    def export(project, files, dest, quality="best", progress_cb=None, on_proc=None, crests=None, sound=True):
        w.sounds.append(sound)
        w.exports.append((project["home"]["code"], [Path(f).name for f in files], quality, sorted(crests or {})))
        if progress_cb:
            progress_cb(50, 600.0)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"edited")
    monkeypatch.setattr(worker.export, "export", export)
    return w


def _video(ed, *names):
    full = ed.game_root / "Full Game"
    full.mkdir(parents=True, exist_ok=True)
    for name in names:
        (full / name).write_bytes(b"x" * 1000)


MARKS = [{"id": "a", "kind": "start", "t": 10}, {"id": "b", "kind": "end", "t": 1300}]


def _picture(path, colour=(200, 30, 30)):
    from PIL import Image
    Image.new("RGB", (300, 300), colour).save(path)
    return str(path)


def test_saved_looks_are_kept_with_the_apps_own_data(ed):
    assert ed.edit_looks() == []
    assert [look["name"] for look in ed.edit_look_save("Night games", {"font": "anton"})] == ["Night games"]
    assert (ed.data / "edit_looks.json").exists() and ed.edit_looks()[0]["bug"]["font"] == "anton"
    assert ed.edit_look_delete("Night games") == []


def test_a_crest_is_added_shown_and_removed(ed, tmp_path):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    assert ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]["crests"] == {"home": False, "away": False, "league": False}
    ed.edit_crest(*ed.args, "away", _picture(tmp_path / "rivals.jpg"))
    assert (ed.game_root / "Edit" / "crest-away.png").exists()
    assert set(ed.edit_crest_images(*ed.args, {"home": True, "away": True, "league": True})) == {"away"}
    ed.edit_crest(*ed.args, "away", None)
    assert not (ed.game_root / "Edit" / "crest-away.png").exists()
    with pytest.raises(RuntimeError, match="isn't a picture"):
        ed.edit_crest(*ed.args, "home", str(tmp_path / "nothing.png"))


def test_a_crest_ticked_but_gone_from_disk_is_unticked_on_opening(ed):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    project = ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]
    project["crests"] = {"home": True, "away": True, "league": False}
    project["marks"] = MARKS
    ed.edit_save(*ed.args, project)
    assert ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]["crests"] == {"home": False, "away": False, "league": False}


def test_your_own_crest_and_the_league_one_are_there_for_the_next_game(ed, tmp_path):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")
    ed.edit_crest(*ed.args, "home", _picture(tmp_path / "us.png"))
    ed.edit_crest(*ed.args, "league", _picture(tmp_path / "league.png", (0, 200, 180)))
    ed.edit_crest(*ed.args, "away", _picture(tmp_path / "them.png"))
    other = ed.root / "2026-09-29_vs-united" / "Full Game"
    other.mkdir(parents=True)
    (other / "2026-09-29_vs-united.mp4").write_bytes(b"x")
    fresh = ed.edit_open("demo-8", "2026-09-29", "United", "Tiger Sharks", "United")["project"]
    assert fresh["crests"] == {"home": True, "away": False, "league": True}        # not the other team's
    assert (ed.root / "2026-09-29_vs-united" / "Edit" / "crest-home.png").exists()
    # Taking your crest off forgets it for later games too.
    ed.edit_crest("demo-8", "2026-09-29", "United", "home", None)
    third = ed.root / "2026-10-06_vs-athletic" / "Full Game"
    third.mkdir(parents=True)
    (third / "2026-10-06_vs-athletic.mp4").write_bytes(b"x")
    assert ed.edit_open("demo-9", "2026-10-06", "Athletic", "Tiger Sharks", "Athletic")["project"]["crests"] == {"home": False, "away": False, "league": True}


def test_the_export_is_given_the_crests_the_edit_shows(ed, tmp_path):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    project = ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]
    ed.edit_crest(*ed.args, "home", _picture(tmp_path / "us.png"))
    ed.edit_crest(*ed.args, "away", _picture(tmp_path / "them.png"))
    project["crests"] = {"home": True, "away": False, "league": False}             # the away crest is there but switched off
    project["marks"] = MARKS
    ed.edit_save(*ed.args, project)
    ed.export_edit(*ed.args, "best")
    assert ed.exports[-1][3] == ["home"]


def test_a_new_edit_starts_from_the_two_teams(ed):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    opened = ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")
    assert opened["project"]["home"]["code"] == "TIG" and opened["project"]["away"]["code"] == "RIV"
    assert opened["project"]["marks"] == [] and opened["durations"] == [4480.0] and opened["height"] == 1080
    assert [Path(f).name for f in opened["files"]] == ["2026-09-22_vs-rivals.mp4"]


def test_an_edit_needs_the_full_game(ed):
    with pytest.raises(RuntimeError, match="Download the full game first"):
        ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")


def test_a_saved_edit_comes_back_and_your_team_is_remembered_for_the_next_game(ed):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    project = ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]
    project["home"].update(code="TSH", color="#ff8800")
    project["bug"] = {"size": 1.4, "font": "bebas", "color": "#0a2a5c", "clock": 10, "strip": 20, "round": 23, "timer": "right", "animate": False, "design": "blocks", "color2": "#00aaff", "crest_shadow": True, "timer_full": True, "timer_text": 75}
    project["marks"] = MARKS
    kept = ed.edit_save(*ed.args, project)
    assert kept["home"]["code"] == "TSH" and (ed.game_root / "Edit" / "edit.json").exists()
    assert ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]["marks"] == kept["marks"]
    other = ed.root / "2026-09-29_vs-united" / "Full Game"
    other.mkdir(parents=True)
    (other / "2026-09-29_vs-united.mp4").write_bytes(b"x")
    fresh = ed.edit_open("demo-8", "2026-09-29", "United", "Tiger Sharks", "United")["project"]
    assert fresh["home"] == {"name": "Tiger Sharks", "code": "TSH", "color": "#ff8800"} and fresh["away"]["code"] == "UNI"
    assert fresh["bug"] == {"size": 1.4, "font": "bebas", "color": "#0a2a5c", "clock": 10, "strip": 20, "round": 23, "timer": "right", "animate": False, "design": "blocks", "color2": "#00aaff", "crest_shadow": True, "timer_full": True, "timer_text": 75}                # the bug's look carries over too


def test_two_half_files_are_edited_as_one_game(ed):
    _video(ed, "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4")
    assert ed.edit_open(*ed.args, "T", "R")["durations"] == [1500.0, 1500.0]


def test_exporting_writes_the_edited_game_beside_the_original(ed):
    _video(ed, "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4")
    project = ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]
    project["marks"] = MARKS
    ed.edit_save(*ed.args, project)
    seen = []
    path = ed.export_edit(*ed.args, "faster", on_progress=lambda pct, done: seen.append(pct))
    assert Path(path) == ed.game_root / "Edited" / "2026-09-22_vs-rivals (edited).mp4"        # no '_half1' in the name
    assert ed.exports == [("TIG", ["2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"], "faster", [])]
    assert seen == [50]
    assert ed._game_media(*ed.args)["edited"] == [{"label": "Edited game", "path": path}]
    assert sorted(p.name for p in (ed.game_root / "Full Game").iterdir()) == [
        "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]                # the originals are untouched


def test_there_is_nothing_to_export_before_an_edit_is_saved(ed):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    with pytest.raises(RuntimeError, match="no edit for this game yet"):
        ed.export_edit(*ed.args, "best")
    assert ed.exports == []


def test_an_export_that_will_not_fit_is_refused_first(ed, monkeypatch):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    ed.edit_save(*ed.args, {"marks": MARKS})
    monkeypatch.setattr(ed.module.space, "free", lambda folder: 100)
    with pytest.raises(ed.module.space.NotEnoughSpace):
        ed.export_edit(*ed.args, "best")
    assert ed.exports == []


def test_room_is_checked_for_an_export_bigger_than_the_original(ed, monkeypatch):
    # At the best quality a real game came out nearly twice the size of its source.
    _video(ed, "2026-09-22_vs-rivals.mp4")                        # 1000 bytes
    ed.edit_save(*ed.args, {"marks": MARKS})
    margin = ed.module.space.MARGIN
    monkeypatch.setattr(ed.module.space, "free", lambda folder: 1500 + margin)
    with pytest.raises(ed.module.space.NotEnoughSpace):
        ed.export_edit(*ed.args, "best")
    monkeypatch.setattr(ed.module.space, "free", lambda folder: 2000 + margin)
    ed.export_edit(*ed.args, "best")
    assert len(ed.exports) == 1


def test_an_export_without_sound_is_asked_for_that_way(ed):
    _video(ed, "2026-09-22_vs-rivals.mp4")
    project = ed.edit_open(*ed.args, "Tiger Sharks", "Rivals")["project"]
    project["marks"] = MARKS
    ed.edit_save(*ed.args, project)
    ed.export_edit(*ed.args, "best")
    ed.export_edit(*ed.args, "best", sound=False)
    assert ed.sounds == [True, False]


def _tracked(seconds, people, fps=2):
    """A half's tracking file: `people(t)` says who is where at each moment."""
    return {"setup": {"fps": fps}, "frm": [{"t": i * 100 // fps, "a": people(i / fps)} for i in range(seconds * fps)]}


def _half(t):
    """A half of 300 seconds' play: lined up for 20, playing, walking off for 10, then gone."""
    import math
    spot = lambda x, y: {"l": [round(x), round(y)]}
    if t < 20:
        return {str(p): spot(150 + 50 * p, 300 + 30 * (p % 5)) for p in range(14)}
    if t < 320:
        return {str(p): spot(500 + 300 * math.sin(t / 3 + p), 500 + 150 * math.sin(t / 2 + 2 * p)) for p in range(14)}
    if t < 330:
        return {str(p): spot(400 + 10 * p, 120 + 55 * p) for p in range(14)}
    return {"90": spot(500, 20)}


def monkeypatch_whistle(ed, heard):
    ed.module.whistle.heard = heard


@pytest.fixture
def quiet(ed):
    """Whatever a test does to the whistle listening is undone after it."""
    kept = ed.module.whistle.heard
    yield
    ed.module.whistle.heard = kept


def test_marks_are_suggested_from_each_halfs_tracking_timed_by_the_videos(ed, quiet):
    _video(ed, "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4")       # 1500 seconds each
    asked = []
    def get(url, timeout=None):
        asked.append(url)
        return SimpleNamespace(ok=True, json=lambda: _tracked(400, _half))
    ed._ctx = SimpleNamespace(request=SimpleNamespace(get=get))
    ed._resolve_masters = lambda team, game_id: [f"https://t/api/teams/{team}/games/{game_id}/gamevideo{h}.hls/game_video.m3u8"
                                                 for h in (1, 2)]
    listened = []
    def heard(path, start, seconds):
        listened.append(Path(path).name)
        # the second half's whistle for the end, 318 seconds into that file
        return [(318.0, 319.5)] if "half2" in Path(path).name and start <= 318.0 <= start + seconds else []
    monkeypatch_whistle(ed, heard)
    found = ed._edit_suggest(*ed.args)
    assert asked == [f"https://t/api/teams/demo/games/demo-7/radar{h}_dynamic.json" for h in (1, 2)]
    assert [m["kind"] for m in found] == ["start", "break", "resume", "end"]
    # The second half's marks are timed from the end of the first half's video, not of its tracking.
    assert found[2]["t"] == found[0]["t"] + 1500.0
    # Each stretch is listened to in the file it falls in, and a whistle there is put on the game's clock.
    assert listened == ["2026-09-22_vs-rivals_half1.mp4"] * 2 + ["2026-09-22_vs-rivals_half2.mp4"] * 2
    assert found[3]["t"] == 1500.0 + 319.5 + 1.0


def test_no_marks_are_suggested_without_tracking_or_without_the_video(ed):
    ed._ctx = SimpleNamespace(request=SimpleNamespace(get=lambda url, timeout=None: SimpleNamespace(ok=False)))
    ed._resolve_masters = lambda team, game_id: ["https://t/api/teams/demo/games/demo-7/gamevideo1.hls/game_video.m3u8"]
    with pytest.raises(RuntimeError, match="Download the full game first"):
        ed._edit_suggest(*ed.args)
    _video(ed, "2026-09-22_vs-rivals.mp4")
    assert ed._edit_suggest(*ed.args) == []
