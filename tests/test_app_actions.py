from types import SimpleNamespace

import pytest

from trace_grabber.games import Game


@pytest.fixture
def api(monkeypatch):
    """The app API with a stub worker; records notifications, opened and revealed files."""
    from gui import app
    api = app.Api()
    api.notes, api.opened, api.revealed, api.events = [], [], [], []
    monkeypatch.setattr(app.platform_tasks, "notify", api.notes.append)
    monkeypatch.setattr(app.platform_tasks, "open_file", api.opened.append)
    monkeypatch.setattr(app.platform_tasks, "reveal_file", api.revealed.append)
    api._emit = lambda event, payload: api.events.append((event, payload))
    games = [Game("t-1", "t", "2026-06-04", "Rovers", "T vs. Rovers"),
             Game("t-2", "t", "2026-06-01", "United", "T vs. United")]
    api._game_cache = {g.id: g for g in games}
    api.files = {"t-1": ["/v/2026-06-04_vs-rovers.mp4"]}
    api.saved_per_game = 1
    api.is_cancelled = False
    api._worker = SimpleNamespace(
        clear_cancel=lambda: None, cancelled=lambda: api.is_cancelled,
        partials=lambda games, done: {},
        download_game=lambda *a: api.saved_per_game,
        list_games=lambda: (games, set()),
        game_files=lambda game_id, date, opponent: api.files.get(game_id, []))
    return api


def test_play_opens_the_saved_video(api):
    assert api.play_game("t-1") == {"ok": True}
    assert api.opened == ["/v/2026-06-04_vs-rovers.mp4"]


def test_show_in_folder_reveals_the_saved_video(api):
    assert api.reveal_game("t-1") == {"ok": True}
    assert api.revealed == ["/v/2026-06-04_vs-rovers.mp4"]


def test_play_says_so_when_the_file_is_gone(api):
    result = api.play_game("t-2")
    assert result["ok"] is False and "moved" in result["error"]
    assert api.opened == []


def test_single_download_notifies_when_saved(api):
    api.download_game("t-1")
    assert api.notes == ["Saved vs Rovers"]


def test_no_notification_when_nothing_was_saved(api):
    api.saved_per_game = 0
    api.download_game("t-1")
    assert api.notes == []


def test_no_notification_when_cancelled(api):
    api.is_cancelled = True
    api.download_game("t-1")
    assert api.notes == []


def test_team_highlights_report_how_many_clips_were_saved(api):
    api._worker.export_highlights = lambda game_id, date, opponent, on_progress=None: ("/v/g_highlights", 6, False)
    assert api.download_highlights("t-1") == {"ok": True, "count": 6, "already": False}


def test_highlights_explain_when_there_is_nothing_to_cut(api):
    api._worker.export_highlights = lambda game_id, date, opponent, on_progress=None: (None, 0, False)
    result = api.download_highlights("t-1")
    assert result["ok"] is False and "highlights" in result["error"]
    assert api.revealed == []


def test_highlights_report_a_failure_in_plain_words(api):
    def boom(game_id, date, opponent, on_progress=None):
        raise RuntimeError("Download this game's video first.")
    api._worker.export_highlights = boom
    assert api.download_highlights("t-1") == {"ok": False, "error": "Download this game's video first."}


def test_team_highlights_already_saved_are_reported_as_such(api):
    api._worker.export_highlights = lambda game_id, date, opponent, on_progress=None: ("/v/g_highlights", 6, True)
    assert api.download_highlights("t-1") == {"ok": True, "count": 6, "already": True}
    assert api.revealed == []          # the panel has its own "Show folder" button


def test_highlights_panel_lists_team_clips_and_player_recaps(api):
    api._worker.list_highlights = lambda game_id, date, opponent: {
        "team_clips": 11, "players": [{"user_id": 3, "number": "10", "name": "", "saved": True}]}
    assert api.list_highlights("t-1") == {
        "ok": True, "team_clips": 11,
        "players": [{"user_id": 3, "number": "10", "name": "", "saved": True}]}


def test_highlights_panel_reports_a_failure_in_plain_words(api):
    def boom(game_id, date, opponent):
        raise RuntimeError("Couldn't reach Trace.")
    api._worker.list_highlights = boom
    assert api.list_highlights("t-1") == {"ok": False, "error": "Couldn't reach Trace."}


