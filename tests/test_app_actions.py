from types import SimpleNamespace

import pytest

from trace_grabber import scorebug
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
        missing=lambda games, done: set(),
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
    assert media["full"] == [{"label": "1st half", "url": "http://127.0.0.1:1/tok/g_half1.mp4", "name": "g_half1.mp4"},
                             {"label": "2nd half", "url": "http://127.0.0.1:1/tok/g_half2.mp4", "name": "g_half2.mp4"}]
    assert media["reel"] == "http://127.0.0.1:1/tok/Team Highlight Reel.mp4"
    assert media["clips"] == [{"label": "Shot · 1st half 4:55", "url": "http://127.0.0.1:1/tok/01.mp4",
                               "half": 1, "start": 295}]
    assert media["recaps"] == [{"label": "#10", "url": "http://127.0.0.1:1/tok/player-10.mp4"}]
    saved.update(full=["/v/g.mp4"], reel=None)
    again = api.game_media("t-1")
    assert again["full"] == [{"label": "Full game", "url": "http://127.0.0.1:1/tok/g.mp4", "name": "g.mp4"}] and again["reel"] is None
    assert api.game_media("nope") == {"full": [], "reel": None, "clips": [], "recaps": [], "mine": [], "edited": []}


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
    api._schedule_auto = lambda first_in_secs=None: api.system.append("timer set")
    api._worker.logged_in = lambda: True
    api._worker.login_detail = lambda: "not logged in"       # what Trace answers when the login has lapsed
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


def _config(auto, tmp_path, hours=3):
    (tmp_path / "config.yaml").write_text(
        f"output_dir: {tmp_path}\ncheck_interval_hours: {hours}\nquality: highest\n")
    auto._worker.reload_config = lambda: True


def _new_game(auto):
    """A game that appeared after automatic downloads were switched on."""
    auto.set_auto(True)
    new = Game("t-3", "t", "2026-06-10", "Athletic", "T vs. Athletic")
    games = [new] + list(auto._game_cache.values())
    auto._worker.list_games = lambda: (games, {"t-1"})
    auto.system.clear()


def test_automatic_options_start_as_everything_every_three_hours(auto, tmp_path):
    _config(auto, tmp_path)
    assert auto.auto_options() == {"full": True, "highlights": True, "recaps": True, "interval": 3}


def test_choosing_what_automatic_downloads_fetch(auto, tmp_path):
    _config(auto, tmp_path)
    assert auto.set_auto_choices({"full": True, "highlights": False, "recaps": False}) == {
        "ok": True, "full": True, "highlights": False, "recaps": False}
    assert auto.auto_options()["highlights"] is False


def test_the_last_choice_cannot_be_switched_off(auto, tmp_path):
    _config(auto, tmp_path)
    auto.set_auto_choices({"full": True, "highlights": False, "recaps": False})
    result = auto.set_auto_choices({"full": False, "highlights": False, "recaps": False})
    assert result["ok"] is False and result["full"] is True and "at least one" in result["error"]
    assert auto.auto_options()["full"] is True


def test_changing_how_often_it_checks_restarts_the_timer(auto, tmp_path):
    _config(auto, tmp_path)
    auto.set_auto(True)
    auto.system.clear()
    assert auto.save_settings({"interval": 12}) == {"ok": True}
    assert auto.auto_options()["interval"] == 12 and auto.system == ["timer set"]


def test_changing_the_interval_with_automatic_downloads_off_starts_no_timer(auto, tmp_path):
    _config(auto, tmp_path)
    auto.save_settings({"interval": 6})
    assert auto.auto_options()["interval"] == 6 and auto.system == []


def test_an_interval_that_is_not_offered_is_not_saved(auto, tmp_path):
    _config(auto, tmp_path)
    for junk in (0, 2, -3, "soon", None):
        auto.save_settings({"interval": junk})
    assert auto.auto_options()["interval"] == 3


def test_a_hand_edited_interval_is_reported_as_it_is(auto, tmp_path):
    _config(auto, tmp_path, hours=2)
    assert auto.auto_options()["interval"] == 2


def test_auto_with_only_the_full_game_fetches_nothing_else(auto, tmp_path):
    _config(auto, tmp_path)
    _new_game(auto)
    auto.set_auto_choices({"full": True, "highlights": False, "recaps": False})
    assert auto.auto_check()["games"] == 1
    assert auto.log == [("video", "t-3")]


