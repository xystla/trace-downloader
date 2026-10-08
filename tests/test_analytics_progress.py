import json
from pathlib import Path
from types import SimpleNamespace

import pytest

MOMENT = {"type": "touch_chain", "side": "home", "duration": 10, "trace_numbers": ["4", "9"],
          "keywords": [], "thirds": ["middle"], "half": 1, "time": 100}


def _game(day):
    return {"status": "ready", "full_date": f"2026-09-{day:02d}T20:30:00.000Z",
            "approx_half_duration": 2700,
            "home_team": {"team_id": 7, "title": "Demo"}, "away_team": {"team_id": 8, "title": "Rivals"}}


@pytest.fixture
def trace(monkeypatch, tmp_path):
    """A worker wired to a fake Trace: `team` is the team's games, `moments` is
    what Trace serves per game id, `fetched` records every moments request."""
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", tmp_path)
    state = tmp_path / "state.json"
    instance = worker.Worker.__new__(worker.Worker)
    account = SimpleNamespace(id="demo", label="Demo", team_urls=["https://go.traceup.com/traceid/team/demo"],
                              state_path=lambda root: state,
                              analytics_dir=lambda root: tmp_path / "analytics" / "demo",
                              output_dir=lambda base: tmp_path / "videos")
    instance._accounts = SimpleNamespace(active=account)
    instance._ctx = SimpleNamespace(request=object())
    instance._cfg = SimpleNamespace(output_dir=tmp_path / "videos")
    fake = SimpleNamespace(worker=instance, team={}, moments={}, fetched=[], online=True,
                           downloaded=lambda *ids: state.write_text(json.dumps([f"demo-{i}" for i in ids])))
    fake.downloaded()
    def fetch_team_games(request, team_id, token):
        if not fake.online:
            raise RuntimeError("offline")
        return fake.team
    def fetch_game_moments(request, num, hash_key, token):
        fake.fetched.append(num)
        return True, fake.moments.get(num, [])
    from trace_grabber import analytics
    monkeypatch.setattr(analytics, "user_token", lambda request: {"token": "t", "user_id": 1})
    monkeypatch.setattr(analytics, "user_hash_key", lambda request, token: "h")
    monkeypatch.setattr(analytics, "team_numeric_id", lambda request, slug: 7)
    monkeypatch.setattr(analytics, "fetch_team_games", fetch_team_games)
    monkeypatch.setattr(analytics, "fetch_game_moments", fetch_game_moments)
    return fake


def _shown(result):
    return [split.whole.game_id for split in result.splits]


def test_reports_progress_for_every_game_checked(trace):
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {2: [MOMENT]}
    trace.downloaded(1, 2)
    calls = []
    result = trace.worker._compute_analytics(lambda done, total: calls.append((done, total)))
    assert calls == [(0, 2), (1, 2), (2, 2)]
    assert _shown(result) == [2]


def test_counts_downloaded_games_trace_gave_no_stats_for(trace):
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {2: [MOMENT]}
    trace.downloaded(1, 2)
    result = trace.worker._compute_analytics()
    assert (result.downloaded, result.without_stats) == (2, 1)


def test_recent_game_is_shown_even_if_not_downloaded(trace):
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    result = trace.worker._compute_analytics()
    assert _shown(result) == [1]
    assert (result.downloaded, result.without_stats) == (0, 0)


def test_stats_stay_after_trace_stops_serving_the_game(trace):
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    trace.downloaded(1)
    trace.worker._compute_analytics()
    trace.moments = {}                      # game fell out of the plan's recent window
    result = trace.worker._compute_analytics()
    assert _shown(result) == [1]
    assert result.without_stats == 0


def test_saved_stats_are_shown_when_trace_is_unreachable(trace):
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    trace.worker._compute_analytics()
    trace.online = False
    assert _shown(trace.worker._compute_analytics()) == [1]


def test_older_saved_games_are_not_requested_again(trace, monkeypatch):
    from gui import worker
    monkeypatch.setattr(worker.analytics_sync, "RECENT_GAMES", 1)
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {1: [MOMENT], 2: [MOMENT]}
    trace.downloaded(1, 2)
    trace.worker._compute_analytics()
    trace.fetched.clear()
    result = trace.worker._compute_analytics()
    assert trace.fetched == []              # everything is already saved
    assert sorted(_shown(result)) == [1, 2]


