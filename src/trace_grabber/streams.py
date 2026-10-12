"""Build game-camera HLS URLs directly from a game id.

Trace stores each game's camera footage as HLS under one of two path
prefixes (newer games use `api`, older games use `us-east-2/soccer/api`):
    {BASE}/{prefix}/teams/{team}/games/{game}/gamevideo{half}.hls/game_video.m3u8
Soccer games have two halves -> gamevideo1 (1st) and gamevideo2 (2nd).
`game_video.m3u8` is the master playlist; quality.pick_from_master selects
the highest-resolution variant. No player automation is needed.
"""
import logging
import re
from urllib.parse import urlsplit

from . import selectors as S

LOG = logging.getLogger(__name__)

# Tried in order; whichever returns 200 for a given game is used. Trace serves a
# game's video from the region bucket it was processed in and 403s the others, so
# every live region must be listed. As of Oct 2026 new games land in us-west-2
# (newer "superfly"-camera games under its qaapi prefix); older games remain in
# us-east-2, and some predate the regioned paths entirely (bare "api").
PREFIXES = [
    "us-west-2/soccer/api", "us-west-2/soccer/qaapi",
    "us-east-2/soccer/api", "us-east-2/soccer/qaapi",
    "api",
]

def prefix_from_base_path(base_path: str | None) -> str | None:
    """The URL prefix out of the `base_path` Trace lists a game with, e.g.
    `/us-west-1/soccer/api/teams/<team>/games/<game>/` -> `us-west-1/soccer/api`.
    This is the game's real place, whatever region it is in; None if absent."""
    prefix, found, _ = (base_path or "").partition("/teams/")
    return prefix.strip("/") or None if found else None

def prefix_from_url(url: str, team_id: str, game_id: str) -> str | None:
    """The URL prefix out of the address of any of this game's files on Trace
    (video, poster, animations...), or None if the address isn't one."""
    if not url.startswith(S.BASE_URL + "/"):
        return None
    prefix, found, _ = urlsplit(url).path.partition(f"/teams/{team_id}/games/{game_id}/")
    return prefix.strip("/") or None if found else None

def prefix_from_html(html: str, team_id: str, game_id: str) -> str | None:
    """Extract the real URL prefix for a game from its watch-page HTML.

    The page contains the true path, e.g.
    `/us-east-2/soccer/qaapi/teams/<team>/games/<game>/gamevideo1.hls/game_video.m3u8`.
    Returns the prefix (`us-east-2/soccer/qaapi`) or None. This is the fallback
    when no known prefix in PREFIXES serves the game.
    """
    tail = re.escape(f"/teams/{team_id}/games/{game_id}/gamevideo")
    m = re.search(r"([A-Za-z0-9][A-Za-z0-9/_-]*)" + tail + r"\d\.hls/game_video\.m3u8", html)
    return m.group(1).strip("/") if m else None

def master_url(team_id: str, game_id: str, half: int, prefix: str = "api") -> str:
    return (
        f"{S.BASE_URL}/{prefix}/teams/{team_id}/games/{game_id}"
        f"/gamevideo{half}.hls/game_video.m3u8"
    )

def resolve_prefix(request, team_id: str, game_id: str, known: str | None = None) -> str | None:
    """Return the path prefix that serves this game's video, or None if neither does.

    `request` is a Playwright APIRequestContext carrying the logged-in session.
    `known` is the prefix Trace listed the game under (Game.prefix); it is tried
    first, so a game in a region PREFIXES doesn't have is still found.
    """
    for prefix in ([known] if known else []) + [p for p in PREFIXES if p != known]:
        try:
            if request.get(master_url(team_id, game_id, 1, prefix), timeout=15000).ok:
                return prefix
        except Exception:
            continue
    return None

def discover_athlete(page, team_url: str) -> str | None:
    """Find the logged-in athlete id by clicking a game card (the watch URL has it).
    `page` is a Playwright page. Returns the id or None."""
    try:
        page.goto(team_url, wait_until="domcontentloaded")
        page.wait_for_selector(".GameCard", timeout=20000)
        page.click(".GameCard .thumbnail")
        page.wait_for_timeout(3000)
        m = re.search(r"/athlete/([A-Z0-9]+)/", page.url)
        return m.group(1) if m else None
    except Exception:
        return None

def prefix_via_watch(page, athlete_id: str, team_id: str, game_id: str) -> str | None:
    """Open a game's watch page and read its real prefix off the page: the
    addresses it fetches the game's files from, or failing that its HTML."""
    num = game_id.split("-")[-1]
    asked = []
    note = lambda request: asked.append(request.url)
    page.on("request", note)
    try:
        page.goto(f"{S.BASE_URL}/traceid/athlete/{athlete_id}/watch/{num}",
                  wait_until="domcontentloaded", timeout=25000)
        for _ in range(20):             # the game's files are asked for a second or two in
            found = next(filter(None, (prefix_from_url(url, team_id, game_id) for url in asked)), None)
            if found:
                return found
            page.wait_for_timeout(500)
        return prefix_from_html(page.content(), team_id, game_id)
    except Exception:
        return None
    finally:
        page.remove_listener("request", note)

def resolve_masters(request, page, athlete_getter, team_id: str, game_id: str,
                    known: str | None = None) -> list[str]:
    """Known-prefix master URLs; if none, fall back to reading the real prefix off
    the watch page (so brand-new path variants never silently fail).
    `athlete_getter` is a 0-arg callable returning the athlete id, called only on fallback."""
    masters = available_masters(request, team_id, game_id, known=known)
    if masters:
        return masters
    athlete_id = athlete_getter()
    prefix = prefix_via_watch(page, athlete_id, team_id, game_id) if athlete_id else None
    # Enough to tell, from a log someone sends in, why a game that plays on Trace
    # came up empty here.
    LOG.warning("no video at the known places for %s: listed under %r, watch page says %r (athlete found: %s)",
                game_id, known, prefix, bool(athlete_id))
    if not prefix:
        return []
    out = []
    for half in (1, 2):
        url = master_url(team_id, game_id, half, prefix)
        try:
            if request.get(url, timeout=15000).ok:
                out.append(url)
        except Exception:
            continue
    if not out:
        LOG.warning("no video for %s under %r either", game_id, prefix)
    return out

def available_masters(request, team_id: str, game_id: str, max_halves: int = 2,
                      known: str | None = None) -> list[str]:
    """Return the working master-playlist URLs for each half, in order.

    Empty list means the game has no downloadable game-camera video.
    """
    prefix = resolve_prefix(request, team_id, game_id, known)
    if not prefix:
        return []
    masters = []
    for half in range(1, max_halves + 1):
        url = master_url(team_id, game_id, half, prefix)
        try:
            if request.get(url, timeout=15000).ok:
                masters.append(url)
        except Exception:
            continue
    return masters