def test_auto_without_the_full_game_fetches_the_rest_once(auto, tmp_path):
    _config(auto, tmp_path)
    _new_game(auto)
    auto.set_auto_choices({"full": False, "highlights": True, "recaps": True})
    result = auto.auto_check()
    assert auto.log == [("clips", "t-3"), ("recap", 1), ("recap", 3)]
    assert result["games"] == 1 and auto.notes[-1] == "Automatic download: 1 new game saved"
    auto.log.clear()
    auto.auto_check()
    assert auto.log == []                                      # handled: not fetched again


def test_auto_tries_again_later_when_trace_has_nothing_ready(auto, tmp_path):
    _config(auto, tmp_path)
    _new_game(auto)
    auto.set_auto_choices({"full": False, "highlights": True, "recaps": False})
    def nothing_yet(game_id, date, opponent, on_progress=None):
        auto.log.append(("clips", game_id))
        raise RuntimeError("Trace has no moments for this game, so there are no highlights to make.")
    auto._worker.export_highlights = nothing_yet
    assert auto.auto_check()["games"] == 0
    auto.auto_check()
    assert auto.log == [("clips", "t-3"), ("clips", "t-3")] and auto.notes == []


def test_auto_stops_and_says_so_once_when_the_disk_is_full(auto, tmp_path):
    from trace_grabber import space
    _config(auto, tmp_path)
    _new_game(auto)
    def no_room(*args):
        raise space.NotEnoughSpace("Not enough disk space: this game needs about 9.0 GB and 3.0 GB is free.")
    auto._worker.download_game = no_room
    auto.auto_check()
    auto.auto_check()
    assert auto.notes == ["Automatic downloads paused: not enough disk space."]
    assert auto.log == []                                      # no highlights or recaps either


def test_auto_says_so_again_if_the_disk_fills_a_second_time(auto, tmp_path):
    from trace_grabber import space
    _config(auto, tmp_path)
    _new_game(auto)
    works = auto._worker.download_game
    def no_room(*args):
        raise space.NotEnoughSpace("Not enough disk space.")
    auto._worker.download_game = no_room
    auto.auto_check()
    auto._worker.download_game = works                         # room was made
    auto.auto_check()
    auto._worker.list_games = lambda: ([Game("t-4", "t", "2026-06-12", "Town", "T vs. Town")], set())
    auto._worker.download_game = no_room
    auto.auto_check()
    assert auto.notes.count("Automatic downloads paused: not enough disk space.") == 2


def test_status_carries_the_automatic_options(auto, tmp_path):
    _config(auto, tmp_path)
    auto._worker.logged_in = lambda: True
    auto._worker.login_detail = lambda: ""
    assert auto.get_status()["auto_options"] == {"full": True, "highlights": True, "recaps": True, "interval": 3}


def test_a_discard_that_was_refused_says_so(api):
    api._worker.discard_partial = lambda game_id, date, opponent: False      # saved, or downloading right now
    result = api.discard_download("t-2")
    assert result["ok"] is False and "downloading or already saved" in result["error"]


def test_switching_auto_off_during_a_run_is_not_undone_by_it(auto, tmp_path):
    from trace_grabber import autodl
    _config(auto, tmp_path)
    _new_game(auto)
    auto.set_auto_choices({"full": False, "highlights": True, "recaps": False})
    def export_highlights(game_id, date, opponent, on_progress=None):
        auto.set_auto(False)                       # the person switches it off while this runs
        return "/v/g_highlights", 11, False
    auto._worker.export_highlights = export_highlights
    auto.auto_check()
    assert auto.auto_settings()["auto"] is False
    assert "t-3" in autodl.load(tmp_path).seen["demo"]         # and the game is still noted as handled


def test_a_choice_changed_during_a_run_survives_the_low_disk_note(auto, tmp_path):
    from trace_grabber import autodl, space
    _config(auto, tmp_path)
    _new_game(auto)
    def no_room(*args):
        auto.set_auto_choices({"full": True, "highlights": False, "recaps": True})
        raise space.NotEnoughSpace("Not enough disk space.")
    auto._worker.download_game = no_room
    auto.auto_check()
    state = autodl.load(tmp_path)
    assert (state.highlights, state.low_disk) == (False, True)