def test_get_analytics_emits_progress_and_reports_coverage():
    from gui import app, worker
    api = app.Api()
    events = []
    api._emit = lambda event, payload: events.append((event, payload))
    def compute(on_progress, refresh=False):
        on_progress(0, 31)
        return worker.AnalyticsResult(splits=[], downloaded=29, without_stats=24)
    api._worker = SimpleNamespace(compute_analytics=compute)
    payload = api.get_analytics()
    assert events == [("analytics_progress", {"done": 0, "total": 31})]
    assert (payload["downloaded"], payload["without_stats"], payload["games"]) == (29, 24, [])


def _old_game_without_stats(trace, monkeypatch):
    from gui import worker
    monkeypatch.setattr(worker.analytics_sync, "RECENT_GAMES", 1)
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {2: [MOMENT]}
    trace.downloaded(1, 2)
    trace.worker._compute_analytics()
    trace.fetched.clear()
    return worker


def test_old_game_without_stats_is_not_requested_again_the_same_day(trace, monkeypatch):
    _old_game_without_stats(trace, monkeypatch)
    result = trace.worker._compute_analytics()
    assert trace.fetched == []
    assert result.without_stats == 1


def test_old_game_without_stats_is_rechecked_after_a_day(trace, monkeypatch):
    worker = _old_game_without_stats(trace, monkeypatch)
    sync = worker.analytics_sync
    later = sync.time.time() + sync.analytics_cache.EMPTY_RECHECK_SECS + 60
    monkeypatch.setattr(sync.time, "time", lambda: later)
    trace.worker._compute_analytics()
    assert trace.fetched == [1]             # the saved game 2 is still not asked about


def test_scheduled_run_saves_stats_for_someone_who_has_viewed_them(trace, tmp_path):
    from trace_grabber import analytics_cache, main
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    analytics_cache.mark_viewed(tmp_path / "analytics" / "demo")
    main._save_stats(trace.worker._ctx, trace.worker._accounts.active, tmp_path)
    assert analytics_cache.cached_ids(tmp_path / "analytics" / "demo") == {1}


def test_scheduled_run_leaves_stats_alone_if_never_viewed(trace, tmp_path):
    from trace_grabber import analytics_cache, main
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    main._save_stats(trace.worker._ctx, trace.worker._accounts.active, tmp_path)
    assert trace.fetched == []
    assert analytics_cache.cached_ids(tmp_path / "analytics" / "demo") == set()


def test_opening_analytics_counts_as_viewing(trace, tmp_path):
    from trace_grabber import analytics_cache
    trace.worker._compute_analytics()
    assert analytics_cache.was_viewed(tmp_path / "analytics" / "demo")


def test_background_save_does_nothing_until_stats_have_been_viewed(trace):
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    assert trace.worker._save_stats() is False
    assert trace.fetched == []


def test_background_save_only_asks_about_recent_games(trace, tmp_path, monkeypatch):
    from gui import worker
    from trace_grabber import analytics_cache
    monkeypatch.setattr(worker.analytics_sync, "RECENT_GAMES", 1)
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {1: [MOMENT], 2: [MOMENT]}
    trace.downloaded(1, 2)                     # game 1 is old and not saved yet
    analytics_cache.mark_viewed(tmp_path / "analytics" / "demo")
    assert trace.worker._save_stats() is True
    assert trace.fetched == [2]
    assert analytics_cache.cached_ids(tmp_path / "analytics" / "demo") == {2}


def test_scheduled_run_survives_a_stats_failure(trace, tmp_path, monkeypatch):
    from trace_grabber import analytics_sync, main
    def boom(*args, **kwargs):
        raise RuntimeError("trace is down")
    monkeypatch.setattr(analytics_sync, "collect", boom)
    analytics_sync.analytics_cache.mark_viewed(tmp_path / "analytics" / "demo")
    main._save_stats(trace.worker._ctx, trace.worker._accounts.active, tmp_path)


