import json
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
from trace_grabber import analytics_sync
from trace_grabber import bookmarks as bookmark_store
from trace_grabber import analytics, edit, export, found, highlights, library, pieces, radar, recaps, segments, space
from trace_grabber.analytics_sync import AnalyticsResult
from trace_grabber import paths, platform_tasks
from trace_grabber.platform_tasks import keep_awake
from trace_grabber.session import (is_logged_in, login_status, api_logged_in,
                                    discover_teams, cookie_headers)
from trace_grabber.games import list_games
from trace_grabber import streams, quality
from trace_grabber.naming import custom_stem, game_folders, half_path, saved_files
from trace_grabber.state import load_state, mark_done, unmark
from trace_grabber.progress import Rate, percent
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

    def games_result(self):
        def load():
            games, done = self._list_games()
            return games, done, list(self._games_errors)
        return self.submit(load)

    def download_game(self, game_id, team_id, date, opponent, on_progress):
        return self.submit(lambda: self._download_game(game_id, team_id, date, opponent, on_progress))

    def partials(self, games, done):
        return self.submit(lambda: self._partials(games, done))

    # These two only touch files, so like cancel() they answer on the caller's
    # thread instead of waiting behind a download that may run for an hour.
    def discard_partial(self, game_id, date, opponent):
        return self._discard_partial(game_id, date, opponent)

    def disk_free(self):
        return self._disk_free()

    # Bookmarks and clips of your own only touch the game's files, so these too
    # answer on the caller's thread: they must work while a download is running.
    def bookmarks(self, game_id, date, opponent):
        return bookmark_store.load(self._folders(game_id, date, opponent).root)

    def add_bookmark(self, game_id, date, opponent, t, half, note=""):
        """(the new bookmark's id, every bookmark of the game)."""
        root = self._folders(game_id, date, opponent).root
        made = bookmark_store.add(root, t, half, note)
        return made["id"], bookmark_store.load(root)

    def edit_bookmark(self, game_id, date, opponent, bookmark_id, note):
        root = self._folders(game_id, date, opponent).root
        bookmark_store.edit(root, bookmark_id, note)
        return bookmark_store.load(root)

    def remove_bookmark(self, game_id, date, opponent, bookmark_id):
        root = self._folders(game_id, date, opponent).root
        bookmark_store.remove(root, bookmark_id)
        return bookmark_store.load(root)

    def export_clip(self, game_id, date, opponent, name, start, end):
        """Cut start..end (seconds into the file that was playing, given by its
        file name) into the game's My Clips folder; returns the clip's path.
        Raises RuntimeError with a message for the person."""
        start, end = float(start), float(end)
        if not highlights.MY_CLIP_MIN <= end - start <= highlights.MY_CLIP_MAX:
            raise RuntimeError("A clip can be from 1 second to 10 minutes long.")
        # The page says which file by name, and it must be one of this game's own:
        # going by "first" or "second" picks the wrong video when a half is missing
        # or an older copy of one is lying beside it.
        files = [Path(f) for f in self._game_files(date or game_id, opponent or None, game_id)]
        source = next((f for f in files if f.name == name), None)
        if source is None:
            raise RuntimeError("Couldn't find the video file. It may have been moved or renamed.")
        which = re.search(r"_half(\d)", source.name)
        half = int(which.group(1)) if which else 0
        folder = self._folders(game_id, date, opponent).my_clips
        first = folder / highlights.my_clip_name(half, start, end)
        dest, n = first, 1
        while dest.exists():                # the same stretch cut twice: keep both
            n += 1
            dest = first.with_name(f"{first.stem}-{n}{first.suffix}")
        highlights.cut_clip(source, start, end - start, dest)
        return str(dest)

    def get_thumb(self, team_id, game_id, date=None, opponent=None):
        return self.submit(lambda: self._get_thumb(team_id, game_id, date, opponent))

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

    def game_files(self, game_id, date, opponent):
        # Files only, so it answers at once: Watch Game must not wait behind a download.
        return self._game_files(date or game_id, opponent or None, game_id)

    def export_highlights(self, game_id, date, opponent, on_progress=None):
        return self.submit(lambda: self._export_highlights(game_id, date, opponent, on_progress))

    def clip_counts(self, games):
        return self.submit(lambda: self._clip_counts(games))

    def folder_to_open(self, game_id, date, opponent):
        return self.submit(lambda: self._folder_to_open(game_id, date, opponent))

    def game_media(self, game_id, date, opponent):
        return self.submit(lambda: self._game_media(game_id, date, opponent))

    def list_highlights(self, game_id, date, opponent):
        return self.submit(lambda: self._list_highlights(game_id, date, opponent))

    def download_recap(self, game_id, date, opponent, user_id, on_progress=None):
        return self.submit(
            lambda: self._download_recap(game_id, date, opponent, user_id, on_progress))

    def highlights_folder(self, game_id, date, opponent, kind="clips"):
        return self.submit(lambda: self._highlights_folder(game_id, date, opponent, kind))

    def save_stats(self):
        return self.submit(lambda: self._save_stats())

    def heatmap(self, game_id, date, opponent, fetch):
        return self.submit(lambda: self._heatmap(game_id, date, opponent, fetch))

    def compute_analytics(self, on_progress=None, refresh=False):
        return self.submit(lambda: self._compute_analytics(on_progress, refresh))

    # ---- the library: what is on disk, what has gone missing, removing a game ----
    def _found_path(self):
        return DATA / "found" / f"{self._active().id}.json"

    def team_label(self):
        acct = self._active()
        return getattr(acct, "label", "") if acct else ""

    def missing(self, games, done):
        """Ids of games on the saved list whose video can't be found: not in the
        library, and not where the person last said it was."""
        if not self._active():
            return set()
        return {g.id for g in games
                if g.id in done and not self._game_files(g.date or g.id, g.opponent or None, g.id)}

    def set_found(self, game_id, files):
        """Remember where the person says a game's video is now. It stays there."""
        acct = self._active()
        found.remember(self._found_path(), game_id, files)
        mark_done(acct.state_path(DATA), game_id)
        return True

    def storage(self, games):
        """What each listed game takes in the team's folder, largest first, with
        the folder's whole size, what in it belongs to no listed game, and the
        disk's free space."""
        acct = self._active()
        if not acct:
            return {"rows": [], "used": 0, "other": 0, "free": space.free(self._cfg.output_dir)}
        root = acct.output_dir(self._cfg.output_dir)
        done = load_state(acct.state_path(DATA))
        rows = []
        for g in games:
            videos = [Path(f) for f in self._game_files(g.date or g.id, g.opponent or None, g.id)]
            use = library.usage(self._folders(g.id, g.date, g.opponent), videos, root)
            if use["total"] or use["elsewhere"]:
                rows.append({"id": g.id, "title": f"vs {g.opponent or g.title}", "date": g.date,
                             "saved": g.id in done, "shared": bool(self._sharing(g.id, g.date, g.opponent, games)),
                             **use})
        rows.sort(key=lambda row: row["total"], reverse=True)
        used = library.size_of(root)
        return {"rows": rows, "used": used, "other": max(0, used - sum(row["total"] for row in rows)),
                "free": space.free(root)}

    def _sharing(self, game_id, date, opponent, games):
        """Other listed games kept in this game's folder: two games on one day
        against the same opponent (or with no opponent named) share it, and
        their files can't be told apart."""
        here = self._folders(game_id, date, opponent).root
        return [g for g in games if g.id != game_id and self._folders(g.id, g.date, g.opponent).root == here]

    def remove_game(self, game_id, date, opponent, everything, games=()):
        """Move a game's full video (or, with `everything`, all of the game) to
        the Trash and take it off the saved list; returns the bytes moved. A video
        the person found outside the library is left where it is and only
        forgotten. `games` are the games listed, so one that shares its folder
        with another is refused. Raises RuntimeError with a message for the
        person; if the Trash refuses, nothing is forgotten."""
        if getattr(self, "_downloading", None) == game_id:
            raise RuntimeError("This game is downloading. Stop the download first.")
        others = self._sharing(game_id, date, opponent, games)
        if others:
            names = " and ".join(sorted({f"vs {g.opponent or g.title}" for g in others}))
            raise RuntimeError(f"This game shares its folder with {names} (same day, same name), so TraceDown "
                               "can't tell their files apart. Open the folder and remove what you don't want there.")
        acct = self._active()
        root = acct.output_dir(self._cfg.output_dir)
        videos = [Path(f) for f in self._game_files(date or game_id, opponent or None, game_id)]
        try:
            paths = library.targets(self._folders(game_id, date, opponent), videos, root, everything)
        except ValueError:
            raise RuntimeError("TraceDown couldn't tell which folder is this game's, so nothing was removed.")
        moved = sum(library.size_of(p) for p in paths)
        platform_tasks.trash(paths)
        unmark(acct.state_path(DATA), game_id)
        found.forget(self._found_path(), game_id)
        return moved

    # ---- the editor: files only, so these answer on the caller's thread ----
    def _edit_teams_path(self):
        return DATA / "edit_teams.json"

    def _remembered_team(self):
        """How the person set their own team up in the editor last time, if they did."""
        try:
            return json.loads(self._edit_teams_path().read_text(encoding="utf-8")).get(self._active().id)
        except (OSError, ValueError, AttributeError):
            return None

    def _remember_team(self, team):
        try:
            known = json.loads(self._edit_teams_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
        if not isinstance(known, dict):
            known = {}
        known[self._active().id] = team
        self._write(self._edit_teams_path(), json.dumps(known, indent=1).encode("utf-8"))

    def _edit_files(self, game_id, date, opponent):
        files = self._game_files(date or game_id, opponent or None, game_id)
        if not files:
            raise RuntimeError("Download the full game first: the editor works on the saved video.")
        return files

    def edit_open(self, game_id, date, opponent, home_name, away_name):
        """The game's edit (a new one if there is none) and its video files."""
        files = self._edit_files(game_id, date, opponent)
        infos = [export.video_info(f) for f in files]
        project = edit.load(self._folders(game_id, date, opponent).root) or edit.default_project(
            home_name, away_name, self._remembered_team())
        return {"project": project, "files": files, "durations": [info["duration"] for info in infos],
                "height": infos[0]["height"]}

    def edit_save(self, game_id, date, opponent, project):
        kept = edit.save(self._folders(game_id, date, opponent).root, project)
        self._remember_team(kept["home"])
        return kept

    def export_edit(self, game_id, date, opponent, quality, on_progress=None, on_proc=None):
        """Export the game's saved edit into its Edited folder; returns the file.
        Raises RuntimeError (or NotEnoughSpace) with a message for the person."""
        files = self._edit_files(game_id, date, opponent)
        folders = self._folders(game_id, date, opponent)
        project = edit.load(folders.root)
        if project is None:
            raise RuntimeError("There is no edit for this game yet.")
        # The export can be as big as the original, and is written beside it.
        space.check(folders.root, sum(Path(f).stat().st_size for f in files) + space.MARGIN)
        name = re.sub(r"_half\d(-\d+)?$", "", Path(files[0]).stem)
        dest = folders.edited / f"{name} (edited).mp4"
        export.export(project, files, dest, quality, on_progress, on_proc)
        return str(dest)

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

    @keep_awake()
    def _list_games(self):
        acct = self._active()
        out = []
        self._games_errors = []
        for url in (acct.team_urls if acct else []):
            try:
                out.extend(list_games(self._page, url))
            except Exception as error:
                LOG.exception("game listing failed for %s", url)
                self._games_errors.append(str(error))
        out = sorted({game.id: game for game in out}.values(),
                     key=lambda game: game.date, reverse=True)
        # auto-name a freshly-migrated account from its games
        if acct and acct.label.startswith("Account ") and out and " vs. " in out[0].title:
            acct.label = out[0].title.split(" vs. ", 1)[0].strip()
            accts_mod.save_accounts(DATA, self._accounts)
        return out, load_state(acct.state_path(DATA)) if acct else set()

    @keep_awake()
    def _download_game(self, game_id, team_id, date, opponent, on_progress):
        """Download a game's halves piece by piece; returns how many halves are
        saved. A half finished by an earlier attempt is kept, and pieces already
        on disk are not fetched again. on_progress gets a dict: half, percent of
        the whole game, speed (MB/s), eta (seconds or None), joining."""
        self._downloading = game_id
        try:
            return self._fetch_game(game_id, team_id, date, opponent, on_progress)
        finally:
            self._downloading = None

    def _fetch_game(self, game_id, team_id, date, opponent, on_progress):
        acct = self._active()
        headers = cookie_headers(self._ctx)
        masters = self._resolve_masters(team_id, game_id)
        LOG.info("download %s halves=%s acct=%s", game_id, len(masters), acct.id)
        out_base = self._folders(game_id, date, opponent).full_game
        if not self._game_files(date or game_id, opponent or None, game_id):
            # Downloading a game again because its video went missing: it is not
            # "saved" on the strength of the old record while the new one is partway.
            unmark(acct.state_path(DATA), game_id)
        chosen = self._cfg.quality
        stem = self._stem(date or game_id, opponent or None)
        halves = []                 # (number, where it goes, its pieces, estimated bytes)
        for number, murl in enumerate(masters, 1):
            request = self._ctx.request
            variant, bandwidth = quality.pick_variant(request.get(murl).text(), murl, chosen)
            parts = segments.parse(request.get(variant).text(), variant)
            dest = self._half_dest(out_base, game_id, date, number, opponent, stem)
            halves.append((number, dest, parts,
                           space.estimate(bandwidth, sum(seconds for seconds, _ in parts))))
        # A half counts as done only if this same download (this game, this quality)
        # finished it; a video that merely has the name is not ours to reuse.
        done = {number for number, dest, _, _ in halves if pieces.finished(dest, game_id, chosen)}
        if halves:
            space.check(out_base, space.needed(
                [(size, pieces.bytes_on_disk(dest), number in done) for number, dest, _, size in halves],
                combine=self._cfg.combine_halves))
        # Progress is for the whole game: what earlier halves weigh, plus this half so far.
        sizes = {number: (dest.stat().st_size if number in done else size)
                 for number, dest, _, size in halves}
        finished = 0
        rate = Rate()
        last_sent = [None]

        def report(number, done, total, pieces_done, pieces_total):
            if total:
                sizes[number] = total
            game_done, game_total = finished + done, sum(sizes.values())
            now = time.monotonic()
            rate.add(now, game_done)
            joining = pieces_done == pieces_total
            if not joining and last_sent[0] is not None and now - last_sent[0] < 0.5:
                return              # a few pieces land every second; twice a second is plenty
            last_sent[0] = now
            on_progress({"half": number, "percent": percent(game_done, game_total),
                         "speed": round(rate.bytes_per_sec() / 1_000_000, 1),
                         "eta": rate.eta(game_total - game_done), "joining": joining})

        saved = 0
        half_files = []
        for number, dest, parts, _ in halves:
            if self._cancel.is_set():
                break
            if number not in done:
                try:
                    pieces.fetch(parts, dest, headers, chosen,
                                 on_progress=lambda *numbers, n=number: report(n, *numbers),
                                 should_stop=self._cancel.is_set,
                                 on_proc=lambda pr: setattr(self, "_proc", pr), owner=game_id)
                except RuntimeError:
                    if self._cancel.is_set():
                        break       # stopped: what was fetched stays, for Resume
                    raise
                finally:
                    self._proc = None
            sizes[number] = dest.stat().st_size
            finished += sizes[number]
            saved += 1
            half_files.append(dest)
        if (self._cfg.combine_halves and not self._cancel.is_set()
                and len(half_files) == 2):
            from trace_grabber import combine as _combine
            from trace_grabber.naming import combined_path
            out = combined_path(out_base, date or game_id, opponent or None, stem)
            try:
                _combine.combine(half_files, out)
                for h in half_files:
                    Path(h).unlink(missing_ok=True)
                LOG.info("combined %s -> %s", game_id, out)
            except Exception as e:
                LOG.info("combine failed for %s (keeping halves): %s", game_id, e)
        if saved and not self._cancel.is_set() and len(masters) >= 2:
            mark_done(acct.state_path(DATA), game_id)
        if saved and not self._cancel.is_set():
            for h in half_files:
                pieces.forget(h)    # the game is whole: nothing here is waiting to be resumed
            analytics_sync.save_for_download(self._ctx.request, acct, DATA, game_id,
                                             videos_dir=self._videos_dir())
        return saved

    def _stem(self, date, opponent):
        """The person's own name for a game's video (Settings), or None for the built-in one."""
        return custom_stem(getattr(self._cfg, "file_name", ""), date, opponent, self.team_label())

    @staticmethod
    def _half_dest(out_base, game_id, date, number, opponent, stem=None):
        """Where a half of this game goes. Two games on one day against the same
        opponent share a folder and a name, and an older version may have left a
        video there; a name already taken by something that isn't this game's own
        download is skipped ('…_half1-2.mp4'), never reused or overwritten.
        `stem` is the person's own file name for the video, if they set one."""
        # A download that has already begun carries on under the name it began
        # with, for both halves, whatever the file-name setting says now.
        begun = pieces.owned_in(out_base, game_id)
        for dest in begun:
            if re.search(rf"_half{number}(-\d+)?$", dest.stem):
                return dest
        if begun:
            stem = re.sub(r"_half\d(-\d+)?$", "", begun[0].stem)
        first = half_path(out_base, date or game_id, number, opponent or None, stem)
        candidate, n = first, 1
        while not (pieces.belongs(candidate, game_id)
                   or not (candidate.exists() or pieces.folder_for(candidate).exists())):
            n += 1
            candidate = first.with_name(f"{first.stem}-{n}{first.suffix}")
        return candidate

    def _half_dests(self, game_id, date, opponent):
        out_base = self._folders(game_id, date, opponent).full_game
        stem = self._stem(date or game_id, opponent or None)
        return [self._half_dest(out_base, game_id, date, number, opponent, stem) for number in (1, 2)]

    def _partials(self, games, done):
        """{game id: share downloaded, 0-1} for games not saved yet that have a
        cut-off full-game download on disk."""
        if not self._active():
            return {}
        found = {}
        for g in games:
            if g.id in done:
                continue
            shares = [1.0 if pieces.finished(dest, g.id, self._cfg.quality)
                      else pieces.progress_of(dest, owner=g.id, quality=self._cfg.quality)
                      for dest in self._half_dests(g.id, g.date, g.opponent)]
            if any(share is not None for share in shares):
                found[g.id] = sum(share or 0.0 for share in shares) / len(shares)
        return found

    def _discard_partial(self, game_id, date, opponent):
        """Delete what a cut-off full-game download left: its pieces and any half
        it finished. Returns False, deleting nothing, for a game that is saved or
        is downloading right now; files that aren't this download's are left alone."""
        acct = self._active()
        if getattr(self, "_downloading", None) == game_id or (
                acct and game_id in load_state(acct.state_path(DATA))):
            return False
        for dest in self._half_dests(game_id, date, opponent):
            if pieces.belongs(dest, game_id):
                pieces.discard(dest)
                dest.unlink(missing_ok=True)
        return True

    def _disk_free(self):
        acct = self._active()
        return space.free(acct.output_dir(self._cfg.output_dir) if acct else self._cfg.output_dir)

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

    @keep_awake()
    def _get_thumb(self, team_id, game_id, date=None, opponent=None):
        """The game's poster as a data: URL (or None), fetched from Trace only once.

        A game that has a folder keeps its poster there ('Thumbnail/thumbnail.jpg'),
        so the folder is complete on its own. Games not downloaded yet have no
        folder, and making one per listed game would litter the videos folder, so
        their posters are kept in the app's own data until the game is downloaded.
        """
        import base64
        acct = self._active()
        in_game = self._folders(game_id, date, opponent).thumbnail if acct else None
        in_app = acct.thumbs_dir(DATA) / f"{game_id}.jpg" if acct else None
        data = self._read(in_game) or self._read(in_app)
        if data is None:
            data = self._fetch_thumb(team_id, game_id)
            if data is None:
                return None
            self._write(in_app, data)
        if in_game and in_game.parent.parent.is_dir() and not in_game.exists():
            self._write(in_game, data)
        return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")

    @staticmethod
    def _read(path):
        try:
            return path.read_bytes() if path and path.exists() else None
        except OSError:
            return None

    @staticmethod
    def _write(path, data):
        """Save a small file whole-or-not-at-all; failing to save is not an error."""
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(".part")
            part.write_bytes(data)
            part.replace(path)
        except OSError:
            pass

    def _fetch_thumb(self, team_id, game_id):
        """Poster bytes from Trace, trying each URL prefix (newer 'api', older
        'us-east-2/soccer/api'), the one that last worked for this team first."""
        cached = self._thumb_prefix.get(team_id)
        order = ([cached] + [p for p in streams.PREFIXES if p != cached]
                 if cached else streams.PREFIXES)
        for prefix in order:
            url = f"{BASE_URL}/{prefix}/teams/{team_id}/games/{game_id}/poster.jpg"
            try:
                r = self._ctx.request.get(url, timeout=12000)
                if r.ok:
                    self._thumb_prefix[team_id] = prefix
                    return r.body()
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

    @keep_awake()
    def _compute_analytics(self, on_progress=None, refresh=False):
        acct = self._active()
        if not acct:
            return AnalyticsResult([])
        analytics_sync.analytics_cache.mark_viewed(acct.analytics_dir(DATA))
        return analytics_sync.collect(self._ctx.request, acct, DATA, on_progress,
                                      videos_dir=self._videos_dir(), refresh=refresh)

    def _videos_dir(self):
        """The active account's folder of game folders."""
        return self._active().output_dir(self._cfg.output_dir)

    @keep_awake()
    def _save_stats(self):
        acct = self._active()
        return bool(acct) and analytics_sync.save_recent(self._ctx.request, acct, DATA,
                                                         videos_dir=self._videos_dir())

    @keep_awake()
    def _heatmap(self, game_id, date, opponent, fetch):
        """The game's saved heat map. With `fetch`, one not saved yet is made from
        Trace's player tracking files (tens of MB a half) and kept. None when
        there is none saved, or Trace has no tracking for the game."""
        team, _, number = game_id.rpartition("-")
        directory = self._active().analytics_dir(DATA) / "heat"
        root = self._folders(game_id, date, opponent).root
        saved = radar.load(directory, int(number), game_root=root)
        if saved:
            radar.copy_to_game(root, saved)     # the game may have been downloaded since
        if saved or not fetch:
            return saved
        halves = {}
        for half, master in enumerate(self._resolve_masters(team, game_id), 1):
            resp = self._ctx.request.get(radar.radar_url(master, half), timeout=180000)
            if resp.ok:
                halves[half] = radar.heat(resp.json(), team)
        built = radar.build(halves)
        if built:
            radar.save(directory, int(number), built, game_root=root)
        return built

    @keep_awake()
    def _export_highlights(self, game_id, date, opponent, on_progress=None):
        """(folder, clip count, already saved). Highlights saved earlier are kept
        as they are. With the game downloaded, clips are cut from the local video;
        without it, they are fetched straight from Trace (on_progress(done, total)
        follows them, cancel() stops them). Raises RuntimeError with a message
        for the user."""
        folders = self._folders(game_id, date, opponent)
        folder, count = self._saved_clips(folders)
        if count:
            highlights.build_reel(folder)      # clips cut before reels existed get one
            return folder, count, True
        found = analytics_sync.moments_for(self._ctx.request, self._active(), DATA,
                                           int(game_id.rsplit("-", 1)[-1]),
                                           videos_dir=self._videos_dir())
        if not found:
            raise RuntimeError("Trace has no moments for this game, so there are no highlights to make.")
        meta, moments = found
        files = self._game_files(date or game_id, opponent or None, game_id)
        if files:
            folder, count = highlights.export(moments, meta.our_side, files, folders.highlights)
        else:
            try:
                folder, count = highlights.export_remote(
                    moments, meta.our_side, self._half_playlists(game_id), folders.highlights,
                    on_progress=on_progress, on_proc=lambda pr: setattr(self, "_proc", pr),
                    should_stop=self._cancel.is_set)
            finally:
                self._proc = None
        if count:
            highlights.build_reel(folder)
        return folder, count, False

    def _half_playlists(self, game_id):
        """{half: pieces} of the game's video on Trace, at the configured quality."""
        team_id = game_id.rpartition("-")[0]
        request = self._ctx.request
        playlists = {}
        for half, master in enumerate(self._resolve_masters(team_id, game_id), 1):
            variant = quality.pick_from_master(request.get(master).text(), master, self._cfg.quality)
            playlists[half] = segments.parse(request.get(variant).text(), variant)
        return playlists

    def _folders(self, game_id, date, opponent):
        return game_folders(self._active().output_dir(self._cfg.output_dir),
                            date or game_id, opponent or None)

    # Clips and recaps are looked for in the game's own folders first, then in
    # the '<game>_highlights' folder they shared before.
    @staticmethod
    def _saved_clips(folders):
        """(folder, count) of team clips already cut for a game, else (None, 0)."""
        for folder in (folders.highlights, folders.legacy_highlights):
            count = highlights.clip_count(folder)
            if count:
                return folder, count
        return None, 0

    @staticmethod
    def _saved_recap(folders, player):
        """Path of a player's recap if it is already saved, else None."""
        for folder in (folders.players, folders.legacy_highlights):
            path = folder / recaps.recap_name(player)
            if path.exists():
                return path
        return None

    def _folder_to_open(self, game_id, date, opponent):
        """Where "Open Folder" should go for a game: its own folder if it has
        one, else the older highlights folder, else the team's folder."""
        folders = self._folders(game_id, date, opponent)
        for folder in (folders.root, folders.legacy_highlights):
            if folder.is_dir():
                return str(folder)
        team = folders.root.parent
        team.mkdir(parents=True, exist_ok=True)
        return str(team)

    def _game_media(self, game_id, date, opponent):
        """Every video saved for a game: the full game, the highlight reel, each
        clip and each player recap, as file paths with labels to show."""
        folders = self._folders(game_id, date, opponent)
        clips_dir = self._saved_clips(folders)[0]
        reel = clips_dir / highlights.REEL_NAME if clips_dir else None
        recap_files = []
        for folder in (folders.players, folders.legacy_highlights):
            if folder.is_dir():
                recap_files = sorted(p for p in folder.glob("player-*.mp4")
                                     if not p.name.endswith(".part.mp4"))
                if recap_files:
                    break
        number = lambda p: int(p.stem.split("-")[1]) if p.stem.split("-")[1].isdigit() else 10 ** 9
        return {"full": self._game_files(date or game_id, opponent or None, game_id),
                "reel": str(reel) if reel and reel.exists() else None,
                "clips": [{"label": highlights.clip_label(p.name), "path": str(p),
                           "half": highlights.clip_place(p.name)[0],
                           "start": highlights.clip_place(p.name)[1]}
                          for p in (highlights.saved_clips(clips_dir) if clips_dir else [])],
                "recaps": [{"label": recaps.recap_label(p.name), "path": str(p)}
                           for p in sorted(recap_files, key=lambda p: (number(p), p.name))],
                "mine": [{"label": highlights.my_clip_label(p.name), "path": str(p)}
                         for p in highlights.my_clips(folders.my_clips)],
                "edited": [{"label": "Edited game", "path": str(p)} for p in sorted(folders.edited.glob("*.mp4"))
                           if not p.name.endswith(".part.mp4")] if folders.edited.is_dir() else []}

    def _clip_counts(self, games):
        """{game id: team clips already cut}, for games that have any."""
        if not self._active():
            return {}
        counts = {g.id: self._saved_clips(self._folders(g.id, g.date, g.opponent))[1]
                  for g in games}
        return {game_id: n for game_id, n in counts.items() if n}

    def _highlights_folder(self, game_id, date, opponent, kind="clips"):
        """The folder holding a game's team clips ("clips"), player recaps
        ("recaps") or your own clips ("mine"), or None when nothing of that kind
        is saved yet."""
        folders = self._folders(game_id, date, opponent)
        if kind == "clips":
            folder = self._saved_clips(folders)[0]
            if folder:
                highlights.build_reel(folder)
        elif kind == "mine":
            folder = folders.my_clips if highlights.my_clips(folders.my_clips) else None
        else:
            folder = next((f for f in (folders.players, folders.legacy_highlights)
                           if f.is_dir() and any(f.glob("player-*.mp4"))), None)
        return str(folder) if folder else None

    def _game_players(self, game_id):
        team_slug, _, num = game_id.rpartition("-")
        request = self._ctx.request
        return recaps.game_players(request, team_slug, int(num), analytics.user_token(request))

    def _list_highlights(self, game_id, date, opponent):
        """What a game's highlights folder holds, and each player's recap: already
        saved, or how long it is ("seconds": 0 when Trace has none for this game)."""
        folders = self._folders(game_id, date, opponent)
        num = int(game_id.rsplit("-", 1)[-1])
        players = []
        for p in self._game_players(game_id):
            saved = self._saved_recap(folders, p) is not None
            seconds = None if saved else (
                len(recaps.fetch_segments(self._ctx.request, p.user_id, num)) * recaps.SEGMENT_SECS)
            players.append({"user_id": p.user_id, "number": p.number, "name": p.name,
                            "saved": saved, "seconds": seconds})
        return {"team_clips": self._saved_clips(folders)[1], "players": players}

    @keep_awake()
    def _download_recap(self, game_id, date, opponent, user_id, on_progress=None):
        """Save one player's recap; returns its path. A recap saved earlier is kept.
        on_progress(percent) follows the download; cancel() stops it mid-file."""
        player = next((p for p in self._game_players(game_id) if p.user_id == user_id), None)
        if player is None:
            raise RuntimeError("That player isn't on this game's roster.")
        folders = self._folders(game_id, date, opponent)
        saved = self._saved_recap(folders, player)
        if saved:
            return str(saved)
        dest = folders.players / recaps.recap_name(player)
        urls = recaps.fetch_segments(self._ctx.request, user_id, int(game_id.rsplit("-", 1)[-1]))
        if not urls:
            raise RuntimeError("Trace has no recap for this player in this game.")
        try:
            recaps.download(urls, dest, progress_cb=on_progress,
                            on_proc=lambda pr: setattr(self, "_proc", pr))
        finally:
            self._proc = None
        return str(dest)

    def _game_files(self, date, opponent, game_id=None):
        """A game's full-game video files: those in the library, else (given the
        game's id) the ones the person found elsewhere that can be reached now."""
        acct = self._active()
        if not acct:
            return []
        files = saved_files(acct.output_dir(self._cfg.output_dir), date, opponent)
        if not files and game_id:
            files = found.existing(self._found_path(), game_id)
        return [str(p) for p in files]