def test_bookmarks_reach_the_page_and_changes_come_back_as_the_new_list(api):
    marks = [{"id": "a1", "t": 30.0, "half": 1, "note": "", "made": "2026-10-07"}]
    asked = []
    api._worker.bookmarks = lambda game_id, date, opponent: marks
    api._worker.add_bookmark = lambda *args: asked.append(("add", args)) or ("a1", marks)
    api._worker.edit_bookmark = lambda *args: asked.append(("edit", args)) or marks
    api._worker.remove_bookmark = lambda *args: asked.append(("remove", args)) or []
    assert api.bookmarks("t-1") == {"ok": True, "bookmarks": marks}
    assert api.add_bookmark("t-1", 30, 1) == {"ok": True, "id": "a1", "bookmarks": marks}
    assert api.edit_bookmark("t-1", "a1", "note") == {"ok": True, "bookmarks": marks}
    assert api.remove_bookmark("t-1", "a1") == {"ok": True, "bookmarks": []}
    assert asked == [("add", ("t-1", "2026-06-04", "Rovers", 30, 1, "")),
                     ("edit", ("t-1", "2026-06-04", "Rovers", "a1", "note")),
                     ("remove", ("t-1", "2026-06-04", "Rovers", "a1"))]


def test_a_bookmark_that_cannot_be_saved_says_why(api):
    def read_only(*args):
        raise PermissionError("the folder is read-only")
    api._worker.add_bookmark = read_only
    assert api.add_bookmark("t-1", 30, 1) == {"ok": False, "error": "the folder is read-only"}
    assert api.bookmarks("nope") == {"ok": False, "error": "game not found"}


def test_an_exported_clip_comes_back_ready_to_play(api):
    api._media = SimpleNamespace(url_for=lambda path: "http://127.0.0.1:1/tok/" + str(path).rsplit("/", 1)[-1])
    asked = []
    api._worker.export_clip = lambda *args: asked.append(args) or "/v/g/My Clips/half2_12m04s-12m31s.mp4"
    assert api.export_clip("t-1", "g_half2.mp4", 724.5, 751.5) == {
        "ok": True, "label": "2nd half 12:04 – 12:31", "url": "http://127.0.0.1:1/tok/half2_12m04s-12m31s.mp4"}
    assert asked == [("t-1", "2026-06-04", "Rovers", "g_half2.mp4", 724.5, 751.5)]


def test_a_clip_that_fails_says_why(api):
    def too_long(*args):
        raise RuntimeError("A clip can be from 1 second to 10 minutes long.")
    api._worker.export_clip = too_long
    assert api.export_clip("t-1", "g.mp4", 0, 900) == {"ok": False, "error": "A clip can be from 1 second to 10 minutes long."}


def test_your_own_clips_can_be_played_in_the_app(api):
    api._media = SimpleNamespace(url_for=lambda path: "http://127.0.0.1:1/tok/" + str(path).rsplit("/", 1)[-1])
    api._worker.game_media = lambda game_id, date, opponent: {
        "full": [], "reel": None, "clips": [], "recaps": [],
        "mine": [{"label": "0:10 – 0:20", "path": "/v/g/My Clips/00m10s-00m20s.mp4"}]}
    assert api.game_media("t-1")["mine"] == [{"label": "0:10 – 0:20", "url": "http://127.0.0.1:1/tok/00m10s-00m20s.mp4"}]
    assert api.game_media("nope")["mine"] == []


def test_your_own_clips_can_be_shown_in_their_folder(api):
    api._worker.highlights_folder = lambda game_id, date, opponent, kind: "/v/g/My Clips" if kind == "mine" else None
    assert api.reveal_highlights("t-1", "mine") == {"ok": True} and api.revealed == ["/v/g/My Clips"]
    api._worker.highlights_folder = lambda *args: None
    assert "clips of your own" in api.reveal_highlights("t-1", "mine")["error"]


def test_full_screen_is_asked_of_the_window_and_never_raises(api):
    calls = []
    api._window = SimpleNamespace(toggle_fullscreen=lambda: calls.append("toggled"))
    assert api.toggle_fullscreen() == {"ok": True} and calls == ["toggled"]
    def broken():
        raise RuntimeError("not supported here")
    api._window = SimpleNamespace(toggle_fullscreen=broken)
    assert api.toggle_fullscreen() == {"ok": False}
    api._window = None
    assert api.toggle_fullscreen() == {"ok": False}


def test_a_saved_game_whose_video_is_gone_is_listed_as_missing(api):
    games = list(api._game_cache.values())
    api._worker.games_result = lambda: (games, {"t-1", "t-2"}, [])
    api._worker.clip_counts = lambda listed: {}
    api._worker.missing = lambda listed, done: {"t-2"}
    assert [(v["id"], v["state"]) for v in api.get_games()["games"]] == [("t-1", "saved"), ("t-2", "missing")]