def test_highlights_already_saved_are_not_cut_or_fetched_again(trace, tmp_path, monkeypatch):
    from gui import worker
    _recap_worker(trace, tmp_path, monkeypatch)
    video = tmp_path / "2026-06-04_vs-rovers" / "Full Game" / "2026-06-04_vs-rovers.mp4"
    folder = tmp_path / "2026-06-04_vs-rovers" / "Highlights"
    folder.mkdir(parents=True)
    (folder / "01_half1_04m55s_shot.mp4").write_bytes(b"clip")
    trace.worker._game_files = lambda date, opponent, game_id=None: [str(video)]
    def must_not_run(*args, **kwargs):
        raise AssertionError("should not fetch or cut again")
    monkeypatch.setattr(worker.analytics_sync, "moments_for", must_not_run)
    monkeypatch.setattr(worker.highlights, "export", must_not_run)
    assert trace.worker._export_highlights("demo-1", "2026-06-04", "Rovers") == (folder, 1, True)


def _recap_worker(trace, tmp_path, monkeypatch):
    from gui import worker
    trace.worker._cfg = SimpleNamespace(output_dir=tmp_path)
    trace.worker._accounts.active.output_dir = lambda base: tmp_path
    monkeypatch.setattr(worker.recaps, "game_players",
                        lambda request, team_slug, num, token: [worker.recaps.Player(3, "10", ""),
                                                                 worker.recaps.Player(2, "7", "Sage S.")])
    return worker