def test_player_recap_download_reports_success_and_failure(api):
    def download(game_id, date, opponent, user_id, on_progress):
        on_progress(30)
        return "/v/g_highlights/player-10.mp4"
    api._worker.download_recap = download
    assert api.download_recap("t-1", 3) == {"ok": True}
    assert api.events == [("recap_progress", {"id": "t-1", "user_id": 3, "percent": 30})]
    def boom(game_id, date, opponent, user_id, on_progress):
        raise RuntimeError("Trace has no recap for this player.")
    api._worker.download_recap = boom
    assert api.download_recap("t-1", 3) == {"ok": False, "error": "Trace has no recap for this player."}


def test_show_highlights_folder(api):
    asked = []
    def folder(game_id, date, opponent, kind):
        asked.append(kind)
        return "/v/g/" + kind
    api._worker.highlights_folder = folder
    assert api.reveal_highlights("t-1") == {"ok": True}
    assert api.reveal_highlights("t-1", "recaps") == {"ok": True}
    assert asked == ["clips", "recaps"] and api.revealed == ["/v/g/clips", "/v/g/recaps"]
    api._worker.highlights_folder = lambda game_id, date, opponent, kind: None
    assert api.reveal_highlights("t-1")["ok"] is False


def test_background_stats_save_never_raises(api):
    api._worker.save_stats = lambda: True
    assert api.save_stats() == {"ok": True, "saved": True}
    def boom():
        raise RuntimeError("offline")
    api._worker.save_stats = boom
    assert api.save_stats() == {"ok": False, "saved": False}


@pytest.fixture
def everything(api):
    """The API fixture with highlights and recaps wired up; `api.log` records worker calls."""
    api.log = []
    api.players = [{"user_id": 1, "number": "2", "name": "Ana R.", "saved": False, "seconds": 224},
                   {"user_id": 2, "number": "7", "name": "Sage S.", "saved": True, "seconds": None},
                   {"user_id": 3, "number": "10", "name": "", "saved": False, "seconds": 212},
                   {"user_id": 4, "number": "15", "name": "", "saved": False, "seconds": 0}]
    api.bad_recaps = set()
    w = api._worker
    def download_game(game_id, *rest):
        api.log.append(("video", game_id))
        return api.saved_per_game
    def export_highlights(game_id, date, opponent, on_progress=None):
        api.log.append(("clips", game_id))
        if on_progress:
            on_progress(3, 11)
        return "/v/g_highlights", 11, False
    def download_recap(game_id, date, opponent, user_id, on_progress=None):
        api.log.append(("recap", user_id))
        if user_id in api.bad_recaps:
            raise RuntimeError("boom")
        on_progress(50)
        return "/v/g_highlights/p.mp4"
    w.download_game = download_game
    w.export_highlights = export_highlights
    w.download_recap = download_recap
    w.list_highlights = lambda game_id, date, opponent: {"team_clips": 0, "players": api.players}
    return api


def _events(api, name):
    return [payload for event, payload in api.events if event == name]


def test_all_recaps_downloads_only_the_missing_ones(everything):
    result = everything.download_all_recaps("t-1")
    assert everything.log == [("recap", 1), ("recap", 3)]         # #7 saved, #15 has none
    assert (result["ok"], result["recaps"], result["failed"]) == (True, 2, 0)
    assert _events(everything, "recaps") == [
        {"id": "t-1", "text": "Checking which recaps are missing…"},
        {"id": "t-1", "text": "Player recap 1 of 2 (#2)…"}, {"id": "t-1", "saved_user": 1},
        {"id": "t-1", "text": "Player recap 2 of 2 (#10)…"}, {"id": "t-1", "saved_user": 3}]
    assert _events(everything, "recap_progress") == [
        {"id": "t-1", "user_id": 1, "percent": 50, "index": 1, "total": 2},
        {"id": "t-1", "user_id": 3, "percent": 50, "index": 2, "total": 2}]
    assert everything.notes == ["Player recaps saved for vs Rovers"]