def _picker(api, answer):
    asked = []
    def create_file_dialog(kind, **options):
        asked.append(options)
        if isinstance(answer, Exception):
            raise answer
        return answer
    api._window = SimpleNamespace(create_file_dialog=create_file_dialog)
    return asked


def test_finding_a_moved_video_remembers_where_it_is(api):
    found = []
    api._worker.set_found = lambda game_id, files: found.append((game_id, files)) or True
    asked = _picker(api, ("/Volumes/Games/rovers_half1.mp4", "/Volumes/Games/rovers_half2.mp4"))
    assert api.find_video("t-1") == {"ok": True}
    assert found == [("t-1", ["/Volumes/Games/rovers_half1.mp4", "/Volumes/Games/rovers_half2.mp4"])]
    assert asked[0]["allow_multiple"] is True
    _picker(api, "/Volumes/Games/rovers.mp4")                  # some versions answer with one path, not a list
    api.find_video("t-1")
    assert found[-1] == ("t-1", ["/Volumes/Games/rovers.mp4"])


def test_cancelling_the_picker_changes_nothing(api):
    api._worker.set_found = lambda *args: pytest.fail("nothing was chosen")
    _picker(api, None)
    assert api.find_video("t-1") == {"ok": False}
    _picker(api, RuntimeError("no window"))
    assert api.find_video("t-1") == {"ok": False, "error": "no window"}
    assert api.find_video("nope") == {"ok": False}


def test_storage_reaches_the_page_with_the_name_of_the_bin(api, monkeypatch):
    from gui import app
    monkeypatch.setattr(app.platform_tasks, "bin_name", lambda: "Trash")
    monkeypatch.setattr(app.platform_tasks, "can_trash", lambda: True)
    asked = []
    report = {"rows": [{"id": "t-1", "title": "vs Rovers", "total": 1100}], "used": 1525, "other": 25, "free": 50}
    api._worker.storage = lambda games: asked.append([g.id for g in games]) or report
    assert api.storage() == {"ok": True, **report, "bin": "Trash", "can_remove": True}
    monkeypatch.setattr(app.platform_tasks, "can_trash", lambda: False)
    assert api.storage()["can_remove"] is False
    asked.pop()
    assert asked == [["t-1", "t-2"]]
    def unreadable(games):
        raise OSError("the drive is not connected")
    api._worker.storage = unreadable
    assert api.storage() == {"ok": False, "error": "the drive is not connected"}


def test_removing_a_game_says_how_much_went_to_the_bin(api, monkeypatch):
    from gui import app
    monkeypatch.setattr(app.platform_tasks, "bin_name", lambda: "Recycle Bin")
    asked = []
    listed = []
    def remove_game(*args, games=()):
        asked.append(args)
        listed.append([g.id for g in games])
        return 4_200_000_000
    api._worker.remove_game = remove_game
    assert api.remove_game("t-1") == {"ok": True, "freed": 4_200_000_000, "bin": "Recycle Bin"}
    assert api.remove_game("t-1", True)["ok"] is True
    assert asked == [("t-1", "2026-06-04", "Rovers", False), ("t-1", "2026-06-04", "Rovers", True)]
    assert listed == [["t-1", "t-2"], ["t-1", "t-2"]]          # the worker is told what else is listed, to spot a shared folder


def test_a_removal_that_fails_says_why(api):
    def refuse(*args, **kwargs):
        raise RuntimeError("This game is downloading. Stop the download first.")
    api._worker.remove_game = refuse
    assert api.remove_game("t-1") == {"ok": False, "error": "This game is downloading. Stop the download first."}
    assert api.remove_game("nope") == {"ok": False, "error": "game not found"}


def test_the_file_name_setting_is_previewed_and_saved(auto, tmp_path):
    _config(auto, tmp_path)
    auto._worker.team_label = lambda: "Tiger Sharks"
    assert auto.preview_file_name("") == {"name": "2026-06-04_vs-rovers.mp4", "custom": False}
    assert auto.preview_file_name("{team} vs {opponent} {date}") == {
        "name": "Tiger Sharks vs Rovers 2026-06-04.mp4", "custom": True}
    assert auto.preview_file_name("???") == {"name": "2026-06-04_vs-rovers.mp4", "custom": False}
    assert auto.save_settings({"file_name": "  {team} vs {opponent}  "}) == {"ok": True}
    auto._worker.logged_in = lambda: True
    auto._worker.login_detail = lambda: ""
    assert auto.get_status()["settings"]["file_name"] == "{team} vs {opponent}"
    auto.save_settings({"file_name": None})
    assert auto.get_status()["settings"]["file_name"] == ""


