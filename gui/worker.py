import logging
import queue
import re
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from playwright.sync_api import sync_playwright

from trace_grabber.config import load_config
from trace_grabber import accounts as accts_mod
from trace_grabber import analytics
from trace_grabber import paths
from trace_grabber.session import (is_logged_in, login_status, api_logged_in,
                                    discover_teams, cookie_headers)
from trace_grabber.games import list_games
from trace_grabber import streams, quality
from trace_grabber.download import download
from trace_grabber.naming import build_path
from trace_grabber.state import load_state, mark_done
from trace_grabber.progress import playlist_duration
from trace_grabber.selectors import BASE_URL

DATA = paths.data_dir()
(DATA / "debug").mkdir(exist_ok=True)
logging.basicConfig(filename=str(DATA / "debug" / "gui.log"), level=logging.INFO,
                    format="%(asctime)s %(message)s")
LOG = logging.getLogger("trace_gui")

class Worker:
    """All Playwright/ffmpeg work on one dedicated thread, for the active account."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._proc = None
        self._athlete_id = None
        self._login_detail = ""  # last login-check detail, surfaced in the UI for diagnostics
        self._thumb_prefix = {}  # team_id -> working URL prefix, learned on first hit
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._started = threading.Event()
        self._thread.start()
        self._started.wait()

    # cancel control — these run on the CALLER's thread (not the job queue),
    # because the worker thread is blocked inside the running download.
    def clear_cancel(self):
        self._cancel.clear()

    def cancelled(self):
        return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()
        p = self._proc
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass

    def submit(self, fn):
        fut: Future = Future()
        self._jobs.put((fn, fut))
        return fut.result()

    # ---- public API ----
    def logged_in(self):
        return self.submit(lambda: self._logged_in())

    def login_detail(self):
        return self.submit(lambda: self._login_detail)

    def list_games(self):
        return self.submit(lambda: self._list_games())

    def download_game(self, game_id, team_id, date, opponent, on_progress):
        return self.submit(lambda: self._download_game(game_id, team_id, date, opponent, on_progress))

    def get_thumb(self, team_id, game_id):
        return self.submit(lambda: self._get_thumb(team_id, game_id))

    def list_accounts(self):
        return self.submit(lambda: self._list_accounts())

    def switch_account(self, account_id):
        return self.submit(lambda: self._switch_account(account_id))

    def remove_account(self, account_id):
        return self.submit(lambda: self._remove_account(account_id))

    def add_account_start(self):
        return self.submit(lambda: self._add_account_start())

    def add_account_finish(self):
        return self.submit(lambda: self._add_account_finish())

    def add_account_poll(self):
        return self.submit(lambda: self._add_account_poll())

    def add_account_cancel(self):
        return self.submit(lambda: self._add_account_cancel())

    def confirm_team_url(self, url):
        return self.submit(lambda: self._confirm_team_url(url))

    def reconnect_start(self):
        return self.submit(lambda: self._reconnect_start())

    def reconnect_finish(self):
        return self.submit(lambda: self._reconnect_finish())

    def reload_config(self):
        return self.submit(lambda: self._reload_config())

    def compute_analytics(self):
        return self.submit(lambda: self._compute_analytics())

    # ---- thread internals ----

    def _open_ctx(self, profile_dir: str, headless: bool):
        self._headless = headless
        self._profile_dir = profile_dir
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(DATA / profile_dir), headless=headless)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def _open_active(self):
        self._accounts = accts_mod.load_accounts(DATA)
        acct = self._accounts.active
        if acct:
            self._open_ctx(acct.profile_dir, headless=True)
        else:
            self._open_ctx("profiles/_empty", headless=True)

    def _run(self):
        with sync_playwright() as p:
            self._pw = p
            self._cfg = load_config(DATA / "config.yaml")
            self._open_active()
            self._started.set()
            while True:
                fn, fut = self._jobs.get()
                if fn is None:
                    break
                try:
                    fut.set_result(fn())
                except Exception as e:  # noqa
                    LOG.exception("job failed")
                    fut.set_exception(e)

    def _active(self):
        return self._accounts.active

    def _logged_in(self):
        acct = self._active()
        if not acct or not acct.team_urls:
            self._login_detail = "no account / no team URL"
            return False
        # API check is instant and authoritative; only fall back to the DOM
        # check (which can race the SPA) if the API itself is unreachable.
        ok, detail = api_logged_in(self._ctx.request)
        if not ok and detail.startswith("api unreachable"):
            ok, detail = login_status(self._page, acct.team_urls[0])
        self._login_detail = detail
        LOG.info("login check: %s", detail)
        return ok

    def _list_games(self):
        acct = self._active()
        out = []
        for url in (acct.team_urls if acct else []):
            out.extend(list_games(self._page, url))
        # auto-name a freshly-migrated account from its games
        if acct and acct.label.startswith("Account ") and out and " vs. " in out[0].title:
            acct.label = out[0].title.split(" vs. ", 1)[0].strip()
            accts_mod.save_accounts(DATA, self._accounts)
        return out, load_state(acct.state_path(DATA)) if acct else set()

    def _download_game(self, game_id, team_id, date, opponent, on_progress):
        acct = self._active()
        headers = cookie_headers(self._ctx)
        masters = self._resolve_masters(team_id, game_id)
        LOG.info("download %s halves=%s acct=%s", game_id, len(masters), acct.id)
        saved = 0
        out_base = acct.output_dir(self._cfg.output_dir)
        half_files = []
        for half, murl in enumerate(masters, 1):
            if self._cancel.is_set():
                break
            variant = quality.pick_from_master(self._ctx.request.get(murl).text(), murl, self._cfg.quality)
            dur = playlist_duration(self._ctx.request.get(variant).text())
            dest = build_path(out_base, date or game_id, half, opponent or None)
            try:
                download(variant, dest, headers,
                         progress_cb=lambda pct, mbps, h=half: on_progress(h, pct, mbps),
                         duration=dur, on_proc=lambda pr: setattr(self, "_proc", pr))
            except RuntimeError:
                if self._cancel.is_set():
                    Path(dest).unlink(missing_ok=True)  # remove the partial file
                    break
                raise
            finally:
                self._proc = None
            saved += 1
            half_files.append(dest)
        if (self._cfg.combine_halves and not self._cancel.is_set()
                and len(half_files) == 2):
            from trace_grabber import combine as _combine
            from trace_grabber.naming import combined_path
            out = combined_path(out_base, date or game_id, opponent or None)
            try:
                _combine.combine(half_files, out)
                for h in half_files:
                    Path(h).unlink(missing_ok=True)
                LOG.info("combined %s -> %s", game_id, out)
            except Exception as e:
                LOG.info("combine failed for %s (keeping halves): %s", game_id, e)
        if saved and not self._cancel.is_set() and len(masters) >= 2:
            mark_done(acct.state_path(DATA), game_id)
        return saved

    def _resolve_masters(self, team_id, game_id):
        """Known prefixes first; watch-page fallback for any new path variant."""
        return streams.resolve_masters(self._ctx.request, self._page, self._athlete,
                                       team_id, game_id)

    def _athlete(self):
        """Discover the logged-in athlete id once (cached for the session)."""
        if not self._athlete_id:
            acct = self._active()
            if acct and acct.team_urls:
                self._athlete_id = streams.discover_athlete(self._page, acct.team_urls[0])
        return self._athlete_id

    def _get_thumb(self, team_id, game_id):
        """Fetch the game's poster with the session and return a data: URL (or None).

        Tries both URL prefixes (newer 'api', older 'us-east-2/soccer/api').
        """
        import base64
        # Try the prefix that worked for this team first (saves up to 2 failing
        # requests per game once the team's prefix is known).
        cached = self._thumb_prefix.get(team_id)
        order = ([cached] + [p for p in streams.PREFIXES if p != cached]
                 if cached else streams.PREFIXES)
        for prefix in order:
            url = f"{BASE_URL}/{prefix}/teams/{team_id}/games/{game_id}/poster.jpg"
            try:
                r = self._ctx.request.get(url, timeout=12000)
                if r.ok:
                    self._thumb_prefix[team_id] = prefix
                    b64 = base64.b64encode(r.body()).decode("ascii")
                    return f"data:image/jpeg;base64,{b64}"
            except Exception:
                continue
        return None

    def _list_accounts(self):
        self._accounts = accts_mod.load_accounts(DATA)
        return {"active": self._accounts.active_id,
                "accounts": [{"id": a.id, "label": a.label} for a in self._accounts.items]}

    def _switch_account(self, account_id):
        self._ctx.close()
        accts_mod.set_active(DATA, self._accounts, account_id)
        self._open_active()
        return self._list_accounts()

    def _remove_account(self, account_id):
        was_active = self._accounts.active_id == account_id
        if was_active:
            self._ctx.close()
        accts_mod.remove_account(DATA, self._accounts, account_id)
        if was_active:
            self._open_active()
        return self._list_accounts()

    # ---- add-account flow (headed) ----
    def _add_account_start(self):
        self._ctx.close()
        self._pending_profile = f"profiles/pending-{int(time.monotonic()*1000)}"
        self._open_ctx(self._pending_profile, headless=False)
        self._page.goto("https://traceup.com", wait_until="domcontentloaded")
        return True

    def _finalize(self, team_urls, label):
        # move pending profile to a stable per-id dir
        acct_id = accts_mod.slugify(label) or f"account-{len(self._accounts.items)+1}"
        stable = f"profiles/{acct_id}"
        self._ctx.close()
        src = DATA / self._pending_profile
        dst = DATA / stable
        if src.exists():
            src.replace(dst)
        accts_mod.add_account(DATA, self._accounts, label=label,
                              team_urls=team_urls, profile_dir=stable)
        self._open_active()
        return self._list_accounts()

    def _add_account_poll(self):
        """Called repeatedly while the login window is open. As soon as the
        session is live, discover the team(s) via the API and finish — the user
        never has to leave the login page or click anything."""
        try:
            ok, _ = api_logged_in(self._ctx.request)
        except Exception as e:
            return {"status": "error",
                    "detail": f"the login window was closed ({e!r})"}
        if not ok:
            return {"status": "waiting"}
        teams = discover_teams(self._ctx.request)
        if not teams:
            return {"status": "logged_in_no_team",
                    "detail": "Logged in, but no team was found on this account."}
        self._finalize([u for u, _ in teams], teams[0][1])
        return {"status": "done", "detail": f"connected: {teams[0][1]}"}

    def _add_account_finish(self):
        """Manual 'Connect now' button — same API discovery, run on demand."""
        res = self._add_account_poll()
        if res.get("status") == "done":
            return {"ok": True, "detail": res["detail"]}
        if res.get("status") == "waiting":
            return {"detail": "Not logged in yet — finish the email + code login "
                              "in the TraceDown window, then it'll connect on its own."}
        return {"needs_url": True, "detail": res.get("detail", "Couldn't detect your team.")}

    def _add_account_cancel(self):
        try:
            self._ctx.close()
        except Exception:
            pass
        self._open_active()
        return True

    def _confirm_team_url(self, url):
        # Normalize: accept a full URL or bare id, strip query/hash.
        url = url.strip().split("?")[0].split("#")[0].rstrip("/")
        m = re.search(r'/traceid/team/([a-z0-9]+)', url)
        if not m and re.fullmatch(r'[a-z0-9]+', url):
            url = f"{BASE_URL}/traceid/team/{url}"
            m = True
        if not m:
            return {"needs_url": True, "detail": f"that doesn't look like a team URL: {url}"}
        try:
            games = list_games(self._page, url)
        except Exception:
            games = []
        label = (games[0].title.split(" vs. ", 1)[0].strip()
                 if games and " vs. " in games[0].title else "Account")
        self._finalize([url], label)
        return {"ok": True, "detail": f"connected: {label}"}

    # ---- reconnect flow (kept for compatibility) ----
    def _reconnect_start(self):
        self._ctx.close()
        self._open_ctx(self._accounts.active.profile_dir if self._accounts.active else ".chrome-profile",
                       headless=False)
        self._page.goto("https://traceup.com", wait_until="domcontentloaded")
        return True

    def _reconnect_finish(self):
        acct = self._active()
        self._ctx.close()
        self._open_ctx(acct.profile_dir if acct else ".chrome-profile", headless=True)
        if not acct or not acct.team_urls:
            return False
        return is_logged_in(self._page, acct.team_urls[0])

    def _reload_config(self):
        self._cfg = load_config(DATA / "config.yaml")
        return True

    def _compute_analytics(self):
        """Stats for the active account's DOWNLOADED games (state.json). Skips any
        game that isn't accessible or errors — never fails the whole batch."""
        acct = self._active()
        if not acct or not acct.team_urls:
            return []
        team_slug = acct.team_urls[0].rstrip("/").split("/")[-1]
        request = self._ctx.request

        try:
            token = analytics.user_token(request)
            hash_key = analytics.user_hash_key(request)
            team_id = analytics.team_numeric_id(request, team_slug)
            if not (token.get("token") and team_id):
                return []
            games_by_id = analytics.fetch_team_games(request, team_id, token)
        except Exception:
            LOG.exception("analytics setup failed")
            return []
        done = load_state(acct.state_path(DATA))   # ids like "hjmwnzo2-13787132"
        out = []
        for full_id in done:
            try:
                num = int(full_id.rsplit("-", 1)[-1])
            except ValueError:
                continue
            game = games_by_id.get(num)
            if not game or game.get("status") != "ready":
                continue
            side = analytics.our_side_for(game, team_id)
            if side is None:
                continue
            try:
                allowed, moments = analytics.fetch_game_moments(request, num, hash_key, token)
                if not allowed or not moments:
                    continue
                opp = (game.get("away_team") if side == "home"
                       else game.get("home_team")) or {}
                meta = analytics.GameMeta(game_id=num,
                                          date=(game.get("full_date") or "")[:10],
                                          opponent=opp.get("title") or opp.get("name") or "",
                                          our_side=side)
                out.append(analytics.compute_game_stats(moments, meta))
            except Exception:
                LOG.exception("analytics failed for game %s", full_id)
                continue
        out.sort(key=lambda s: s.date, reverse=True)
        return out