def test_all_recaps_needs_no_game_video(everything):
    result = everything.download_all_recaps("t-2")                # t-2 has no video saved
    assert result["ok"] and result["recaps"] == 2
    assert not [entry for entry in everything.log if entry[0] in ("video", "clips")]


def test_all_recaps_carries_on_past_a_failed_one(everything):
    everything.bad_recaps = {1}
    result = everything.download_all_recaps("t-1")
    assert (result["recaps"], result["failed"]) == (1, 1)
    assert ("recap", 3) in everything.log


def test_all_recaps_stops_between_files_when_cancelled(everything):
    original = everything._worker.download_recap
    def cancel_after_first(*args):
        original(*args)
        everything.is_cancelled = True
    everything._worker.download_recap = cancel_after_first
    result = everything.download_all_recaps("t-1")
    assert [entry for entry in everything.log if entry[0] == "recap"] == [("recap", 1)]
    assert result["cancelled"] is True and everything.notes == []


def test_all_recaps_reports_a_listing_failure(everything):
    def boom(game_id, date, opponent):
        raise RuntimeError("Couldn't reach Trace.")
    everything._worker.list_highlights = boom
    result = everything.download_all_recaps("t-1")
    assert result["ok"] is False and result["error"] == "Couldn't reach Trace."


def test_highlights_for_a_saved_game_just_cuts_the_clips(everything):
    assert everything.download_highlights("t-1") == {"ok": True, "count": 11, "already": False}
    assert everything.log == [("clips", "t-1")]


def test_highlights_for_a_new_game_do_not_download_the_game(everything):
    assert everything.download_highlights("t-2")["ok"] is True
    assert everything.log == [("clips", "t-2")]                  # straight to the clips


def test_highlights_report_progress_on_the_card(everything):
    everything.download_highlights("t-2")
    assert ("highlights_progress", {"id": "t-2", "done": 3, "total": 11}) in everything.events


def test_game_list_says_how_many_team_clips_each_game_has(api):
    games = list(api._game_cache.values())
    api._worker.games_result = lambda: (games, {"t-1"}, [])
    api._worker.clip_counts = lambda listed: {"t-1": 11}
    views = api.get_games()["games"]
    assert [(v["id"], v["state"], v["clips"]) for v in views] == [("t-1", "saved", 11), ("t-2", "new", 0)]


def test_a_recap_stopped_midway_is_not_counted_as_a_failure(everything):
    def stopped_midway(game_id, date, opponent, user_id, on_progress=None):
        everything.is_cancelled = True
        raise RuntimeError("The recap download didn't finish (ffmpeg exit -15).")
    everything._worker.download_recap = stopped_midway
    result = everything.download_all_recaps("t-1")
    assert (result["cancelled"], result["failed"], result["recaps"]) == (True, 0, 0)


def test_thumbnail_request_says_which_game_folder_it_belongs_to(api):
    asked = []
    api._worker.get_thumb = lambda *args: asked.append(args) or "data:x"
    assert api.get_thumb("t", "t-1") == "data:x"
    assert asked == [("t", "t-1", "2026-06-04", "Rovers")]


def test_analytics_games_carry_the_trace_score(api):
    from gui import worker
    from trace_grabber import analytics
    def split(num):
        return analytics.compute_split([], analytics.GameMeta(num, "2026-06-04", "Rovers", "home", 5400))
    api._game_cache = {"t-1": Game("t-1", "t", "2026-06-04", "Rovers", "T vs. Rovers", score_us=2, score_them=4),
                       "t-2": Game("t-2", "t", "2026-06-01", "United", "T vs. United")}
    api._worker.compute_analytics = lambda on_progress, refresh=False: worker.AnalyticsResult(
        splits=[split(1), split(2), split(3)])
    games = api.get_analytics()["games"]
    assert [g["score"] for g in games] == [{"us": 2, "them": 4, "result": "loss"}, None, None]


def test_refresh_button_asks_for_fresh_stats(api):
    from gui import worker
    asked = []
    def compute(on_progress, refresh=False):
        asked.append(refresh)
        return worker.AnalyticsResult(splits=[])
    api._worker.compute_analytics = compute
    api.get_analytics()
    api.get_analytics(True)
    assert asked == [False, True]