def test_an_expired_login_found_by_a_background_check_is_told_once(auto, tmp_path):
    _config(auto, tmp_path)
    _new_game(auto)
    listing = auto._worker.list_games
    auto._worker.logged_in = lambda: False
    auto._worker.list_games = lambda: pytest.fail("there is nothing to list while logged out")
    assert auto.auto_check() == {"ran": True, "games": 0, "expired": True}
    auto.auto_check()
    wanted = "Your Trace login has expired. Open TraceDown and reconnect to keep downloading new games."
    assert auto.notes == [wanted] and auto.log == []
    assert auto.tray_status().startswith("Trace login expired")
    auto._worker.logged_in = lambda: True                        # reconnected
    auto._worker.list_games = listing
    auto.auto_check()
    assert not auto.tray_status().startswith("Trace login expired")
    auto._worker.logged_in = lambda: False                       # and months later it lapses again
    auto._worker.list_games = lambda: pytest.fail("nothing to list")
    auto.auto_check()
    assert auto.notes.count(wanted) == 2


def test_reconnecting_in_the_window_clears_the_expired_status(auto, tmp_path):
    _config(auto, tmp_path)
    auto.set_auto(True)
    auto._worker.logged_in = lambda: False
    auto.auto_check()
    auto._worker.logged_in = lambda: True
    auto._worker.login_detail = lambda: ""
    auto.get_status()
    assert not auto.tray_status().startswith("Trace login expired")


def test_the_tray_says_what_is_downloading_and_when_it_last_checked(auto, tmp_path):
    _config(auto, tmp_path)
    _new_game(auto)
    refreshed = []
    auto._tray = SimpleNamespace(refresh=lambda: refreshed.append(auto.tray_status()), set_visible=lambda on: None)
    during = []
    def download_game(game_id, team_id, date, opponent, on_progress):
        for percent in (0, 2, 40, 41, 90):
            on_progress({"half": 1, "percent": percent, "speed": 8.0, "eta": 60, "joining": False})
        during.append(auto.tray_status())
        return 2
    auto._worker.download_game = download_game
    auto.auto_check()
    assert during == ["Downloading vs Athletic · 90%"]
    assert "Downloading vs Athletic · 0%" in refreshed and "Downloading vs Athletic · 40%" in refreshed
    assert "Downloading vs Athletic · 2%" not in refreshed and "Downloading vs Athletic · 41%" not in refreshed      # not on every tick
    assert auto.tray_status().startswith("Last checked today at ") and auto.tray_status().endswith("· 1 new game saved")
    assert refreshed[-1] == auto.tray_status()


def test_stats_and_pictures_are_copied_through_the_app(api, monkeypatch):
    from gui import app
    copied = []
    monkeypatch.setattr(app.platform_tasks, "copy_text", lambda text: copied.append(("text", text)))
    monkeypatch.setattr(app.platform_tasks, "copy_image", lambda png: copied.append(("png", png)))
    assert api.copy_text("Shots 12") == {"ok": True}
    assert api.copy_image("data:image/png;base64,iVBORw0KGgo=") == {"ok": True}
    assert copied == [("text", "Shots 12"), ("png", b"\x89PNG\r\n\x1a\n")]


def test_a_copy_that_cannot_be_made_says_so(api, monkeypatch):
    from gui import app
    def refuse(_):
        raise RuntimeError("no clipboard here")
    monkeypatch.setattr(app.platform_tasks, "copy_text", refuse)
    monkeypatch.setattr(app.platform_tasks, "copy_image", refuse)
    assert api.copy_text("x") == {"ok": False, "error": "Couldn't copy it to the clipboard."}
    assert api.copy_image("data:image/png;base64,iVBORw0KGgo=") == {"ok": False, "error": "Couldn't copy it to the clipboard."}
    for junk in ("", "not a picture", "data:image/png;base64,@@@", "data:image/jpeg;base64,AAAA", None):
        assert api.copy_image(junk) == {"ok": False, "error": "There was no picture to copy."}
    assert api.copy_text("") == {"ok": False, "error": "There was nothing to copy."}