def test_highlights_listing_marks_recaps_already_saved(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    monkeypatch.setattr(worker.recaps, "fetch_segments", lambda request, user_id, num: [])
    game = tmp_path / "2026-06-04_vs-rovers"
    (game / "Player Highlights").mkdir(parents=True)
    (game / "Highlights").mkdir()
    (game / "Player Highlights" / "player-10.mp4").write_bytes(b"v")
    (game / "Highlights" / "01_half1_04m55s_shot.mp4").write_bytes(b"v")
    listing = trace.worker._list_highlights("demo-1", "2026-06-04", "Rovers")
    assert listing["team_clips"] == 1
    assert listing["players"] == [
        {"user_id": 3, "number": "10", "name": "", "saved": True, "seconds": None},
        {"user_id": 2, "number": "7", "name": "Sage S.", "saved": False, "seconds": 0}]


def test_highlights_listing_says_how_long_each_recap_is(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    lengths = {3: ["a.ts"] * 106, 2: []}          # Trace cuts recaps into 2-second segments
    monkeypatch.setattr(worker.recaps, "fetch_segments", lambda request, user_id, num: lengths[user_id])
    listing = trace.worker._list_highlights("demo-1", "2026-06-04", "Rovers")
    assert [(p["number"], p["seconds"]) for p in listing["players"]] == [("10", 212), ("7", 0)]


def test_recap_is_downloaded_into_the_games_highlights_folder(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    monkeypatch.setattr(worker.recaps, "fetch_segments", lambda request, user_id, num: ["https://x/a.ts"])
    saved = []
    def download(urls, dest, progress_cb=None, on_proc=None):
        saved.append((urls, dest))
        progress_cb(40)
        on_proc("ffmpeg process")
        assert trace.worker._proc == "ffmpeg process"      # Stop can reach it while it runs
    monkeypatch.setattr(worker.recaps, "download", download)
    seen = []
    path = trace.worker._download_recap("demo-1", "2026-06-04", "Rovers", 3, seen.append)
    assert saved == [(["https://x/a.ts"],
                      tmp_path / "2026-06-04_vs-rovers" / "Player Highlights" / "player-10.mp4")]
    assert path == str(saved[0][1])
    assert seen == [40] and trace.worker._proc is None


def test_recap_already_saved_is_not_downloaded_again(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    folder = tmp_path / "2026-06-04_vs-rovers" / "Player Highlights"
    folder.mkdir(parents=True)
    (folder / "player-10.mp4").write_bytes(b"v")
    def must_not_run(*args, **kwargs):
        raise AssertionError("should not download again")
    monkeypatch.setattr(worker.recaps, "fetch_segments", must_not_run)
    monkeypatch.setattr(worker.recaps, "download", must_not_run)
    assert trace.worker._download_recap("demo-1", "2026-06-04", "Rovers", 3) == str(folder / "player-10.mp4")


def test_clip_counts_come_from_each_games_highlights_folder(trace, tmp_path, monkeypatch):
    _recap_worker(trace, tmp_path, monkeypatch)
    from trace_grabber.games import Game
    folder = tmp_path / "2026-06-04_vs-rovers" / "Highlights"
    folder.mkdir(parents=True)
    for name in ("01_half1_04m55s_shot.mp4", "02_half2_01m35s_opp-shot.mp4"):
        (folder / name).write_bytes(b"v")
    games = [Game("demo-1", "demo", "2026-06-04", "Rovers", "T vs. Rovers"),
             Game("demo-2", "demo", "2026-06-01", "United", "T vs. United")]
    assert trace.worker._clip_counts(games) == {"demo-1": 2}


def _older_layout(tmp_path):
    """Clips and a recap where the previous layout kept them: '<game>_highlights'."""
    folder = tmp_path / "2026-06-04_vs-rovers_highlights"
    folder.mkdir()
    (folder / "01_half1_04m55s_shot.mp4").write_bytes(b"v")
    (folder / "player-10.mp4").write_bytes(b"v")
    return folder


def test_clips_and_recaps_saved_in_the_older_layout_still_count(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    monkeypatch.setattr(worker.recaps, "fetch_segments", lambda request, user_id, num: [])
    folder = _older_layout(tmp_path)
    listing = trace.worker._list_highlights("demo-1", "2026-06-04", "Rovers")
    assert listing["team_clips"] == 1 and listing["players"][0]["saved"] is True
    assert trace.worker._download_recap("demo-1", "2026-06-04", "Rovers", 3) == str(folder / "player-10.mp4")


def test_folder_buttons_open_the_right_folder(trace, tmp_path, monkeypatch):
    _recap_worker(trace, tmp_path, monkeypatch)
    args = ("demo-1", "2026-06-04", "Rovers")
    assert trace.worker._highlights_folder(*args, "clips") is None
    assert trace.worker._highlights_folder(*args, "recaps") is None
    game = tmp_path / "2026-06-04_vs-rovers"
    (game / "Highlights").mkdir(parents=True)
    (game / "Highlights" / "01_half1_04m55s_shot.mp4").write_bytes(b"v")
    (game / "Player Highlights").mkdir()
    (game / "Player Highlights" / "player-10.mp4").write_bytes(b"v")
    assert trace.worker._highlights_folder(*args, "clips") == str(game / "Highlights")
    assert trace.worker._highlights_folder(*args, "recaps") == str(game / "Player Highlights")


def test_folder_buttons_fall_back_to_the_older_layout(trace, tmp_path, monkeypatch):
    _recap_worker(trace, tmp_path, monkeypatch)
    folder = _older_layout(tmp_path)
    args = ("demo-1", "2026-06-04", "Rovers")
    assert trace.worker._highlights_folder(*args, "clips") == str(folder)
    assert trace.worker._highlights_folder(*args, "recaps") == str(folder)


def test_cutting_highlights_also_makes_the_reel(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    video = tmp_path / "2026-06-04_vs-rovers" / "Full Game" / "2026-06-04_vs-rovers.mp4"
    target = tmp_path / "2026-06-04_vs-rovers" / "Highlights"
    trace.worker._game_files = lambda date, opponent, game_id=None: [str(video)]
    monkeypatch.setattr(worker.analytics_sync, "moments_for",
                        lambda *args, **kwargs: (SimpleNamespace(our_side="home"), ["moments"]))
    monkeypatch.setattr(worker.highlights, "export", lambda moments, side, files, folder: (folder, 4))
    reels = []
    monkeypatch.setattr(worker.highlights, "build_reel", reels.append)
    assert trace.worker._export_highlights("demo-1", "2026-06-04", "Rovers") == (target, 4, False)
    assert reels == [target]


def test_clips_cut_before_reels_existed_get_one_when_asked_again(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    folder = tmp_path / "2026-06-04_vs-rovers" / "Highlights"
    folder.mkdir(parents=True)
    (folder / "01_half1_04m55s_shot.mp4").write_bytes(b"clip")
    trace.worker._game_files = lambda date, opponent, game_id=None: ["video.mp4"]
    reels = []
    monkeypatch.setattr(worker.highlights, "build_reel", reels.append)
    assert trace.worker._export_highlights("demo-1", "2026-06-04", "Rovers") == (folder, 1, True)
    trace.worker._highlights_folder("demo-1", "2026-06-04", "Rovers", "clips")
    assert reels == [folder, folder]


def test_highlights_come_straight_from_trace_when_the_game_is_not_downloaded(trace, tmp_path, monkeypatch):
    worker = _recap_worker(trace, tmp_path, monkeypatch)
    trace.worker._cfg.quality = "highest"
    trace.worker._cancel = __import__("threading").Event()
    trace.worker._game_files = lambda date, opponent, game_id=None: []                  # no video saved
    trace.worker._resolve_masters = lambda team_id, game_id: [f"https://t/{team_id}/h1.m3u8", "https://t/h2.m3u8"]
    trace.worker._ctx = SimpleNamespace(request=SimpleNamespace(
        get=lambda url, **kw: SimpleNamespace(text=lambda: "#EXTINF:2.0,\nseg0.ts\n")))
    monkeypatch.setattr(worker.quality, "pick_from_master", lambda text, url, quality: url + "?variant")
    monkeypatch.setattr(worker.analytics_sync, "moments_for",
                        lambda *args, **kwargs: (SimpleNamespace(our_side="home"), ["moments"]))
    calls, reels = [], []
    def export_remote(moments, side, playlists, folder, on_progress=None, on_proc=None, should_stop=None):
        calls.append((moments, side, playlists, folder))
        on_progress(1, 3)
        return folder, 3
    monkeypatch.setattr(worker.highlights, "export_remote", export_remote)
    monkeypatch.setattr(worker.highlights, "build_reel", reels.append)
    seen = []
    target = tmp_path / "2026-06-04_vs-rovers" / "Highlights"
    result = trace.worker._export_highlights("demo-1", "2026-06-04", "Rovers", lambda d, n: seen.append((d, n)))
    assert result == (target, 3, False)
    (moments, side, playlists, folder), = calls
    assert folder == target and sorted(playlists) == [1, 2]
    assert playlists[1] == [(2.0, "https://t/demo/seg0.ts")]
    assert seen == [(1, 3)] and reels == [target]


def _game_folder(tmp_path, day):
    """The folder the fake team's game on that September day would be saved in."""
    folder = tmp_path / "videos" / f"2026-09-{day:02d}_vs-rivals"
    folder.mkdir(parents=True)
    return folder


def test_viewing_stats_puts_a_copy_in_each_downloaded_games_folder(trace, tmp_path):
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {1: [MOMENT], 2: [MOMENT]}
    game = _game_folder(tmp_path, 1)                     # game 1 is downloaded, game 2 is not
    trace.worker._compute_analytics()
    assert (game / "Analytics" / "stats.json").exists()
    assert [p.name for p in (tmp_path / "videos").iterdir()] == ["2026-09-01_vs-rivals"]


def test_downloading_a_game_puts_its_stats_in_its_folder(trace, tmp_path):
    from trace_grabber import analytics_sync
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    game = _game_folder(tmp_path, 1)
    acct = trace.worker._accounts.active
    analytics_sync.save_for_download(trace.worker._ctx.request, acct, tmp_path, "demo-1",
                                     videos_dir=tmp_path / "videos")
    assert (game / "Analytics" / "stats.json").exists()


def test_stats_travel_with_the_videos_folder(trace, tmp_path):
    import shutil
    trace.team = {1: _game(1)}
    trace.moments = {1: [MOMENT]}
    _game_folder(tmp_path, 1)
    trace.worker._compute_analytics()
    shutil.rmtree(tmp_path / "analytics")                # another computer: no app data...
    trace.moments = {}                                   # ...and Trace no longer serves the game
    result = trace.worker._compute_analytics()
    assert _shown(result) == [1]


def _two_saved_games(trace):
    trace.team = {1: _game(1), 2: _game(2)}
    trace.moments = {1: [MOMENT], 2: [MOMENT]}
    trace.downloaded(1, 2)
    trace.worker._compute_analytics()
    trace.fetched.clear()
    trace.keys_asked = 0


def test_saved_stats_open_without_asking_trace_for_them_again(trace, monkeypatch):
    from trace_grabber import analytics
    _two_saved_games(trace)
    def count_key(request, token):
        trace.keys_asked += 1
        return "h"
    monkeypatch.setattr(analytics, "user_hash_key", count_key)
    result = trace.worker._compute_analytics()
    assert sorted(_shown(result)) == [1, 2]
    assert trace.fetched == [] and trace.keys_asked == 0      # no per-game requests at all


def test_a_new_game_is_still_fetched_alongside_the_saved_ones(trace):
    _two_saved_games(trace)
    trace.team[3] = _game(3)
    trace.moments[3] = [MOMENT]
    result = trace.worker._compute_analytics()
    assert trace.fetched == [3] and sorted(_shown(result)) == [1, 2, 3]


def test_refresh_asks_trace_again_for_recent_games(trace, monkeypatch):
    from gui import worker
    monkeypatch.setattr(worker.analytics_sync, "RECENT_GAMES", 1)
    _two_saved_games(trace)
    trace.worker._compute_analytics(refresh=True)
    assert trace.fetched == [2]             # the newest game is re-read; older saved ones are not


def test_analytics_result_carries_each_games_timeline(trace):
    trace.team = {1: _game(1)}
    trace.moments = {1: [dict(MOMENT, time=120, keywords=["home-shot"])]}
    result = trace.worker._compute_analytics()
    assert [m["label"] for m in result.timelines[1]["moments"]] == ["shot"]


def test_stats_saved_before_times_were_kept_are_fetched_once_more(trace, tmp_path):
    trace.team = {1: _game(1)}
    old = {k: v for k, v in MOMENT.items() if k != "time"}
    trace.moments = {1: [old]}                         # an old save: no "time" on the moment
    trace.worker._compute_analytics()
    trace.fetched.clear()
    trace.worker._compute_analytics()
    assert trace.fetched == []                         # Trace still has no times: not asked every time
    trace.fetched.clear()
    from trace_grabber import analytics_cache
    (tmp_path / "analytics" / "demo" / "_empty.json").unlink()      # a day later
    trace.moments = {1: [dict(MOMENT, time=120)]}
    trace.worker._compute_analytics()
    assert trace.fetched == [1]
    trace.fetched.clear()
    trace.worker._compute_analytics()
    assert trace.fetched == []                         # now complete, not asked again


def test_game_media_lists_everything_saved_for_a_game(trace, tmp_path, monkeypatch):
    _recap_worker(trace, tmp_path, monkeypatch)
    game = tmp_path / "2026-06-04_vs-rovers"
    for folder, names in {"Full Game": ["2026-06-04_vs-rovers.mp4"],
                          "Highlights": ["02_half2_01m35s_opp-shot.mp4", "01_half1_04m55s_shot.mp4",
                                         "Team Highlight Reel.mp4", "03_half2_09m00s_box-entry.part.mp4"],
                          "Player Highlights": ["player-10.mp4", "player-07-sage-s.mp4"]}.items():
        (game / folder).mkdir(parents=True)
        for name in names:
            (game / folder / name).write_bytes(b"v")
    media = trace.worker._game_media("demo-1", "2026-06-04", "Rovers")
    assert [Path(p).name for p in media["full"]] == ["2026-06-04_vs-rovers.mp4"]
    assert Path(media["reel"]).name == "Team Highlight Reel.mp4"
    assert [(c["label"], Path(c["path"]).name) for c in media["clips"]] == [
        ("Shot · 1st half 4:55", "01_half1_04m55s_shot.mp4"),
        ("Opponent shot · 2nd half 1:35", "02_half2_01m35s_opp-shot.mp4")]
    assert [(c["half"], c["start"]) for c in media["clips"]] == [(1, 295), (2, 95)]
    assert [(r["label"], Path(r["path"]).name) for r in media["recaps"]] == [
        ("#7 Sage S", "player-07-sage-s.mp4"), ("#10", "player-10.mp4")]


def test_game_media_is_empty_for_a_game_with_nothing_saved(trace, tmp_path, monkeypatch):
    _recap_worker(trace, tmp_path, monkeypatch)
    assert trace.worker._game_media("demo-1", "2026-06-04", "Rovers") == {
        "full": [], "reel": None, "clips": [], "recaps": [], "mine": [], "edited": []}


def test_open_folder_for_a_game_goes_to_the_most_specific_folder_there_is(trace, tmp_path, monkeypatch):
    _recap_worker(trace, tmp_path, monkeypatch)
    args = ("demo-1", "2026-06-04", "Rovers")
    assert trace.worker._folder_to_open(*args) == str(tmp_path)              # nothing saved yet: the team folder
    old = tmp_path / "2026-06-04_vs-rovers_highlights"
    old.mkdir()
    assert trace.worker._folder_to_open(*args) == str(old)                   # only the older highlights folder
    game = tmp_path / "2026-06-04_vs-rovers"
    (game / "Highlights").mkdir(parents=True)
    assert trace.worker._folder_to_open(*args) == str(game)                  # the game's own folder


def _radar_file(us_x):
    """A half's tracking: our player 1 roams around us_x, our goalkeeper stays on the left."""
    athletes = {"1": {"team": "demo", "pos": ""}, "9": {"team": "demo", "pos": ""}}
    frames = [{"t": i, "a": {"1": {"l": [us_x + i * 10, 500]}, "9": {"l": [20, 500]}}} for i in range(4)]
    return {"setup": {"athletes": athletes}, "frm": frames}


def _heat_worker(trace, served):
    master = "https://go.traceup.com/api/teams/demo/games/demo-1/gamevideo{}.hls/game_video.m3u8"
    trace.worker._resolve_masters = lambda team, game: [master.format(1), master.format(2)]
    asked = []
    def get(url, **kwargs):
        asked.append(url)
        data = served.get(url.rsplit("/", 1)[-1])
        return SimpleNamespace(ok=data is not None, json=lambda: data)
    trace.worker._ctx = SimpleNamespace(request=SimpleNamespace(get=get))
    return asked


def test_heat_map_is_fetched_once_then_read_from_disk(trace):
    asked = _heat_worker(trace, {"radar1_dynamic.json": _radar_file(600), "radar2_dynamic.json": _radar_file(300)})
    assert trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=False) is None
    assert asked == []                                 # looking is free; only "fetch" goes to Trace
    heat = trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=True)
    assert [url.rsplit("/", 1)[-1] for url in asked] == ["radar1_dynamic.json", "radar2_dynamic.json"]
    assert heat["whole"]["samples"] == 8 and heat["first"]["samples"] == 4 and heat["whole"]["players"] == 1
    assert trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=True) == heat
    assert len(asked) == 2


def test_heat_map_survives_a_half_trace_has_no_tracking_for(trace):
    _heat_worker(trace, {"radar1_dynamic.json": _radar_file(600)})
    heat = trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=True)
    assert heat["second"] is None and heat["whole"]["samples"] == 4


def test_game_without_tracking_has_no_heat_map(trace):
    _heat_worker(trace, {})
    assert trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=True) is None


def test_heat_map_loaded_before_the_game_had_a_folder_is_copied_in_later(trace, tmp_path):
    _heat_worker(trace, {"radar1_dynamic.json": _radar_file(600)})
    heat = trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=True)
    game = tmp_path / "videos" / "2026-06-04_vs-rovers"
    assert not game.exists()                       # looking at a game doesn't create its folder
    game.mkdir(parents=True)                       # ...then the game is downloaded
    assert trace.worker._heatmap("demo-1", "2026-06-04", "Rovers", fetch=False) == heat
    assert json.loads((game / "Analytics" / "heatmap.json").read_text()) == heat