@pytest.fixture
def updater(api, monkeypatch, tmp_path):
    """The API with the updates module faked: `api.release` is what GitHub offers."""
    from gui import app
    from trace_grabber import updates
    api.release = updates.Release("9.9.9", ["Faster.", "Fewer bugs."], "https://gh/x.zip", 10, None, "x.zip")
    api.calls = []
    def check(current):
        if api.release == "offline":
            raise RuntimeError("curl: could not resolve host")
        return api.release
    def download(release, folder, on_progress=None):
        api.calls.append(("download", release.version))
        on_progress(50)
        return tmp_path / release.asset
    def start_install(path):
        api.calls.append(("install", path.name))
        return api.installer_takes_over
    api.installer_takes_over = True
    api.quit_scheduled = []
    monkeypatch.setattr(app.updates, "check", check)
    monkeypatch.setattr(app.updates, "download", download)
    monkeypatch.setattr(app.updates, "start_install", start_install)
    monkeypatch.setattr(app.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(app, "DATA", tmp_path)
    monkeypatch.setattr(api, "_quit_soon", lambda: api.quit_scheduled.append(True))
    return api


def test_update_check_reports_a_newer_version_and_its_changes(updater):
    found = updater.check_update()
    assert (found["ok"], found["available"], found["version"], found["notes"], found["can_install"]) == (
        True, True, "9.9.9", ["Faster.", "Fewer bugs."], True)


def test_update_check_when_up_to_date_or_offline(updater):
    updater.release = None
    assert updater.check_update()["available"] is False
    updater.release = "offline"
    result = updater.check_update()
    assert result["ok"] is False and "connection" in result["error"]


def test_running_from_source_is_offered_the_download_page_not_an_install(updater, monkeypatch):
    from gui import app
    monkeypatch.setattr(app.paths, "is_frozen", lambda: False)
    assert updater.check_update()["can_install"] is False


def test_update_now_downloads_installs_and_quits(updater):
    updater.check_update()
    assert updater.install_update() == {"ok": True, "restarting": True}
    assert updater.calls == [("download", "9.9.9"), ("install", "x.zip")]
    assert ("update_progress", {"percent": 50}) in updater.events and updater.quit_scheduled == [True]


def test_update_that_cannot_install_itself_shows_the_download_instead(updater):
    updater.installer_takes_over = False
    updater.check_update()
    assert updater.install_update() == {"ok": True, "manual": True}
    assert updater.revealed and updater.quit_scheduled == []


def test_a_failed_update_download_keeps_the_app_running(updater, monkeypatch):
    from gui import app
    def broken(release, folder, on_progress=None):
        raise RuntimeError("The download didn't match its checksum, so it was not installed.")
    monkeypatch.setattr(app.updates, "download", broken)
    updater.check_update()
    result = updater.install_update()
    assert result["ok"] is False and "checksum" in result["error"] and updater.quit_scheduled == []


def test_whats_new_is_offered_once_after_updating(updater, tmp_path, monkeypatch):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "is_frozen", lambda: False)      # read the changelog from the source tree
    (tmp_path / "accounts.json").write_text("{}")
    shown = updater.whats_new()
    assert shown["version"] == paths.APP_VERSION and shown["notes"]
    updater.whats_new_seen()
    assert updater.whats_new() is None


def test_everything_saved_for_a_game_can_be_played_inside_the_app(api):
    api._media = SimpleNamespace(url_for=lambda path: "http://127.0.0.1:1/tok/" + str(path).rsplit("/", 1)[-1])
    saved = {"full": ["/v/g_half1.mp4", "/v/g_half2.mp4"], "reel": "/v/H/Team Highlight Reel.mp4",
             "clips": [{"label": "Shot · 1st half 4:55", "path": "/v/H/01.mp4", "half": 1, "start": 295}],
             "recaps": [{"label": "#10", "path": "/v/P/player-10.mp4"}]}
    api._worker.game_media = lambda game_id, date, opponent: saved
    media = api.game_media("t-1")
    assert media["full"] == [{"label": "1st half", "url": "http://127.0.0.1:1/tok/g_half1.mp4"},
                             {"label": "2nd half", "url": "http://127.0.0.1:1/tok/g_half2.mp4"}]
    assert media["reel"] == "http://127.0.0.1:1/tok/Team Highlight Reel.mp4"
    assert media["clips"] == [{"label": "Shot · 1st half 4:55", "url": "http://127.0.0.1:1/tok/01.mp4",
                               "half": 1, "start": 295}]
    assert media["recaps"] == [{"label": "#10", "url": "http://127.0.0.1:1/tok/player-10.mp4"}]
    saved.update(full=["/v/g.mp4"], reel=None)
    again = api.game_media("t-1")
    assert again["full"] == [{"label": "Full game", "url": "http://127.0.0.1:1/tok/g.mp4"}] and again["reel"] is None
    assert api.game_media("nope") == {"full": [], "reel": None, "clips": [], "recaps": []}