def test_being_offline_is_not_reported_as_an_expired_login(auto, tmp_path):
    # Trace can't be reached (no Wi-Fi after waking, Trace itself down): that says
    # nothing about the login, so no notification and no "reconnect".
    _config(auto, tmp_path)
    _new_game(auto)
    auto._worker.logged_in = lambda: False
    auto._worker.list_games = lambda: pytest.fail("nothing to list")
    for detail in ("api unreachable: ConnectError('offline')", "api http 502 (non-JSON)",
                   "navigation failed: TimeoutError()", "no account / no team URL"):
        auto._worker.login_detail = lambda detail=detail: detail
        assert auto.auto_check() == {"ran": False, "games": 0}       # "didn't run": it looks again in ten minutes
    assert auto.notes == [] and not auto.tray_status().startswith("Trace login expired")
    assert [event for event, _ in auto.events if event == "login_changed"] == []


def test_the_window_is_told_when_the_login_expires_so_it_can_offer_reconnect(auto, tmp_path):
    # The window may have been open (hidden) for weeks, still saying "Logged in".
    _config(auto, tmp_path)
    auto.set_auto(True)
    auto._worker.logged_in = lambda: False
    auto.auto_check()
    assert ("login_changed", {}) in auto.events


def test_reconnecting_looks_for_the_missed_games_soon_not_hours_later(auto, tmp_path):
    _config(auto, tmp_path)
    auto.set_auto(True)
    auto._worker.logged_in = lambda: False
    auto.auto_check()
    soon = []
    auto._schedule_auto = lambda first_in_secs=None: soon.append(first_in_secs)
    auto._worker.logged_in = lambda: True
    auto.get_status()
    auto.get_status()                                            # only on the change, not on every look
    assert soon == [60]


def test_the_tray_menu_is_only_redrawn_when_what_it_says_changes(auto, tmp_path):
    _config(auto, tmp_path)
    redrawn = []
    auto._tray = SimpleNamespace(refresh=lambda: redrawn.append(auto.tray_status()), set_visible=lambda on: None)
    auto._tray_changed()
    auto._tray_changed()
    assert redrawn == []                                         # nothing to say yet, nothing changed
    auto._downloading_now = ("vs Rovers", 40)
    auto._tray_changed()
    auto._tray_changed()
    assert redrawn == ["Downloading vs Rovers · 40%"]


@pytest.fixture
def editor(api, monkeypatch):
    """The API with an editor-ready stub worker. Threads run at once, in line."""
    from gui import app
    api._media = SimpleNamespace(url_for=lambda path: "http://127.0.0.1:1/tok/" + str(path).rsplit("/", 1)[-1])
    api._start = lambda work: work()
    api.project = {"home": {"name": "T", "code": "TIG", "color": "#16a05a"},
                   "away": {"name": "Rovers", "code": "ROV", "color": "#1e5ac8"},
                   "marks": [{"id": "a", "kind": "start", "t": 10}, {"id": "b", "kind": "break", "t": 610},
                             {"id": "c", "kind": "resume", "t": 700}, {"id": "d", "kind": "end", "t": 1300}]}
    api.asked = []
    w = api._worker
    w.team_label = lambda: "T"
    w.edit_open = lambda game_id, date, opponent, home, away: api.asked.append(("open", game_id, home, away)) or {
        "project": api.project, "files": ["/v/g_half1.mp4", "/v/g_half2.mp4"], "durations": [1500.0, 1600.0], "height": 1080}
    w.edit_save = lambda game_id, date, opponent, project: api.asked.append(("save", game_id)) or project
    monkeypatch.setattr(app.platform_tasks, "notify", api.notes.append)
    return api


def test_opening_the_editor_gives_the_page_everything_it_draws_from(editor):
    opened = editor.edit_open("t-1")
    assert opened["ok"] is True and opened["title"] == "vs Rovers" and opened["project"] == editor.project
    assert opened["segments"] == [[10, 610], [700, 1300]] and opened["problems"] == []
    assert opened["sources"] == [
        {"url": "http://127.0.0.1:1/tok/g_half1.mp4", "name": "g_half1.mp4", "start": 0, "length": 1500.0},
        {"url": "http://127.0.0.1:1/tok/g_half2.mp4", "name": "g_half2.mp4", "start": 1500.0, "length": 1600.0}]
    assert opened["duration"] == 3100.0 and opened["layout"] == scorebug.layout(1.0, editor.project["home"], editor.project["away"]) and opened["score"] is None
    assert editor.asked == [("open", "t-1", "T", "Rovers")]


def test_opening_the_editor_without_the_video_says_what_is_needed(editor):
    def nothing(*args):
        raise RuntimeError("Download the full game first: the editor works on the saved video.")
    editor._worker.edit_open = nothing
    assert editor.edit_open("t-1") == {"ok": False, "error": "Download the full game first: the editor works on the saved video."}
    assert editor.edit_open("nope") == {"ok": False, "error": "game not found"}


