# gui/app.py
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import webview
import yaml

from gui.worker import Worker
from gui.viewmodel import games_view, connection_state
from trace_grabber import analytics, paths, platform_tasks
from trace_grabber.config import load_config

WEB = paths.resource_dir() / "gui" / "web"
DATA = paths.data_dir()
LAST_RUN = DATA / "last_run.json"


class Api:
    def __init__(self):
        self._worker = None
        self._window = None
        self._game_cache = {}

    def _w(self):
        if self._worker is None:
            self._worker = Worker()
        return self._worker

    def set_window(self, window):
        self._window = window

    def get_status(self):
        last = json.loads(LAST_RUN.read_text()) if LAST_RUN.exists() else None
        cfg = load_config(DATA / "config.yaml")
        has_account = bool(self._w().list_accounts()["accounts"])
        logged_in = self._w().logged_in()
        return {
            "logged_in": logged_in,
            "has_account": has_account,
            "connection": connection_state(has_account, logged_in),
            "login_detail": self._w().login_detail(),
            "last_run": last,
            "auto": platform_tasks.schedule_enabled(),
            "settings": {"output_dir": str(cfg.output_dir), "quality": cfg.quality, "combine": cfg.combine_halves},
            "version": paths.APP_VERSION,
        }

    def list_games(self):
        games, done = self._w().list_games()
        # Cache the Game objects so a later download doesn't have to re-scrape
        # the whole games page just to look up team_id/date/opponent.
        self._game_cache = {g.id: g for g in games}
        return games_view(games, done)

    def _run_download(self, game_id):
        g = self._game_cache.get(game_id)
        if g is None:
            # Cache miss (e.g. game appeared since the last list) — refresh once.
            games, _ = self._w().list_games()
            self._game_cache = {x.id: x for x in games}
            g = self._game_cache.get(game_id)
        if not g:
            return {"ok": False, "error": "game not found"}

        def on_progress(half, pct, mbps):
            self._emit("progress", {"id": game_id, "half": half, "percent": pct,
                                    "speed": round(mbps, 1)})
        try:
            n = self._w().download_game(g.id, g.team_id, g.date, g.opponent, on_progress)
            if self._w().cancelled():
                self._emit("cancelled", {"id": game_id})
            else:
                self._emit("saved" if n > 0 else "unavailable", {"id": game_id})
            return {"ok": True, "files": n}
        except Exception as e:
            self._emit("error", {"id": game_id, "message": str(e)})
            return {"ok": False, "error": str(e)}

    def download_game(self, game_id):
        self._w().clear_cancel()
        return self._run_download(game_id)

    def cancel(self):
        self._w().cancel()
        return {"ok": True}

    def get_thumb(self, team_id, game_id):
        return self._w().get_thumb(team_id, game_id)

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

    def download_new(self):
        self._w().clear_cancel()
        views = self.list_games()
        new_ids = [v["id"] for v in views if v["state"] == "new"]
        done = 0
        for gid in new_ids:
            if self._w().cancelled():
                break
            self._run_download(gid)
            done += 1
        return {"ok": True, "count": done}

    def set_auto(self, enabled):
        if enabled:
            platform_tasks.schedule_enable(load_config(DATA / "config.yaml").check_interval_hours)
        else:
            platform_tasks.schedule_disable()
        return platform_tasks.schedule_enabled()

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
        data = yaml.safe_load(cfgpath.read_text())
        data["output_dir"] = path
        cfgpath.write_text(yaml.safe_dump(data, sort_keys=False))
        self._w().reload_config()
        return {"ok": True, "output_dir": path}

    def get_analytics(self):
        games = self._w().compute_analytics()
        season = analytics.aggregate(games)
        return {
            "games": [{**asdict(g), "territory_svg": analytics.territory_svg(g.territory_us)}
                      for g in games],
            "season": asdict(season),
            "season_territory_svg": analytics.territory_svg(season.territory),
        }

    def export_analytics(self, fmt):
        if not self._window:
            return {"ok": False}
        games = self._w().compute_analytics()
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
        (analytics.export_csv if fmt == "csv" else analytics.export_html)(games, season, path)
        return {"ok": True, "path": str(path)}

    def save_settings(self, settings):
        path = DATA / "config.yaml"
        data = yaml.safe_load(path.read_text())
        if "quality" in settings:
            data["quality"] = settings["quality"]
        if "combine" in settings:
            data["combine_halves"] = bool(settings["combine"])
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        self._w().reload_config()
        return {"ok": True}

    def _emit(self, event, payload):
        if self._window:
            self._window.evaluate_js(f"window.onPy({json.dumps(event)}, {json.dumps(payload)})")


def main():
    from trace_grabber import firstrun, tools
    firstrun.init()
    tools.setup_browser_env()
    api = Api()
    need_setup = not tools.chromium_installed()
    first = WEB / ("setup.html" if need_setup else "index.html")
    window = webview.create_window("TraceDown", str(first), js_api=api,
                                   width=520, height=720)
    api.set_window(window)
    if need_setup:
        # Only when we showed the setup screen: install Chromium, then load the app.
        def _setup():
            try:
                tools.install_chromium()
            except Exception:
                pass
            window.load_url("file://" + str(WEB / "index.html"))
        import threading
        threading.Thread(target=_setup, daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