def test_analytics_games_carry_their_timeline(api):
    from gui import worker
    from trace_grabber import analytics
    split = analytics.compute_split([], analytics.GameMeta(1, "2026-06-04", "Rovers", "home", 5400))
    line = {"duration": 4600, "half1": 2300, "moments": [{"t": 50, "half": 1, "label": "shot", "len": 5}]}
    api._worker.compute_analytics = lambda on_progress, refresh=False: worker.AnalyticsResult(
        splits=[split], timelines={1: line})
    assert api.get_analytics()["games"][0]["timeline"] == line


@pytest.fixture
def updater(api, monkeypatch, tmp_path):
    """The API with the updates module faked: `api.release` is what GitHub offers."""
    from gui import app
    from trace_grabber import updates
    api.release = updates.Release("9.9.9", ["Faster.", "Fewer bugs."], "https://gh/x.zip", 10, None, "x.zip")
    api.calls = []
    def check(current):
        if api.release == "offline":
            raise RuntimeError("curl: could not resolve host")
        return api.release
    def download(release, folder, on_progress=None):
        api.calls.append(("download", release.version))
        on_progress(50)
        return tmp_path / release.asset
    def start_install(path):
        api.calls.append(("install", path.name))
        return api.installer_takes_over
    api.installer_takes_over = True
    api.quit_scheduled = []
    monkeypatch.setattr(app.updates, "check", check)
    monkeypatch.setattr(app.updates, "download", download)
    monkeypatch.setattr(app.updates, "start_install", start_install)
    monkeypatch.setattr(app.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(app, "DATA", tmp_path)
    monkeypatch.setattr(api, "_quit_soon", lambda: api.quit_scheduled.append(True))
    return api


def test_update_check_reports_a_newer_version_and_its_changes(updater):
    found = updater.check_update()
    assert (found["ok"], found["available"], found["version"], found["notes"], found["can_install"]) == (
        True, True, "9.9.9", ["Faster.", "Fewer bugs."], True)


def test_update_check_when_up_to_date_or_offline(updater):
    updater.release = None
    assert updater.check_update()["available"] is False
    updater.release = "offline"
    result = updater.check_update()
    assert result["ok"] is False and "connection" in result["error"]


def test_running_from_source_is_offered_the_download_page_not_an_install(updater, monkeypatch):
    from gui import app
    monkeypatch.setattr(app.paths, "is_frozen", lambda: False)
    assert updater.check_update()["can_install"] is False


def test_update_now_downloads_installs_and_quits(updater):
    updater.check_update()
    assert updater.install_update() == {"ok": True, "restarting": True}
    assert updater.calls == [("download", "9.9.9"), ("install", "x.zip")]
    assert ("update_progress", {"percent": 50}) in updater.events and updater.quit_scheduled == [True]


def test_update_that_cannot_install_itself_shows_the_download_instead(updater):
    updater.installer_takes_over = False
    updater.check_update()
    assert updater.install_update() == {"ok": True, "manual": True}
    assert updater.revealed and updater.quit_scheduled == []


def test_a_failed_update_download_keeps_the_app_running(updater, monkeypatch):
    from gui import app
    def broken(release, folder, on_progress=None):
        raise RuntimeError("The download didn't match its checksum, so it was not installed.")
    monkeypatch.setattr(app.updates, "download", broken)
    updater.check_update()
    result = updater.install_update()
    assert result["ok"] is False and "checksum" in result["error"] and updater.quit_scheduled == []


def test_whats_new_is_offered_once_after_updating(updater, tmp_path, monkeypatch):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "is_frozen", lambda: False)      # read the changelog from the source tree
    (tmp_path / "accounts.json").write_text("{}")
    shown = updater.whats_new()
    assert shown["version"] == paths.APP_VERSION and shown["notes"]
    updater.whats_new_seen()
    assert updater.whats_new() is None


