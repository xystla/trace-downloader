"""Collect a team's game stats from Trace, saving each game's as it loads."""
import logging
import time
from dataclasses import dataclass, field

from . import analytics
from . import analytics_cache
from . import highlights
from .naming import game_folders
from .state import load_state

LOG = logging.getLogger(__name__)

# Newest team games whose stats are requested from Trace whether or not they are
# downloaded (and re-read on a Refresh). Any game is requested only until its
# stats are saved, and at most once a day while Trace has nothing for it.
RECENT_GAMES = 10


@dataclass
class AnalyticsResult:
    splits: list
    downloaded: int = 0     # downloaded games considered
    without_stats: int = 0  # of those, how many Trace gave no stats for
    # game id -> highlights.timeline(): the key moments, for the game page
    timelines: dict = field(default_factory=dict)


def _keep_with_game(videos_dir, meta, moments) -> None:
    """Copy a game's stats into its own folder (if it has one) under videos_dir."""
    if videos_dir:
        analytics_cache.save_with_game(game_folders(videos_dir, meta.date, meta.opponent).root,
                                       meta, moments)


def collect(request, acct, data_dir, on_progress=None, recent_only=False,
            videos_dir=None, refresh=False) -> AnalyticsResult:
    """Stats for an account's downloaded games plus its most recent
    ones. Each game's moments are saved the first time Trace returns them and
    reused afterwards, because Trace only serves a plan-limited number of
    recent games. Skips any game that errors — never fails the whole batch.
    on_progress(done, total) is called as each game is checked.
    recent_only looks at just the newest games — the quick pass used to keep
    stats from being lost in the background.
    A game whose stats are already saved is read from disk, not asked for
    again; refresh=True re-reads the newest games from Trace anyway, in case
    their stats changed.
    videos_dir is the account's videos folder: stats are copied into each
    downloaded game's folder there, and read back from it when the app's own
    copy is missing (the folder was moved to another computer)."""
    if not acct.team_urls:
        return AnalyticsResult([])
    team_slug = acct.team_urls[0].rstrip("/").split("/")[-1]
    cache_dir = acct.analytics_dir(data_dir)
    with_game = analytics_cache.in_game_folders(videos_dir) if videos_dir else {}
    cached = analytics_cache.cached_ids(cache_dir) | set(with_game)
    known_empty = analytics_cache.known_empty(cache_dir, time.time())

    token = hash_key = team_id = None
    games_by_id = {}
    try:
        token = analytics.user_token(request)
        team_id = analytics.team_numeric_id(request, team_slug)
        if token.get("token") and team_id:
            games_by_id = analytics.fetch_team_games(request, team_id, token)
    except Exception:
        LOG.exception("analytics setup failed")
    online = bool(games_by_id)   # offline: saved games only

    downloaded = set()
    for full_id in load_state(acct.state_path(data_dir)):   # ids like "teamname-13787132"
        try:
            downloaded.add(int(full_id.rsplit("-", 1)[-1]))
        except ValueError:
            continue
    ready = [(g.get("full_date") or "", num) for num, g in games_by_id.items()
             if g.get("status") == "ready"]
    recent = {num for _, num in sorted(ready, reverse=True)[:RECENT_GAMES]}
    candidates = sorted(recent if recent_only else downloaded | recent | cached, reverse=True)

    out = []
    timelines = {}
    without_stats = 0
    newly_empty = set()
    report = on_progress or (lambda done_count, total: None)
    for index, num in enumerate(candidates):
        report(index, len(candidates))
        found = None
        saved = None
        if num in cached:
            saved = analytics_cache.load(cache_dir, num) or (
                analytics_cache.load_file(with_game[num]) if num in with_game else None)
        # Stats saved before moment times were kept can't drive the timeline: ask
        # once more (at most daily) so the game gets one if Trace still has it.
        outdated = bool(saved and saved[1]) and not any("time" in m for m in saved[1])
        unknown = (num not in cached or outdated) and num not in known_empty
        asked = online and (unknown or (refresh and num in recent))
        if asked:
            try:
                if hash_key is None:     # only needed once a game is actually requested
                    hash_key = analytics.user_hash_key(request, token)
                found = _fetch_game(request, games_by_id.get(num), num,
                                    team_id, hash_key, token)
                if found:
                    analytics_cache.save(cache_dir, *found)
                    if not any("time" in m for m in found[1]):
                        newly_empty.add(num)     # nothing newer to be had today
                else:
                    newly_empty.add(num)
            except Exception:
                LOG.exception("analytics failed for game %s", num)
        fresh = found is not None
        if found is None:
            found = saved
        if found is None:
            without_stats += online and num in downloaded
            continue
        meta, moments = found
        if fresh or num not in with_game:
            _keep_with_game(videos_dir, meta, moments)
        try:
            out.append(analytics.compute_split(moments, meta))
            timelines[num] = highlights.timeline(moments, meta.our_side)
        except Exception:
            LOG.exception("analytics failed for game %s", num)
    report(len(candidates), len(candidates))
    if newly_empty:
        analytics_cache.save_empty(cache_dir, newly_empty, time.time())
    out.sort(key=lambda s: s.whole.date, reverse=True)
    return AnalyticsResult(out, downloaded=len(downloaded), without_stats=without_stats,
                           timelines=timelines)


