import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def game(monkeypatch, tmp_path):
    """A worker whose active account saves games under tmp_path; no job queue,
    so anything that waits in line would fail here."""
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", tmp_path)
    w = worker.Worker.__new__(worker.Worker)
    w._accounts = SimpleNamespace(active=SimpleNamespace(
        id="demo", output_dir=lambda base: tmp_path, state_path=lambda root: tmp_path / "state.json"))
    w._cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False, quality="highest")
    w._cancel = threading.Event()
    w.module = worker
    w.root = tmp_path / "2026-09-22_vs-rivals"
    w.args = ("demo-7", "2026-09-22", "Rivals")
    w.cuts = []
    def cut_clip(source, start, length, dest):
        w.cuts.append((Path(source).name, start, length))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"clip")
    monkeypatch.setattr(worker.highlights, "cut_clip", cut_clip)
    return w


def _save(game, *names):
    full = game.root / "Full Game"
    full.mkdir(parents=True, exist_ok=True)
    for name in names:
        (full / name).write_bytes(b"video")


def test_bookmarks_go_in_the_games_folder_without_waiting_in_line(game):
    assert game.bookmarks(*game.args) == []
    new_id, marks = game.add_bookmark(*game.args, 1390.4, 1, "Good press")
    assert [m["id"] for m in marks] == [new_id] and (game.root / "Bookmarks" / "bookmarks.json").exists()
    assert game.edit_bookmark(*game.args, new_id, "Great press")[0]["note"] == "Great press"
    assert game.remove_bookmark(*game.args, new_id) == []


def test_a_clip_is_cut_from_the_half_that_was_playing(game):
    _save(game, "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4")
    path = game.export_clip(*game.args, 2, 724.5, 751.5)
    assert game.cuts == [("2026-09-22_vs-rivals_half2.mp4", 724.5, 27.0)]
    assert Path(path) == game.root / "My Clips" / "half2_12m04s-12m31s.mp4"


def test_a_clip_from_a_game_saved_as_one_file(game):
    _save(game, "2026-09-22_vs-rivals.mp4")
    path = game.export_clip(*game.args, 0, 3605, 3660)
    assert game.cuts == [("2026-09-22_vs-rivals.mp4", 3605.0, 55.0)] and Path(path).name == "60m05s-61m00s.mp4"


def test_the_same_stretch_twice_keeps_both_clips(game):
    _save(game, "2026-09-22_vs-rivals.mp4")
    first = game.export_clip(*game.args, 0, 10, 20)
    second = game.export_clip(*game.args, 0, 10.4, 20.2)          # same seconds, so the same name
    assert (Path(first).name, Path(second).name) == ("00m10s-00m20s.mp4", "00m10s-00m20s-2.mp4")


def test_a_clip_must_be_a_sensible_length(game):
    _save(game, "2026-09-22_vs-rivals.mp4")
    for start, end in ((10, 10.5), (0, 601), (20, 10)):
        with pytest.raises(RuntimeError, match="1 second to 10 minutes"):
            game.export_clip(*game.args, 0, start, end)
    assert game.cuts == []


def test_a_clip_needs_the_video_it_is_cut_from(game):
    _save(game, "2026-09-22_vs-rivals_half1.mp4")
    with pytest.raises(RuntimeError, match="Couldn't find the video"):
        game.export_clip(*game.args, 2, 10, 20)
    with pytest.raises(RuntimeError, match="Couldn't find the video"):
        game.export_clip(*game.args, 0, 10, 20)


def test_your_own_clips_are_listed_with_the_games_other_videos(game):
    _save(game, "2026-09-22_vs-rivals.mp4")
    game.export_clip(*game.args, 0, 10, 20)
    media = game._game_media(*game.args)
    assert media["mine"] == [{"label": "0:10 – 0:20", "path": str(game.root / "My Clips" / "00m10s-00m20s.mp4")}]
    assert game._highlights_folder(*game.args, kind="mine") == str(game.root / "My Clips")


def test_a_game_with_no_clips_of_your_own_has_no_such_folder_to_show(game):
    assert game._game_media(*game.args)["mine"] == []
    assert game._highlights_folder(*game.args, kind="mine") is None