def test_saving_an_edit_answers_with_what_is_wrong_with_it(editor):
    broken = {**editor.project, "marks": editor.project["marks"][:-1]}
    saved = editor.edit_save("t-1", broken)
    assert saved["ok"] is True and saved["problems"] == ["Mark where the game ends."] and saved["segments"] == []
    assert editor.edit_save("t-1", editor.project)["problems"] == []


def test_a_plate_is_drawn_for_the_page_to_preview(editor):
    plate = editor.bug_plate({"code": "tig", "color": "#16a05a"}, {"code": "ROV", "color": "nonsense"}, 2, 1)
    assert plate["ok"] is True and plate["url"].startswith("data:image/png;base64,iVBOR")
    assert editor.bug_plate(None, None, "x", None)["ok"] is True          # junk is tidied, never an error
    big = editor.bug_plate({"code": "TIG"}, {"code": "ROV"}, 0, 0, {"size": 2.0, "font": "poppins"})
    assert big["ok"] is True and len(big["url"]) > len(plate["url"])


def test_the_editor_is_told_the_typefaces_and_gets_a_fresh_layout_with_each_save(editor):
    opened = editor.edit_open("t-1")
    assert opened["fonts"][0] == {"key": "barlow", "label": "Barlow Semi Condensed", "file": "BarlowSemiCondensed-SemiBold.ttf"}
    assert len(opened["fonts"]) == 6 and opened["sizes"] == [0.5, 2.0]
    assert [d["key"] for d in opened["designs"]] == ["classic", "slim", "blocks"] and all(d["label"] for d in opened["designs"])
    assert opened["usual"] == scorebug.USUAL and opened["usual"] is not scorebug.USUAL       # the look "Reset" goes back to
    changed = {**editor.project, "home": {**editor.project["home"], "code": "TIGER SHARKS"}, "bug": {"size": 1.5, "font": "anton"}}
    saved = editor.edit_save("t-1", changed)
    assert saved["layout"] == scorebug.layout(1.0, changed["home"], changed["away"], changed["bug"])
    assert saved["layout"]["font"] == "anton" and saved["layout"]["width"] > opened["layout"]["width"] * 1.5


def _events(api, name):
    return [payload for event, payload in api.events if event == name]


def test_an_export_reports_progress_and_then_the_finished_file(editor):
    def export_edit(game_id, date, opponent, quality, on_progress=None, on_proc=None):
        editor.asked.append(("export", game_id, quality))
        on_progress(25, 300.0)
        on_progress(50, 600.0)
        return "/v/g/Edited/g (edited).mp4"
    editor._worker.export_edit = export_edit
    assert editor.export_start("t-1", "faster") == {"ok": True}
    assert ("export", "t-1", "faster") in editor.asked
    assert [(p["id"], p["percent"]) for p in _events(editor, "export_progress")] == [("t-1", 25), ("t-1", 50)]
    assert _events(editor, "export_done") == [{"id": "t-1", "ok": True, "stopped": False, "label": "Edited game",
                                              "url": "http://127.0.0.1:1/tok/g (edited).mp4"}]
    assert editor.notes == ["Exported vs Rovers with the score bug"]
    assert editor.export_start("t-1")["ok"] is True                       # and another can be started afterwards


def test_only_one_export_runs_at_a_time(editor):
    started = []
    editor._start = started.append                                        # the thread is "running": never finishes here
    editor._worker.export_edit = lambda *a, **k: "/x.mp4"
    assert editor.export_start("t-1") == {"ok": True}
    assert editor.export_start("t-2") == {"ok": False, "error": "Another export is running."}
    assert len(started) == 1


def test_stopping_an_export_ends_it_and_says_nothing_was_exported(editor):
    stopped = []
    def export_edit(game_id, date, opponent, quality, on_progress=None, on_proc=None):
        on_proc(SimpleNamespace(terminate=lambda: stopped.append("terminated")))
        editor.export_stop()
        raise RuntimeError("The export didn't finish.")
    editor._worker.export_edit = export_edit
    editor.export_start("t-1")
    assert stopped == ["terminated"]
    assert _events(editor, "export_done") == [{"id": "t-1", "ok": False, "stopped": True,
                                              "error": "Stopped. Nothing was exported."}]
    assert editor.notes == []


