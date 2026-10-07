import json
import threading
from types import SimpleNamespace

import pytest

GB = 1_000_000_000


class _Request:
    def get(self, url, **kwargs):
        return SimpleNamespace(text=lambda: "")


@pytest.fixture
def game(monkeypatch, tmp_path):
    """A worker with Trace faked: two halves of three pieces, 1 GB a half.
    `game.fetched` lists the halves fetched; `game.fetch` can be replaced."""
    from trace_grabber import analytics_sync, paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", tmp_path)
    monkeypatch.setattr(analytics_sync, "moments_for", lambda *a, **k: None)
    account = SimpleNamespace(id="demo", output_dir=lambda base: tmp_path,
                              state_path=lambda root: tmp_path / "state.json")
    w = worker.Worker.__new__(worker.Worker)
    w._accounts = SimpleNamespace(active=account)
    w._ctx = SimpleNamespace(request=_Request())
    w._cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False, quality="highest")
    w._cancel = threading.Event()
    w._proc = None
    w._resolve_masters = lambda team_id, game_id: ["half1", "half2"]
    monkeypatch.setattr(worker, "cookie_headers", lambda ctx: {"Cookie": "s=1"})
    monkeypatch.setattr(worker.quality, "pick_variant", lambda text, url, quality: ("variant", 8_000_000))
    monkeypatch.setattr(worker.segments, "parse", lambda text, url: [(1000 / 3, f"https://t/{i}.ts") for i in range(3)])
    monkeypatch.setattr(worker.space, "free", lambda folder: 500 * GB)
    w.fetched = []
    w.owners = []
    def fetch(parts, dest, headers, quality, on_progress=None, should_stop=None, on_proc=None, owner=""):
        w.fetched.append(dest.name)
        w.owners.append(owner)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"video")
    w.fetch = fetch
    monkeypatch.setattr(worker.pieces, "fetch", lambda *a, **k: w.fetch(*a, **k))
    w.module = worker
    w.full = tmp_path / "2026-09-22_vs-rivals" / "Full Game"
    w.run = lambda on_progress=lambda info: None: w._download_game(
        "demo-7", "demo", "2026-09-22", "Rivals", on_progress)
    return w


def _finished_earlier(game, name, owner="demo-7", quality="highest", content=b"done earlier"):
    """A half an earlier attempt finished, with the record the fetcher leaves beside it."""
    game.full.mkdir(parents=True, exist_ok=True)
    half = game.full / name
    half.write_bytes(content)
    (game.full / f".{half.stem}.done").write_text(json.dumps({"owner": owner, "quality": quality}))
    return half