def test_quitting_for_an_update_really_ends_the_app(api, monkeypatch):
    # The Mac installer waits for the app to be gone before swapping it, so a
    # process that lingers after its window closes would block the update.
    from gui import app
    order = []
    api._window = SimpleNamespace(destroy=lambda: order.append("window closed"))
    monkeypatch.setattr(app.threading, "Timer",
                        lambda delay, fn: SimpleNamespace(start=lambda: (order.append(f"after {delay}s"), fn())))
    monkeypatch.setattr(app.os, "_exit", lambda code: order.append(f"process ended ({code})"))
    api._quit_soon()
    assert order[1] == "window closed" and order[-1] == "process ended (0)"


def test_open_folder_works_for_a_game_that_is_not_downloaded(api):
    api._worker.folder_to_open = lambda game_id, date, opponent: "/v/2026-06-01_vs-united"
    assert api.open_game_folder("t-2") == {"ok": True}
    assert api.opened == ["/v/2026-06-01_vs-united"]


@pytest.fixture
def auto(everything, monkeypatch, tmp_path):
    """The `everything` API with settings kept in a temp folder and the system hooks recorded."""
    from gui import app
    api = everything
    api.system = []
    monkeypatch.setattr(app, "DATA", tmp_path)
    monkeypatch.setattr(app.platform_tasks, "schedule_disable", lambda: api.system.append("old scheduler off"))
    monkeypatch.setattr(app.platform_tasks, "login_enable", lambda: api.system.append("login on"))
    monkeypatch.setattr(app.platform_tasks, "login_disable", lambda: api.system.append("login off"))
    api._worker.list_accounts = lambda: {"active": "demo", "accounts": [{"id": "demo", "label": "Demo"}]}
    api._schedule_auto = lambda: api.system.append("timer set")
    return api


def test_first_open_asks_the_welcome_questions_once(auto):
    assert auto.auto_settings() == {"auto": False, "login": False, "welcome": True}
    assert auto.finish_welcome(True, True) == {"ok": True}
    assert auto.auto_settings() == {"auto": True, "login": True, "welcome": False}
    assert auto.system == ["old scheduler off", "timer set", "login on"]


def test_switching_auto_on_skips_every_game_already_listed(auto):
    auto.set_auto(True)
    result = auto.auto_check()
    assert (result["ran"], result["games"]) == (True, 0) and auto.log == []


def test_auto_fetches_a_game_added_later_with_highlights_and_recaps(auto):
    from gui import app
    auto.set_auto(True)
    new = Game("t-3", "t", "2026-06-10", "Athletic", "T vs. Athletic")
    games = [new] + list(auto._game_cache.values())
    auto._worker.list_games = lambda: (games, {"t-1"})
    result = auto.auto_check()
    assert auto.log == [("video", "t-3"), ("clips", "t-3"), ("recap", 1), ("recap", 3)]
    assert (result["ran"], result["games"]) == (True, 1)
    states = [payload["running"] for event, payload in auto.events if event == "auto"]
    assert states[0] is True and states[-1] is False
    assert auto.notes[-1] == "Automatic download: 1 new game saved"


def test_auto_does_nothing_when_off_or_while_you_are_downloading(auto):
    assert auto.auto_check()["ran"] is False                   # switched off
    auto.set_auto(True)
    auto._user_jobs = 1                                        # you are in the middle of a download
    assert auto.auto_check()["ran"] is False


def test_closing_the_window_keeps_the_app_running_only_with_auto_on(auto):
    assert auto.keep_running() is False
    auto.set_auto(True)
    assert auto.keep_running() is True
    auto._quit_soon = lambda: None
    auto.quit_app()
    assert auto.keep_running() is False                        # Quit means quit


def test_start_at_login_follows_its_switch(auto):
    auto.set_login(True)
    auto.set_login(False)
    assert auto.system == ["login on", "login off"] and auto.auto_settings()["login"] is False