def test_an_export_that_fails_says_why(editor):
    def export_edit(*args, **kwargs):
        raise RuntimeError("Mark where the game ends.")
    editor._worker.export_edit = export_edit
    editor.export_start("t-1")
    assert _events(editor, "export_done") == [{"id": "t-1", "ok": False, "stopped": False, "error": "Mark where the game ends."}]
    assert editor.export_start("nope") == {"ok": False, "error": "game not found"}


def test_the_edited_game_can_be_played_in_the_app(editor):
    editor._worker.game_media = lambda game_id, date, opponent: {
        "full": [], "reel": None, "clips": [], "recaps": [], "mine": [],
        "edited": [{"label": "Edited game", "path": "/v/g/Edited/g (edited).mp4"}]}
    assert editor.game_media("t-1")["edited"] == [{"label": "Edited game", "url": "http://127.0.0.1:1/tok/g (edited).mp4"}]
    assert editor.game_media("nope")["edited"] == []


def test_stop_pressed_before_the_export_has_properly_started_still_stops_it(editor):
    # Reading the video's facts and drawing the plates comes first; ffmpeg starts a moment later.
    ended = []
    def export_edit(game_id, date, opponent, quality, on_progress=None, on_proc=None):
        editor.export_stop()                                        # pressed during the preparation
        on_proc(SimpleNamespace(terminate=lambda: ended.append("terminated")))
        raise RuntimeError("The export didn't finish.")
    editor._worker.export_edit = export_edit
    editor.export_start("t-1")
    assert ended == ["terminated"]
    assert _events(editor, "export_done")[-1] == {"id": "t-1", "ok": False, "stopped": True,
                                                 "error": "Stopped. Nothing was exported."}


def test_quitting_the_app_ends_an_export_in_progress(editor):
    ended = []
    editor._export_proc = SimpleNamespace(terminate=lambda: ended.append("terminated"))
    editor._quit_soon = lambda: None
    editor.quit_app()
    assert ended == ["terminated"]


def test_choosing_a_crest_asks_for_a_picture_and_hands_it_to_the_worker(editor):
    given = []
    editor._worker.edit_crest = lambda game_id, date, opponent, which, source: given.append((game_id, which, source))
    asked = _picker(editor, ("/Users/me/Pictures/badge.png",))
    assert editor.pick_crest("t-1", "home") == {"ok": True}
    assert given == [("t-1", "home", "/Users/me/Pictures/badge.png")] and asked[0]["allow_multiple"] is False
    assert "png" in asked[0]["file_types"][0].lower()
    _picker(editor, None)
    assert editor.pick_crest("t-1", "league") == {"ok": False} and len(given) == 1                 # cancelled
    assert editor.pick_crest("t-1", "mascot") == {"ok": False, "error": "unknown crest"}
    assert editor.clear_crest("t-1", "home") == {"ok": True} and given[-1] == ("t-1", "home", None)


def test_a_picture_that_cannot_be_used_is_reported(editor):
    def refuse(*args):
        raise RuntimeError("That file isn't a picture TraceDown can use. Try a PNG or JPEG.")
    editor._worker.edit_crest = refuse
    _picker(editor, ("/Users/me/notes.txt",))
    assert editor.pick_crest("t-1", "away") == {"ok": False, "error": "That file isn't a picture TraceDown can use. Try a PNG or JPEG."}


def test_plates_and_layouts_include_the_crests_the_edit_shows(editor):
    from PIL import Image
    asked = []
    def pictures(game_id, date, opponent, shown):
        asked.append((game_id, shown))
        return {"home": Image.new("RGBA", (40, 40), (255, 120, 0, 255))} if shown.get("home") else {}
    editor._worker.edit_crest_images = pictures
    teams = ({"code": "TIG", "color": "#16a05a"}, {"code": "ROV", "color": "#1e5ac8"})
    bare = editor.bug_plate(*teams, 0, 0, None, "t-1", {"home": False})
    crested = editor.bug_plate(*teams, 0, 0, None, "t-1", {"home": True, "away": True})
    assert crested["ok"] is True and crested["url"] != bare["url"] and asked[-1] == ("t-1", {"home": True, "away": True, "league": False})
    assert editor.bug_plate(*teams, 0, 0)["url"] == bare["url"]                                       # with no game, no crests
    with_crest = {**editor.project, "crests": {"home": True, "away": False, "league": True}}
    saved = editor.edit_save("t-1", with_crest)
    assert saved["layout"] == scorebug.layout(1.0, with_crest["home"], with_crest["away"], None, with_crest["crests"])