def _fetch_game(request, game, num, team_id, hash_key, token):
    """(meta, moments) from Trace, or None when it has no stats for this game."""
    if not game or game.get("status") != "ready":
        return None
    side = analytics.our_side_for(game, team_id)
    if side is None:
        return None
    allowed, moments = analytics.fetch_game_moments(request, num, hash_key, token)
    if not allowed or not moments:
        return None
    opp = (game.get("away_team") if side == "home" else game.get("home_team")) or {}
    half = game.get("approx_half_duration") or 0
    meta = analytics.GameMeta(game_id=num,
                              date=(game.get("full_date") or "")[:10],
                              opponent=opp.get("title") or opp.get("name") or "",
                              our_side=side,
                              match_secs=half * 2)
    return meta, moments


def moments_for(request, acct, data_dir, num: int, videos_dir=None):
    """(meta, moments) for one game: fresh from Trace when it still serves the
    game (and saved), otherwise the saved copy. None when there is neither.
    With videos_dir, a copy is kept in (and read back from) the game's folder."""
    found = _moments_for(request, acct, data_dir, num)
    if found is None and videos_dir:
        path = analytics_cache.in_game_folders(videos_dir).get(num)
        found = analytics_cache.load_file(path) if path else None
    if found:
        _keep_with_game(videos_dir, *found)
    return found


def _moments_for(request, acct, data_dir, num: int):
    cache_dir = acct.analytics_dir(data_dir)
    try:
        team_slug = acct.team_urls[0].rstrip("/").split("/")[-1]
        token = analytics.user_token(request)
        hash_key = analytics.user_hash_key(request, token)
        team_id = analytics.team_numeric_id(request, team_slug)
        game = analytics.fetch_team_games(request, team_id, token).get(num)
        found = _fetch_game(request, game, num, team_id, hash_key, token)
        if found:
            analytics_cache.save(cache_dir, *found)
            return found
    except Exception:
        LOG.exception("moments fetch failed for game %s", num)
    return analytics_cache.load(cache_dir, num)


def save_recent(request, acct, data_dir, videos_dir=None) -> bool:
    """Background pass: save the newest games' stats before Trace stops serving
    them. Only for an account whose stats have been viewed; returns whether it ran."""
    if not analytics_cache.was_viewed(acct.analytics_dir(data_dir)):
        return False
    collect(request, acct, data_dir, recent_only=True, videos_dir=videos_dir)
    return True


def save_for_download(request, acct, data_dir, game_id: str, videos_dir=None) -> None:
    """Keep the stats of a game that was just downloaded (ids like "team-13787132").
    Never raises: a stats problem must not turn a finished download into a failure."""
    try:
        moments_for(request, acct, data_dir, int(game_id.rsplit("-", 1)[-1]), videos_dir=videos_dir)
    except Exception:
        LOG.exception("stats not saved for downloaded game %s", game_id)
