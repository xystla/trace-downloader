import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import load_config
from . import accounts as accts_mod
from . import paths
from .platform_tasks import keep_awake, notify
from .session import is_logged_in, cookie_headers
from .games import list_games, list_new_games
from . import analytics_sync, streams, quality
from .download import download
from .naming import build_path, game_folders
from .state import mark_done

DATA = paths.data_dir()
LAST_RUN = DATA / "last_run.json"

def write_last_run(path, count: int, error, when: str | None = None) -> None:
    when = when or datetime.now().isoformat(timespec="seconds")
    Path(path).write_text(json.dumps({"count": count, "error": error, "when": when}))

def _make_athlete_getter(page, team_url):
    """Cached 0-arg getter for the account's athlete id (used by the watch-page fallback)."""
    cache = {}
    def getter():
        if "id" not in cache:
            cache["id"] = streams.discover_athlete(page, team_url) if team_url else None
        return cache["id"]
    return getter

@keep_awake()
def _download_game(ctx, page, athlete_getter, headers, cfg, acct, game) -> int:
    masters = streams.resolve_masters(ctx.request, page, athlete_getter, game.team_id, game.id)
    out_base = game_folders(acct.output_dir(cfg.output_dir), game.date or game.id,
                            game.opponent).full_game
    saved = 0
    half_files = []
    for half, murl in enumerate(masters, 1):
        variant = quality.pick_from_master(ctx.request.get(murl, timeout=15000).text(), murl, cfg.quality)
        dest = build_path(out_base, game.date or game.id, half, game.opponent)
        download(variant, dest, headers)
        print(f"saved {dest}")
        saved += 1
        half_files.append(dest)
    if cfg.combine_halves and len(half_files) == 2:
        from . import combine as _combine
        from .naming import combined_path
        out = combined_path(out_base, game.date or game.id, game.opponent)
        try:
            _combine.combine(half_files, out)
            for h in half_files:
                Path(h).unlink(missing_ok=True)
            print(f"combined -> {out}")
        except Exception as e:
            print(f"combine failed (keeping halves): {e}", file=sys.stderr)
    if saved and len(masters) >= 2:
        mark_done(acct.state_path(DATA), game.id)
    if saved:
        analytics_sync.save_for_download(ctx.request, acct, DATA, game.id,
                                         videos_dir=acct.output_dir(cfg.output_dir))
    return saved

@keep_awake()
def _save_stats(ctx, acct, data_dir=DATA, videos_dir=None) -> None:
    """Save stats for the newest games now (for accounts whose stats have been
    viewed): Trace stops serving them once they are no longer among the team's
    most recent, whether or not the app was opened."""
    try:
        analytics_sync.save_recent(ctx.request, acct, data_dir, videos_dir=videos_dir)
    except Exception as e:
        print(f"stats not saved for {acct.label}: {e}", file=sys.stderr)

def _open(p, acct):
    ctx = p.chromium.launch_persistent_context(str(acct.profile_path(DATA)), headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page

def run(mode: str = "new") -> int:
    cfg = load_config(DATA / "config.yaml")
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    accounts = accts_mod.load_accounts(DATA)
    with sync_playwright() as p:
        if mode in ("seed", "latest"):
            acct = accounts.active
            if not acct:
                print("no active account", file=sys.stderr); return 1
            if not acct.team_urls:
                print("active account has no team URL", file=sys.stderr); return 1
            ctx, page = _open(p, acct)
            try:
                if not is_logged_in(page, acct.team_urls[0]):
                    print("Session expired for active account.", file=sys.stderr); return 1
                if mode == "seed":
                    n = 0
                    for url in acct.team_urls:
                        for g in list_games(page, url):
                            mark_done(acct.state_path(DATA), g.id); n += 1
                    print(f"seeded {n} game(s) for {acct.label}"); return 0
                games = list_games(page, acct.team_urls[0])
                if not games:
                    print("no games"); return 0
                headers = cookie_headers(ctx)
                getter = _make_athlete_getter(page, acct.team_urls[0])
                total = _download_game(ctx, page, getter, headers, cfg, acct, games[0])
                print(f"done — {total} file(s)"); return 0
            finally:
                ctx.close()

        total = 0
        for acct in accounts.items:
            ctx, page = _open(p, acct)
            try:
                if not acct.team_urls or not is_logged_in(page, acct.team_urls[0]):
                    notify(f"{acct.label}: session expired — open the app to reconnect")
                    print(f"{acct.label}: not logged in", file=sys.stderr)
                    continue
                headers = cookie_headers(ctx)
                getter = _make_athlete_getter(page, acct.team_urls[0])
                for url in acct.team_urls:
                    for game in list_new_games(page, url, acct.state_path(DATA)):
                        try:
                            total += _download_game(ctx, page, getter, headers, cfg, acct, game)
                        except Exception as e:
                            print(f"FAILED {game.id}: {e}", file=sys.stderr)
                _save_stats(ctx, acct, videos_dir=acct.output_dir(cfg.output_dir))
            finally:
                ctx.close()
        if total:
            notify(f"Downloaded {total} video(s)")
        write_last_run(LAST_RUN, count=total, error=None)
        print(f"done — {total} file(s)")
    return 0

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "new"
    if mode not in {"new", "seed", "latest"}:
        print("usage: python -m trace_grabber.main [new|seed|latest]", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(mode))
