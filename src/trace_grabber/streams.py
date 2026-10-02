"""Build game-camera HLS URLs directly from a game id.

Trace stores each game's camera footage as HLS under one of two path
prefixes (newer games use `api`, older games use `us-east-2/soccer/api`):
    {BASE}/{prefix}/teams/{team}/games/{game}/gamevideo{half}.hls/game_video.m3u8
Soccer games have two halves -> gamevideo1 (1st) and gamevideo2 (2nd).
`game_video.m3u8` is the master playlist; quality.pick_from_master selects
the highest-resolution variant. No player automation is needed.
"""
import re

from . import selectors as S

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

def resolve_prefix(request, team_id: str, game_id: str) -> str | None:
    """Return the path prefix that serves this game's video, or None if neither does.

    `request` is a Playwright APIRequestContext carrying the logged-in session.
    """
    for prefix in PREFIXES:
        try:
            if request.get(master_url(team_id, game_id, 1, prefix), timeout=15000).ok:
                return prefix
        except Exception:
            continue
    return None

def discover_athlete(page, team_url: str) -> str | None:
    """Find the logged-in athlete id by clicking a game card (the watch URL has it).
    `page` is a Playwright page. Returns the id or None."""
    import re
    try:
        page.goto(team_url, wait_until="domcontentloaded")
        page.wait_for_selector("a.GameLink.GameCard", timeout=20000)
        page.click("a.GameLink.GameCard")
        page.wait_for_timeout(3000)
        m = re.search(r"/athlete/([A-Z0-9]+)/", page.url)
        return m.group(1) if m else None
    except Exception:
        return None

def prefix_via_watch(page, athlete_id: str, team_id: str, game_id: str) -> str | None:
    """Open a game's watch page and read its real video prefix from the HTML."""
    num = game_id.split("-")[-1]
    try:
        page.goto(f"{S.BASE_URL}/traceid/athlete/{athlete_id}/watch/{num}",
                  wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)
        return prefix_from_html(page.content(), team_id, game_id)
    except Exception:
        return None

def resolve_masters(request, page, athlete_getter, team_id: str, game_id: str) -> list[str]:
    """Known-prefix master URLs; if none, fall back to reading the real prefix off
    the watch page (so brand-new path variants never silently fail).
    `athlete_getter` is a 0-arg callable returning the athlete id, called only on fallback."""
    masters = available_masters(request, team_id, game_id)
    if masters:
        return masters
    athlete_id = athlete_getter()
    if not athlete_id:
        return []
    prefix = prefix_via_watch(page, athlete_id, team_id, game_id)
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
    return out

def available_masters(request, team_id: str, game_id: str, max_halves: int = 2) -> list[str]:
    """Return the working master-playlist URLs for each half, in order.

    Empty list means the game has no downloadable game-camera video.
    """
    prefix = resolve_prefix(request, team_id, game_id)
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
