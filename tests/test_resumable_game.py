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
    def fetch(parts, dest, headers, quality, on_progress=None, should_stop=None, on_proc=None):
        w.fetched.append(dest.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"video")
    w.fetch = fetch
    monkeypatch.setattr(worker.pieces, "fetch", lambda *a, **k: w.fetch(*a, **k))
    w.module = worker
    w.full = tmp_path / "2026-09-22_vs-rivals" / "Full Game"
    w.run = lambda on_progress=lambda info: None: w._download_game(
        "demo-7", "demo", "2026-09-22", "Rivals", on_progress)
    return w


def test_both_halves_are_fetched_under_fixed_names(game):
    assert game.run() == 2
    assert game.fetched == ["2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]


def test_a_half_that_was_already_finished_is_not_downloaded_again(game):
    game.full.mkdir(parents=True)
    (game.full / "2026-09-22_vs-rivals_half1.mp4").write_bytes(b"done earlier")
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
    game.full.mkdir(parents=True)
    (game.full / "2026-09-22_vs-rivals_half1.mp4").write_bytes(b"done")
    shares = {"2026-09-22_vs-rivals_half2.mp4": 0.5}
    monkeypatch.setattr(game.module.pieces, "progress_of", lambda dest: shares.get(dest.name))
    assert game._partials(listed, done={"demo-9"}) == {"demo-7": 0.75}


def test_discarding_removes_the_pieces_and_any_finished_half(game, monkeypatch):
    game.full.mkdir(parents=True)
    half1 = game.full / "2026-09-22_vs-rivals_half1.mp4"
    half1.write_bytes(b"done")
    thrown = []
    monkeypatch.setattr(game.module.pieces, "discard", lambda dest: thrown.append(dest.name))
    assert game._discard_partial("demo-7", "2026-09-22", "Rivals") is True
    assert not half1.exists()
    assert thrown == ["2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]


def test_free_space_is_that_of_the_download_folder(game):
    assert game._disk_free() == 500 * GB