def test_heat_map_reports_missing_until_asked_to_fetch(api):
    calls = []
    def heatmap(game_id, date, opponent, fetch):
        calls.append(fetch)
        return {"whole": {"samples": 3}} if fetch else None
    api._worker.heatmap = heatmap
    game_id = next(iter(api._game_cache))
    assert api.get_heatmap(game_id) == {"ok": False, "missing": True}
    assert api.get_heatmap(game_id, True) == {"ok": True, "heat": {"whole": {"samples": 3}}}
    assert calls == [False, True]


def test_heat_map_explains_a_game_trace_never_tracked(api):
    api._worker.heatmap = lambda *args: None
    result = api.get_heatmap(next(iter(api._game_cache)), True)
    assert result["ok"] is False and "tracking" in result["error"]


def test_turning_automatic_downloads_on_also_opens_the_app_at_login(auto):
    assert auto.set_auto(True) is True
    assert "login on" in auto.system and auto.auto_settings()["login"] is True


def test_login_choice_survives_while_automatic_downloads_stay_on(auto):
    auto.set_auto(True)
    auto.set_login(False)
    auto.system.clear()
    auto.set_auto(True)                              # already on: the choice isn't overridden
    assert "login on" not in auto.system and auto.auto_settings()["login"] is False


def test_turning_automatic_downloads_off_stops_opening_at_login(auto):
    auto.set_auto(True)
    auto.system.clear()
    assert auto.set_auto(False) is False
    assert "login off" in auto.system and auto.auto_settings()["login"] is False


def test_welcome_can_still_decline_opening_at_login(auto):
    auto.finish_welcome(True, False)
    assert auto.auto_settings() == {"auto": True, "login": False, "welcome": False}
    assert auto.system[-1] == "login off"


def test_game_download_progress_reaches_the_page_with_time_left(api):
    def download_game(game_id, team_id, date, opponent, on_progress):
        on_progress({"half": 1, "percent": 25, "speed": 8.4, "eta": 360, "joining": False})
        return 2
    api._worker.download_game = download_game
    api.download_game("t-1")
    assert ("progress", {"id": "t-1", "half": 1, "percent": 25, "speed": 8.4, "eta": 360,
                         "joining": False}) in api.events


def test_game_list_says_which_games_have_a_cut_off_download(api):
    games = list(api._game_cache.values())
    api._worker.games_result = lambda: (games, {"t-1"}, [])
    api._worker.clip_counts = lambda listed: {}
    api._worker.partials = lambda listed, done: {"t-2": 0.62}
    views = api.get_games()["games"]
    assert [(v["id"], v["partial"]) for v in views] == [("t-1", None), ("t-2", 0.62)]


def test_a_cut_off_download_can_be_discarded(api):
    thrown = []
    api._worker.discard_partial = lambda game_id, date, opponent: thrown.append((game_id, date, opponent)) or True
    assert api.discard_download("t-2") == {"ok": True}
    assert thrown == [("t-2", "2026-06-01", "United")]
    assert api.discard_download("nope")["ok"] is False


def test_a_game_that_will_not_fit_says_so(api):
    from trace_grabber import space
    def download_game(*args):
        raise space.NotEnoughSpace("Not enough disk space: this game needs about 9.0 GB and 3.0 GB is free.")
    api._worker.download_game = download_game
    result = api.download_game("t-1")
    assert result["ok"] is False and result["no_space"] is True
    assert ("error", {"id": "t-1", "message": result["error"]}) in api.events
    assert api.notes == []


def test_any_other_failure_is_not_a_disk_problem(api):
    def download_game(*args):
        raise RuntimeError("The connection dropped.")
    api._worker.download_game = download_game
    assert api.download_game("t-1")["no_space"] is False


def test_free_space_is_reported_in_words_and_flagged_when_low(api):
    api._worker.disk_free = lambda: 212_000_000_000
    assert api.disk_free() == {"ok": True, "free": 212_000_000_000, "text": "212 GB", "low": False}
    api._worker.disk_free = lambda: 3_200_000_000
    assert api.disk_free()["low"] is True and api.disk_free()["text"] == "3.2 GB"
    def gone():
        raise OSError("drive not connected")
    api._worker.disk_free = gone
    assert api.disk_free() == {"ok": False}