def test_both_halves_are_fetched_under_fixed_names(game):
    assert game.run() == 2
    assert game.fetched == ["2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]


def test_a_half_that_was_already_finished_is_not_downloaded_again(game):
    _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4")
    assert game.run() == 2
    assert game.fetched == ["2026-09-22_vs-rivals_half2.mp4"]
    assert sorted(p.name for p in game.full.glob("*.mp4")) == [
        "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]      # no '-2' copy


def test_a_stop_keeps_what_was_downloaded_and_does_not_mark_the_game_saved(game):
    def stopped(parts, dest, headers, quality, **kwargs):
        game._cancel.set()
        raise game.module.pieces.Stopped("stopped")
    game.fetch = stopped
    assert game.run() == 0
    assert not (game.full.parent.parent / "state.json").exists()


def test_a_dropped_connection_is_reported_and_half_one_is_kept(game):
    original = game.fetch
    def second_half_fails(parts, dest, headers, quality, **kwargs):
        if "half2" in dest.name:
            raise RuntimeError("The connection dropped.")
        original(parts, dest, headers, quality, **kwargs)
    game.fetch = second_half_fails
    with pytest.raises(RuntimeError, match="connection dropped"):
        game.run()
    assert (game.full / "2026-09-22_vs-rivals_half1.mp4").exists()


def test_a_game_that_will_not_fit_is_refused_before_anything_is_fetched(game, monkeypatch):
    monkeypatch.setattr(game.module.space, "free", lambda folder: 2 * GB)      # needs 2 + 1 + 0.5
    with pytest.raises(game.module.space.NotEnoughSpace):
        game.run()
    assert game.fetched == []


def test_progress_covers_the_whole_game_with_speed_and_time_left(game, monkeypatch):
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(game.module.time, "monotonic", lambda: next(clock))
    def fetch(parts, dest, headers, quality, on_progress=None, **kwargs):
        on_progress(0, 0, 0, 3)
        on_progress(GB // 2, GB, 1, 3)
        on_progress(GB, GB, 3, 3)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"video")
    game.fetch = fetch
    seen = []
    game.run(seen.append)
    first_half = [info for info in seen if info["half"] == 1]
    assert [info["percent"] for info in first_half] == [0, 25, 50]
    assert first_half[1]["speed"] == 100.0 and first_half[1]["eta"] == 15      # 0.5 GB in 5 s, 1.5 GB to go
    assert first_half[-1]["joining"] is True and first_half[0]["joining"] is False
    assert seen[-1]["half"] == 2 and seen[-1]["percent"] <= 100


def test_a_cut_off_game_reports_how_far_it_got(game, monkeypatch):
    listed = [SimpleNamespace(id="demo-7", date="2026-09-22", opponent="Rivals"),
              SimpleNamespace(id="demo-8", date="2026-09-29", opponent="United"),
              SimpleNamespace(id="demo-9", date="2026-10-01", opponent="Athletic")]
    _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4")
    shares = {("2026-09-22_vs-rivals_half2.mp4", "demo-7", "highest"): 0.5}
    monkeypatch.setattr(game.module.pieces, "progress_of",
                        lambda dest, owner=None, quality=None: shares.get((dest.name, owner, quality)))
    assert game._partials(listed, done={"demo-9"}) == {"demo-7": 0.75}


def test_discarding_removes_the_pieces_and_any_finished_half(game):
    half1 = _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4")
    pieces_folder = game.full / ".2026-09-22_vs-rivals_half2.pieces"
    pieces_folder.mkdir()
    (pieces_folder / "info.json").write_text(json.dumps({"owner": "demo-7", "quality": "highest", "count": 3}))
    (pieces_folder / "00000.ts").write_bytes(b"piece")
    assert game._discard_partial("demo-7", "2026-09-22", "Rivals") is True
    assert list(game.full.iterdir()) == []


def test_fetching_says_whose_download_it_is(game):
    game.run()
    assert game.owners == ["demo-7", "demo-7"]


def test_another_games_half_with_the_same_name_is_neither_taken_nor_overwritten(game):
    # Two games on one day against the same opponent share a folder and a file name.
    theirs = _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4", owner="demo-6", content=b"the other game")
    assert game.run() == 2
    assert game.fetched == ["2026-09-22_vs-rivals_half1-2.mp4", "2026-09-22_vs-rivals_half2.mp4"]
    assert theirs.read_bytes() == b"the other game"


def test_a_video_saved_before_is_not_mistaken_for_a_finished_half(game):
    game.full.mkdir(parents=True)
    saved = game.full / "2026-09-22_vs-rivals_half1.mp4"
    saved.write_bytes(b"saved by an older version")
    assert game._partials([SimpleNamespace(id="demo-7", date="2026-09-22", opponent="Rivals")], done=set()) == {}
    game.run()
    assert game.fetched[0] == "2026-09-22_vs-rivals_half1-2.mp4" and saved.read_bytes() == b"saved by an older version"


def test_a_half_finished_at_another_quality_is_downloaded_again(game):
    _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4", quality="1000k")
    game.run()
    assert game.fetched == ["2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]


def test_once_a_game_is_saved_its_halves_are_ordinary_videos(game):
    _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4")
    game.run()
    assert sorted(p.name for p in game.full.iterdir()) == [
        "2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]      # no records left
    assert game._partials([SimpleNamespace(id="demo-7", date="2026-09-22", opponent="Rivals")], done=set()) == {}


def test_discard_never_deletes_a_saved_game(game):
    game.run()                                                   # saved as two halves
    assert game._discard_partial("demo-7", "2026-09-22", "Rivals") is False
    assert len(list(game.full.glob("*.mp4"))) == 2


def test_discard_leaves_another_games_files_alone(game):
    theirs = _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4", owner="demo-6")
    mine = _finished_earlier(game, "2026-09-22_vs-rivals_half1-2.mp4")
    assert game._discard_partial("demo-7", "2026-09-22", "Rivals") is True
    assert theirs.exists() and not mine.exists()


def test_a_game_cannot_be_discarded_while_it_is_downloading(game):
    half1 = _finished_earlier(game, "2026-09-22_vs-rivals_half1.mp4")
    seen = []
    def fetch(parts, dest, headers, quality, **kwargs):
        seen.append(game.discard_partial("demo-7", "2026-09-22", "Rivals"))
        dest.write_bytes(b"video")
    game.fetch = fetch
    game.run()
    assert seen == [False] and half1.exists()


def test_free_space_and_discard_do_not_wait_behind_a_running_download(game):
    # The test worker has no job queue at all: these must answer on the caller's own thread.
    assert not hasattr(game, "_jobs")
    assert game.disk_free() == 500 * GB
    assert game.discard_partial("demo-7", "2026-09-22", "Rivals") is True


def test_free_space_is_that_of_the_download_folder(game):
    assert game._disk_free() == 500 * GB


def test_downloading_a_missing_game_again_un_saves_it_until_it_is_whole(game):
    # Saved once, video since gone; "Download again" is cut off after the first half.
    state = game.full.parent.parent / "state.json"
    state.write_text(json.dumps(["demo-7", "demo-9"]))
    def fetch(parts, dest, headers, quality, **kwargs):
        if "half2" in dest.name:
            raise RuntimeError("The connection dropped.")
        _finished_earlier(game, dest.name)
    game.fetch = fetch
    with pytest.raises(RuntimeError):
        game.run()
    assert json.loads(state.read_text()) == ["demo-9"]                # not "saved" on the strength of half a game
    listed = [SimpleNamespace(id="demo-7", date="2026-09-22", opponent="Rivals")]
    assert game._partials(listed, done=set(json.loads(state.read_text()))) == {"demo-7": 0.5}


def test_downloading_does_not_un_save_a_game_whose_video_is_there(game):
    state = game.full.parent.parent / "state.json"
    state.write_text(json.dumps(["demo-7"]))
    game.full.mkdir(parents=True)
    (game.full / "2026-09-22_vs-rivals.mp4").write_bytes(b"the whole game")
    def stopped(parts, dest, headers, quality, **kwargs):
        game._cancel.set()
        raise game.module.pieces.Stopped("stopped")
    game.fetch = stopped
    game.run()
    assert json.loads(state.read_text()) == ["demo-7"]
