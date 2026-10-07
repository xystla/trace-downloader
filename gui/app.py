# gui/app.py
import functools
import inspect
import json
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from dataclasses import asdict
from datetime import date
from pathlib import Path

import webview
import yaml

from gui.instance import Instance
from gui.media import MediaServer
from gui.tray import Tray
from gui.worker import Worker
from gui.viewmodel import games_view, connection_state, score_view
from trace_grabber import analytics, autodl, highlights, paths, platform_tasks, space, updates
from trace_grabber.config import load_config
from trace_grabber.naming import custom_stem

WEB = paths.resource_dir() / "gui" / "web"
DATA = paths.data_dir()
LAST_RUN = DATA / "last_run.json"
INTERVALS = (1, 3, 6, 12, 24)      # hours between automatic checks offered in Settings


def _user_job(fn):
    """Mark a download the person started, so the automatic check waits its turn."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        self._user_jobs += 1
        try:
            return fn(self, *args, **kwargs)
        finally:
            self._user_jobs -= 1
    return wrapper


class Api:
    def __init__(self):
        self._worker = None
        self._window = None
        self._game_cache = {}
        self._tray = None
        self._quitting = False
        self._user_jobs = 0        # downloads the person started that are still running
        self._auto_running = False
        self._auto_timer = None

    def _w(self):
        if self._worker is None:
            self._worker = Worker()
        return self._worker

    def set_window(self, window):
        self._window = window

    def get_status(self):
        last = json.loads(LAST_RUN.read_text(encoding="utf-8")) if LAST_RUN.exists() else None
        cfg = load_config(DATA / "config.yaml")
        has_account = bool(self._w().list_accounts()["accounts"])
        logged_in = self._w().logged_in()
        return {
            "logged_in": logged_in,
            "has_account": has_account,
            "connection": connection_state(has_account, logged_in),
            "login_detail": self._w().login_detail(),
            "last_run": last,
            **self.auto_settings(),
            "auto_options": self.auto_options(),
            "settings": {"output_dir": str(cfg.output_dir), "quality": cfg.quality, "combine": cfg.combine_halves,
                         "file_name": cfg.file_name},
            "version": paths.APP_VERSION,
        }

    def get_games(self):
        games, done, errors = self._w().games_result()
        self._game_cache = {g.id: g for g in games}
        clips = self._w().clip_counts(games)
        partial = self._w().partials(games, done)      # full-game downloads that were cut off
        missing = self._w().missing(games, done)        # saved, but the video is no longer there
        views = [{**view, "clips": clips.get(view["id"], 0), "partial": partial.get(view["id"]),
                  "state": "missing" if view["id"] in missing else view["state"]}
                 for view in games_view(games, done)]
        return {"games": views, "errors": errors}

    def _run_download(self, game_id):
        g = self._game_cache.get(game_id)
        if g is None:
            # Cache miss (e.g. game appeared since the last list) — refresh once.
            games, _ = self._w().list_games()
            self._game_cache = {x.id: x for x in games}
            g = self._game_cache.get(game_id)
        if not g:
            return {"ok": False, "error": "game not found"}

        def on_progress(info):
            self._emit("progress", {"id": game_id, **info})
        try:
            n = self._w().download_game(g.id, g.team_id, g.date, g.opponent, on_progress)
            if self._w().cancelled():
                self._emit("cancelled", {"id": game_id})
            else:
                self._emit("saved" if n > 0 else "unavailable", {"id": game_id})
            return {"ok": True, "files": n}
        except Exception as e:
            self._emit("error", {"id": game_id, "message": str(e)})
            return {"ok": False, "error": str(e), "no_space": isinstance(e, space.NotEnoughSpace)}

    def _saved(self, result):
        return bool(result.get("ok") and result.get("files")) and not self._w().cancelled()

    @_user_job
    def download_game(self, game_id):
        self._w().clear_cancel()
        result = self._run_download(game_id)
        if self._saved(result):
            g = self._game_cache[game_id]
            platform_tasks.notify(f"Saved vs {g.opponent or g.title}")
        return result

    def _game_file(self, game_id):
        g = self._game_cache.get(game_id)
        files = self._w().game_files(g.id, g.date, g.opponent) if g else []
        return files[0] if files else None

    def _url(self, path):
        """A local address the page can play a saved video from."""
        if not hasattr(self, "_media"):
            self._media = MediaServer()
        return self._media.url_for(path)

    def _with_game_file(self, game_id, action):
        path = self._game_file(game_id)
        if not path:
            return {"ok": False,
                    "error": "Couldn't find the video file. It may have been moved or renamed."}
        action(path)
        return {"ok": True}

    def game_media(self, game_id):
        """Everything saved for a game as addresses the page can play: the full
        game (one part, or one per half when the halves are kept separate), the
        highlight reel, each clip, each player recap and each clip of your own."""
        empty = {"full": [], "reel": None, "clips": [], "recaps": [], "mine": []}
        g = self._game_cache.get(game_id)
        if not g:
            return empty
        try:
            media = self._w().game_media(g.id, g.date, g.opponent)
        except Exception:
            return empty
        url = self._url
        files = media["full"]
        halves = [f for f in files if "_half" in Path(f).name]
        if len(halves) == len(files) and len(files) > 1:
            names = ["1st half", "2nd half"]
            full = [{"label": names[i] if i < 2 else f"Part {i + 1}", "url": url(f), "name": Path(f).name}
                    for i, f in enumerate(files)]
        else:
            full = [{"label": "Full game", "url": url(f), "name": Path(f).name} for f in files[:1]]
        return {"full": full,
                "reel": url(media["reel"]) if media["reel"] else None,
                "clips": [{"label": c["label"], "url": url(c["path"]), "half": c.get("half"),
                           "start": c.get("start")} for c in media["clips"]],
                "recaps": [{"label": r["label"], "url": url(r["path"])} for r in media["recaps"]],
                "mine": [{"label": c["label"], "url": url(c["path"])} for c in media.get("mine", [])]}

    def play_game(self, game_id):
        return self._with_game_file(game_id, platform_tasks.open_file)

    def reveal_game(self, game_id):
        return self._with_game_file(game_id, platform_tasks.reveal_file)

    def _for_game(self, game_id, call):
        """Run a worker call for a listed game, turning any failure into a message."""
        g = self._game_cache.get(game_id)
        if not g:
            return None, "game not found"
        try:
            return call(g), None
        except Exception as e:
            return None, str(e)

    def list_highlights(self, game_id):
        listing, error = self._for_game(
            game_id, lambda g: self._w().list_highlights(g.id, g.date, g.opponent))
        return {"ok": False, "error": error} if error else {"ok": True, **listing}

    @_user_job
    def download_recap(self, game_id, user_id):
        def on_progress(pct):
            self._emit("recap_progress", {"id": game_id, "user_id": user_id, "percent": pct})

        _, error = self._for_game(
            game_id,
            lambda g: self._w().download_recap(g.id, g.date, g.opponent, user_id, on_progress))
        return {"ok": False, "error": error} if error else {"ok": True}

    def reveal_highlights(self, game_id, kind="clips"):
        """Show a game's Highlights folder ("clips"), Player Highlights folder ("recaps") or My Clips folder ("mine")."""
        folder, error = self._for_game(
            game_id, lambda g: self._w().highlights_folder(g.id, g.date, g.opponent, kind))
        if not folder:
            what = {"recaps": "player recaps", "mine": "clips of your own"}.get(kind, "highlights")
            return {"ok": False, "error": error or f"No {what} have been saved for this game yet."}
        platform_tasks.reveal_file(folder)
        return {"ok": True}

    def open_game_folder(self, game_id):
        """Open the folder for a game that has no video yet (see Worker._folder_to_open)."""
        folder, error = self._for_game(
            game_id, lambda g: self._w().folder_to_open(g.id, g.date, g.opponent))
        if not folder:
            return {"ok": False, "error": error or "Couldn't open the folder."}
        platform_tasks.open_file(folder)
        return {"ok": True}

    @_user_job
    def download_highlights(self, game_id):
        g = self._game_cache.get(game_id)
        if not g:
            return {"ok": False, "error": "game not found"}
        def on_progress(done, total):
            self._emit("highlights_progress", {"id": game_id, "done": done, "total": total})

        try:
            self._w().clear_cancel()
            folder, count, already = self._w().export_highlights(g.id, g.date, g.opponent, on_progress)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if self._w().cancelled():
            return {"ok": False, "error": "Stopped. No highlights were saved."}
        if not count:
            return {"ok": False, "error": "No highlights were found in this game."}
        return {"ok": True, "count": count, "already": already}

    def cancel(self):
        self._w().cancel()
        return {"ok": True}

    def discard_download(self, game_id):
        """Delete what a cut-off full-game download left on disk."""
        done, error = self._for_game(
            game_id, lambda g: self._w().discard_partial(g.id, g.date, g.opponent))
        if not error and not done:
            error = "Nothing was deleted: this game is downloading or already saved."
        return {"ok": False, "error": error} if error else {"ok": True}

    def disk_free(self):
        """Free space where games are saved, for the Downloads page."""
        try:
            free = self._w().disk_free()
        except Exception:
            return {"ok": False}
        return {"ok": True, "free": free, "text": space.size_text(free), "low": free < space.LOW}

    # ---- watching: bookmarks, clips of your own, full screen ----
    def _marks(self, game_id, call):
        """Run a bookmark call for a listed game; every one answers with the game's bookmarks."""
        marks, error = self._for_game(game_id, call)
        return {"ok": False, "error": error} if error else {"ok": True, "bookmarks": marks}

    def bookmarks(self, game_id):
        return self._marks(game_id, lambda g: self._w().bookmarks(g.id, g.date, g.opponent))

    def add_bookmark(self, game_id, t, half, note=""):
        made, error = self._for_game(
            game_id, lambda g: self._w().add_bookmark(g.id, g.date, g.opponent, t, half, note))
        return {"ok": False, "error": error} if error else {"ok": True, "id": made[0], "bookmarks": made[1]}

    def edit_bookmark(self, game_id, bookmark_id, note):
        return self._marks(game_id, lambda g: self._w().edit_bookmark(g.id, g.date, g.opponent, bookmark_id, note))

    def remove_bookmark(self, game_id, bookmark_id):
        return self._marks(game_id, lambda g: self._w().remove_bookmark(g.id, g.date, g.opponent, bookmark_id))

    def export_clip(self, game_id, name, start, end):
        """Cut a stretch of a saved full-game file (named as game_media named it)
        into the game's My Clips folder."""
        path, error = self._for_game(
            game_id, lambda g: self._w().export_clip(g.id, g.date, g.opponent, name, start, end))
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "label": highlights.my_clip_label(Path(path).name), "url": self._url(path)}

    def toggle_fullscreen(self):
        """Put the app's window into full screen, or back. The page makes the video
        fill the window either way, so failing here only loses the last step."""
        try:
            self._window.toggle_fullscreen()
            return {"ok": True}
        except Exception:
            return {"ok": False}

    # ---- the library: missing videos, storage, removing a game, file names ----
    def find_video(self, game_id):
        """Ask where a game's video is now and remember it. The file stays there."""
        g = self._game_cache.get(game_id)
        if not g or not self._window:
            return {"ok": False}
        # OPEN_DIALOG was renamed to FileDialog.OPEN in newer pywebview (as with FOLDER and SAVE).
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if kind is None:
            kind = webview.OPEN_DIALOG
        try:
            chosen = self._window.create_file_dialog(
                kind, allow_multiple=True, file_types=("Video files (*.mp4;*.mov;*.m4v;*.mkv)",))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not chosen:
            return {"ok": False}  # cancelled
        files = [chosen] if isinstance(chosen, str) else list(chosen)
        _, error = self._for_game(game_id, lambda game: self._w().set_found(game.id, files))
        return {"ok": False, "error": error} if error else {"ok": True}

    def storage(self):
        """What each game takes on disk, for the Storage page."""
        try:
            report = self._w().storage(list(self._game_cache.values()))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, **report, "bin": platform_tasks.bin_name(), "can_remove": platform_tasks.can_trash()}

    def remove_game(self, game_id, everything=False):
        """Move a game's full video, or everything saved for it, to the Trash."""
        moved, error = self._for_game(
            game_id, lambda g: self._w().remove_game(g.id, g.date, g.opponent, bool(everything),
                                                     games=list(self._game_cache.values())))
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "freed": moved, "bin": platform_tasks.bin_name()}

    def preview_file_name(self, pattern):
        """The file name a pattern gives a sample game, for the Settings preview."""
        stem = custom_stem(pattern, "2026-06-04", "Rovers", self._w().team_label())
        return {"name": (stem or "2026-06-04_vs-rovers") + ".mp4", "custom": bool(stem)}

    def get_thumb(self, team_id, game_id):
        g = self._game_cache.get(game_id)
        return self._w().get_thumb(team_id, game_id, g.date if g else None,
                                   g.opponent if g else None)

    def list_accounts(self):
        return self._w().list_accounts()

    def switch_account(self, account_id):
        return self._w().switch_account(account_id)

    def remove_account(self, account_id):
        return self._w().remove_account(account_id)

    def add_account_start(self):
        self._w().add_account_start()
        return {"ok": True}

    def add_account_finish(self):
        return self._w().add_account_finish()

    def add_account_poll(self):
        return self._w().add_account_poll()

    def add_account_cancel(self):
        self._w().add_account_cancel()
        return {"ok": True}

    def confirm_team_url(self, url):
        return self._w().confirm_team_url(url)

    # ---- automatic downloads, running inside the app ----
    def auto_settings(self):
        state = autodl.load(DATA)
        return {"auto": state.enabled, "login": state.login, "welcome": not state.welcomed}

    def auto_options(self):
        """What automatic downloads fetch for a new game, and how often they look."""
        state = autodl.load(DATA)
        return {"full": state.full, "highlights": state.highlights, "recaps": state.recaps,
                "interval": load_config(DATA / "config.yaml").check_interval_hours}

    def set_auto_choices(self, choices):
        """Choose what automatic downloads fetch. At least one thing must stay on:
        with nothing chosen they would run and do nothing."""
        state = autodl.load(DATA)
        names = ("full", "highlights", "recaps")
        wanted = {name: bool(choices.get(name, getattr(state, name))) for name in names}
        if not any(wanted.values()):
            return {"ok": False, "error": "Automatic downloads need at least one thing to fetch.",
                    **{name: getattr(state, name) for name in names}}
        for name in names:
            setattr(state, name, wanted[name])
        autodl.save(DATA, state)
        return {"ok": True, **wanted}

    def finish_welcome(self, auto, login):
        """Record the first-open choices (appearance is kept by the page itself)."""
        state = autodl.load(DATA)
        state.welcomed = True
        autodl.save(DATA, state)
        self.set_auto(bool(auto))             # which also opens the app at login
        if autodl.load(DATA).login != bool(auto and login):
            self.set_login(bool(auto and login))
        return {"ok": True}

    def set_auto(self, enabled):
        """Turn automatic downloads on or off. They only ever cover games added
        after this moment: the games listed now are recorded as already seen."""
        platform_tasks.schedule_disable()     # the old background task is replaced by this
        state = autodl.load(DATA)
        was_on = state.enabled
        state.enabled = bool(enabled)
        if state.enabled:
            try:
                games, done = self._w().list_games()
                state.seen.pop(self._w().list_accounts()["active"], None)     # draw the line afresh
                autodl.pending(state, self._w().list_accounts()["active"], games, done)
            except Exception:
                pass                          # the line is drawn on the first check instead
        autodl.save(DATA, state)
        if self._tray:
            self._tray.set_visible(state.enabled)
        if state.enabled:
            self._schedule_auto()
        # Automatic downloads need the app running, so switching them on also
        # opens TraceDown at login (it can be switched back off on its own), and
        # switching them off stops that.
        if state.enabled != was_on or (state.login and not state.enabled):
            self.set_login(state.enabled)
        return state.enabled

    def set_login(self, enabled):
        state = autodl.load(DATA)
        state.login = bool(enabled)
        autodl.save(DATA, state)
        (platform_tasks.login_enable if state.login else platform_tasks.login_disable)()
        return state.login

    def _schedule_auto(self, first_in_secs=None):
        """(Re)start the timer for the next automatic check."""
        if self._auto_timer:
            self._auto_timer.cancel()
        hours = load_config(DATA / "config.yaml").check_interval_hours
        self._auto_timer = threading.Timer(first_in_secs or hours * 3600, self._auto_tick)
        self._auto_timer.daemon = True
        self._auto_timer.start()

    def _auto_tick(self):
        try:
            ran = self.auto_check()["ran"]
        except Exception:
            ran = True
        if autodl.load(DATA).enabled:
            # If you were busy downloading, look again in ten minutes rather than in three hours.
            self._schedule_auto(first_in_secs=None if ran else 600)

    def _auto_change(self, change):
        """Apply one change to the automatic-download settings as they are on disk
        right now. A check can run for hours while the person changes settings; a
        copy loaded when it started must never be saved back over their choices."""
        state = autodl.load(DATA)
        change(state)
        autodl.save(DATA, state)

    def auto_check(self):
        """Fetch every game added since automatic downloads were switched on:
        whichever of the full game, its highlights and reel, and each player
        recap were chosen."""
        state = autodl.load(DATA)
        if not state.enabled or self._auto_running or self._user_jobs > 0:
            return {"ran": False, "games": 0}
        self._auto_running = True
        saved = 0
        try:
            w = self._w()
            games, done = w.list_games()
            self._game_cache = {g.id: g for g in games}
            account = w.list_accounts()["active"]
            pending = autodl.pending(state, account, games, done)
            autodl.save(DATA, state)
            for index, g in enumerate(pending, 1):
                name = f"vs {g.opponent or g.title}"
                self._emit("auto", {"running": True,
                                    "text": f"Automatic download {index} of {len(pending)}: {name}"})
                w.clear_cancel()
                got = False
                if state.full:
                    result = self._run_download(g.id)
                    if result.get("no_space"):
                        if not autodl.load(DATA).low_disk:        # say it once, not on every check
                            platform_tasks.notify("Automatic downloads paused: not enough disk space.")
                            self._auto_change(lambda s: setattr(s, "low_disk", True))
                        break
                    if not self._saved(result):
                        if w.cancelled():
                            break
                        continue                  # no video yet, or it failed: try again next time
                    if autodl.load(DATA).low_disk:
                        self._auto_change(lambda s: setattr(s, "low_disk", False))
                    got = True
                if state.highlights:
                    got = bool(self.download_highlights(g.id).get("ok")) or got
                    if w.cancelled():
                        break
                if state.recaps:
                    got = bool(self.download_all_recaps(g.id, quiet=True).get("recaps")) or got
                    if w.cancelled():
                        break
                if not state.full:
                    # Without its video a game is never marked done, so note here
                    # that it has been dealt with (or is still to be tried again).
                    self._auto_change(lambda s: autodl.settle(s, account, g.id, got, date.today()))
                saved += got
            if saved:
                platform_tasks.notify(
                    f"Automatic download: {saved} new game{'' if saved == 1 else 's'} saved")
        finally:
            self._auto_running = False
            self._emit("auto", {"running": False, "text": ""})
        return {"ran": True, "games": saved}

    def keep_running(self):
        """Should closing the window leave the app running in the background?"""
        return not self._quitting and autodl.load(DATA).enabled

    def quit_app(self):
        self._quitting = True
        self._quit_soon()
        return {"ok": True}

    def show_window(self):
        if self._window:
            self._window.show()
            self._window.restore()

    def open_folder(self):
        cfg = load_config(DATA / "config.yaml")
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        opener = "open" if sys.platform == "darwin" else ("explorer" if __import__("os").name == "nt" else "xdg-open")
        subprocess.run([opener, str(cfg.output_dir)], check=False)

    def reconnect_start(self):
        self._w().reconnect_start()
        return {"ok": True}

    def reconnect_finish(self):
        return {"logged_in": self._w().reconnect_finish()}

    def choose_output_dir(self):
        """Open a native folder picker and save the chosen download location."""
        if not self._window:
            return {"ok": False}
        # FOLDER_DIALOG was renamed to FileDialog.FOLDER in newer pywebview.
        folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if folder is None:
            folder = webview.FOLDER_DIALOG
        try:
            res = self._window.create_file_dialog(folder)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not res:
            return {"ok": False}  # cancelled
        path = res[0] if isinstance(res, (list, tuple)) else res
        cfgpath = DATA / "config.yaml"
        data = yaml.safe_load(cfgpath.read_text(encoding="utf-8"))
        data["output_dir"] = path
        cfgpath.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self._w().reload_config()
        return {"ok": True, "output_dir": path}

    def get_analytics(self, refresh=False):
        # Payload carries three segments per game and for the season — whole
        # match, first half, second half — so the UI can toggle between them.
        def stat(gs):
            return {**asdict(gs),
                    "territory_svg": analytics.territory_svg(gs.territory_us, ink="currentColor")}

        def season_seg(seasonstats):
            return {**asdict(seasonstats),
                    "territory_svg": analytics.territory_svg(seasonstats.territory, ink="currentColor")}

        def on_progress(done, total):
            self._emit("analytics_progress", {"done": done, "total": total})

        downloaded = without_stats = 0
        timelines = {}
        try:
            result = self._w().compute_analytics(on_progress, bool(refresh))
            splits = result.splits
            downloaded, without_stats = result.downloaded, result.without_stats
            timelines = result.timelines
        except Exception:
            splits = []
        # Scores come from the game list (stats are keyed by the game's number).
        scores = {int(g.id.rsplit("-", 1)[-1]): score_view(g) for g in self._game_cache.values()
                  if g.id.rsplit("-", 1)[-1].isdigit()}
        games = [{"game_id": sp.whole.game_id, "date": sp.whole.date,
                  "opponent": sp.whole.opponent, "score": scores.get(sp.whole.game_id),
                  "timeline": timelines.get(sp.whole.game_id),
                  "whole": stat(sp.whole), "first": stat(sp.first),
                  "second": stat(sp.second)}
                 for sp in splits]
        return {
            "games": games,
            "downloaded": downloaded,
            "without_stats": without_stats,
            "season": {
                "whole": season_seg(analytics.aggregate([sp.whole for sp in splits])),
                "first": season_seg(analytics.aggregate([sp.first for sp in splits])),
                "second": season_seg(analytics.aggregate([sp.second for sp in splits])),
            },
        }

    @_user_job
    def download_all_recaps(self, game_id, quiet=False):
        """Every player recap Trace has for one game that isn't saved yet. Reports
        progress as "recaps" events — a step text before each player, the player's
        id once saved — and stops between files once cancelled."""
        g = self._game_cache.get(game_id)
        if not g:
            return {"ok": False, "error": "game not found"}
        w = self._w()
        w.clear_cancel()
        result = {"ok": True, "recaps": 0, "failed": 0, "cancelled": False}
        try:
            self._emit("recaps", {"id": game_id, "text": "Checking which recaps are missing…"})
            wanted = [p for p in w.list_highlights(g.id, g.date, g.opponent)["players"]
                      if not p["saved"] and p["seconds"]]
            for index, player in enumerate(wanted, 1):
                if w.cancelled():
                    break
                self._emit("recaps", {"id": game_id, "text":
                                      f"Player recap {index} of {len(wanted)} (#{player['number']})…"})
                def on_progress(pct, user_id=player["user_id"], index=index):
                    self._emit("recap_progress", {"id": game_id, "user_id": user_id, "percent": pct,
                                                  "index": index, "total": len(wanted)})

                try:
                    w.download_recap(g.id, g.date, g.opponent, player["user_id"], on_progress)
                    result["recaps"] += 1
                    self._emit("recaps", {"id": game_id, "saved_user": player["user_id"]})
                except Exception:
                    result["failed"] += not w.cancelled()   # a Stop mid-file isn't a failure
        except Exception as e:
            return {**result, "ok": False, "error": str(e)}
        result["cancelled"] = w.cancelled()
        if not result["cancelled"] and not quiet:
            platform_tasks.notify(f"Player recaps saved for vs {g.opponent or g.title}")
        return result

    # ---- updates ----
    def check_update(self):
        """Is a newer TraceDown on GitHub? Never installs anything by itself."""
        try:
            release = updates.check(paths.APP_VERSION)
        except Exception:
            return {"ok": False, "error": "Couldn't check for updates. Check your connection and try again."}
        self._update = release
        if not release:
            return {"ok": True, "available": False, "current": paths.APP_VERSION}
        return {"ok": True, "available": True, "current": paths.APP_VERSION,
                "version": release.version, "notes": release.notes,
                # Only an installed copy can replace itself; from source there is nothing to swap.
                "can_install": paths.is_frozen() and bool(release.url)}

    def install_update(self):
        """Download the update found by check_update and hand over to its
        installer, then quit so it can replace this copy. Falls back to showing
        the download when it can't be installed automatically."""
        release = getattr(self, "_update", None)
        if not release or not release.url or not paths.is_frozen():
            webbrowser.open(updates.RELEASES_PAGE)
            return {"ok": True, "manual": True}
        try:
            with platform_tasks.keep_awake():
                path = updates.download(
                    release, Path(tempfile.gettempdir()) / "TraceDown-update",
                    on_progress=lambda pct: self._emit("update_progress", {"percent": pct}))
            if updates.start_install(path):
                self._quit_soon()
                return {"ok": True, "restarting": True}
            platform_tasks.reveal_file(path)
            return {"ok": True, "manual": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _quit_soon(self):
        """Close the app shortly, after this call has been answered — and make
        sure the process itself ends: the installer waits for it to be gone
        before replacing the app, so a process lingering behind a closed window
        would block the update."""
        self._quitting = True

        def quit_now():
            try:
                if self._window:
                    self._window.destroy()
            finally:
                threading.Timer(1.5, lambda: os._exit(0)).start()
        threading.Timer(1.0, quit_now).start()

    def whats_new(self):
        """This version's changes, if they haven't been shown since updating."""
        try:
            changelog = (paths.resource_dir() / "CHANGELOG.md").read_text(encoding="utf-8")
            return updates.pending_whats_new(DATA, paths.APP_VERSION, changelog)
        except Exception:
            return None

    def whats_new_seen(self):
        updates.mark_seen(DATA, paths.APP_VERSION)
        return {"ok": True}

    def version_notes(self):
        """This version's changes, for the "What's new" button in Settings."""
        try:
            changelog = (paths.resource_dir() / "CHANGELOG.md").read_text(encoding="utf-8")
        except OSError:
            changelog = ""
        return {"version": paths.APP_VERSION, "notes": updates.notes_for(paths.APP_VERSION, changelog)}

    def save_stats(self):
        """Quietly save the newest games' stats (only once Analytics has been viewed)."""
        try:
            return {"ok": True, "saved": bool(self._w().save_stats())}
        except Exception:
            return {"ok": False, "saved": False}

    def get_heatmap(self, game_id, fetch=False):
        """Where our players spent the game. Without `fetch` only a saved map is
        returned; with it, Trace's tracking files are downloaded and kept."""
        g = self._game_cache.get(game_id)
        if not g:
            return {"ok": False, "error": "game not found"}
        try:
            heat = self._w().heatmap(g.id, g.date, g.opponent, bool(fetch))
        except Exception as e:
            return {"ok": False, "error": f"Couldn't load the heat map: {e}"}
        if heat:
            return {"ok": True, "heat": heat}
        if not fetch:
            return {"ok": False, "missing": True}
        return {"ok": False, "error": "Trace has no player tracking for this game."}

    def export_analytics(self, fmt):
        if not self._window:
            return {"ok": False}
        try:
            splits = self._w().compute_analytics().splits
            games = [sp.whole for sp in splits]   # exports are whole-game
            season = analytics.aggregate(games)
            ext = "csv" if fmt == "csv" else "html"
            # SAVE_DIALOG was renamed to FileDialog.SAVE in newer pywebview
            # (mirrors the FOLDER shim in choose_output_dir).
            save = getattr(getattr(webview, "FileDialog", None), "SAVE", None)
            if save is None:
                save = webview.SAVE_DIALOG
            try:
                res = self._window.create_file_dialog(
                    save, save_filename=f"team-analytics.{ext}")
            except Exception as e:
                return {"ok": False, "error": str(e)}
            if not res:
                return {"ok": False}  # cancelled
            path = Path(res[0] if isinstance(res, (list, tuple)) else res)
            scores = {int(g.id.rsplit("-", 1)[-1]): f"{g.score_us}-{g.score_them}"
                      for g in self._game_cache.values()
                      if g.score_us is not None and g.score_them is not None
                      and g.id.rsplit("-", 1)[-1].isdigit()}
            (analytics.export_csv if fmt == "csv" else analytics.export_html)(
                games, season, path, scores=scores)
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_settings(self, settings):
        path = DATA / "config.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "quality" in settings:
            data["quality"] = settings["quality"]
        if "combine" in settings:
            data["combine_halves"] = bool(settings["combine"])
        if "file_name" in settings:
            data["file_name"] = str(settings["file_name"] or "").strip()[:200]
        retime = settings.get("interval") in INTERVALS and not isinstance(settings.get("interval"), bool)
        if retime:
            data["check_interval_hours"] = settings["interval"]
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self._w().reload_config()
        if retime and autodl.load(DATA).enabled:
            self._schedule_auto()             # the next check comes one new interval from now
        return {"ok": True}

    def _emit(self, event, payload):
        if self._window:
            self._window.evaluate_js(f"window.onPy({json.dumps(event)}, {json.dumps(payload)})")


def main():
    from trace_grabber import firstrun, tools
    from gui.runtime import prepare_renderer, show_startup_error
    try:
        renderer = prepare_renderer()
    except Exception as error:
        if sys.platform != "win32":
            raise
        show_startup_error(error)
        return 1
    firstrun.init()
    tools.setup_browser_env()
    # One copy at a time: if TraceDown is already running (perhaps hidden in the
    # menu bar or tray), bring its window back instead of starting another.
    instance = Instance(DATA)
    if instance.ask_running_copy_to_show():
        return 0
    api = Api()
    state = autodl.load(DATA)
    try:
        # Automatic downloads used to be a hidden task run by the operating system.
        # They now run in the app, so carry the old choice over and retire the task.
        if platform_tasks.schedule_enabled():
            platform_tasks.schedule_disable()
            state.enabled = True
            autodl.save(DATA, state)
    except Exception:
        pass
    need_setup = not tools.chromium_installed()
    first = WEB / ("setup.html" if need_setup else "index.html")
    # Started at login ("--background"): stay out of the way until asked for.
    hidden = state.enabled and "--background" in sys.argv and not need_setup
    window = webview.create_window("TraceDown", str(first), js_api=api,
                                   width=1200, height=780, min_size=(1120, 640),
                                   background_color="#0b0f14", hidden=hidden)
    api.set_window(window)

    def on_closing():
        # With automatic downloads on, closing the window only puts it away.
        if not api.keep_running():
            return True
        # Quitting the whole app (Cmd+Q, logging out, shutting down) is a real quit:
        # refusing it would hold up the computer.
        if any(f.function == "applicationShouldTerminate_" for f in inspect.stack()):
            api._quitting = True
            return True
        if api._tray:
            window.hide()
        else:
            window.minimize()
        return False
    window.events.closing += on_closing

    def check_now():
        threading.Thread(target=api.auto_check, daemon=True).start()
    api._tray = Tray.start(api.show_window, check_now, api.quit_app, visible=state.enabled)
    instance.listen(api.show_window)
    if state.enabled:
        api._schedule_auto(first_in_secs=90)
    setup = None
    if need_setup:
        # Only when we showed the setup screen: install Chromium, then load the app.
        def _setup():
            try:
                tools.install_chromium()
            except Exception as error:
                window.evaluate_js("document.getElementById('msg').textContent = " +
                                   json.dumps("Video engine setup failed. Reopen TraceDown to retry. " + str(error)))
                return
            window.load_url((WEB / "index.html").resolve().as_uri())
        setup = _setup
    webview.start(setup, gui=renderer)
    # The window loop has ended, so the app is quitting: don't let the tray icon
    # or a background check keep the process alive.
    instance.stop()
    if api._tray:
        api._tray.stop()
    os._exit(0)


if __name__ == "__main__":
    main()
