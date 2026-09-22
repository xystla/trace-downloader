import html as _html
from html.parser import HTMLParser
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from .state import new_game_ids

@dataclass
class Game:
    id: str           # full game id, e.g. "demoteam1-1001"
    team_id: str      # e.g. "demoteam1"
    date: str         # ISO "YYYY-MM-DD", or "" if unparseable
    opponent: str | None
    title: str        # raw label, e.g. "Demo FC vs. Rovers"

# Match cards structurally: attribute/class order and nested labels can vary.
_POSTER_RE = re.compile(r'/teams/([a-z0-9]+)/games/([a-z0-9]+-\d+)/')

class _Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.card = None
        self.field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "a" and {"GameLink", "GameCard"} <= classes:
            self.card = {"title": "", "date": "", "poster": None}
        if self.card is None:
            return
        for value in attrs.values():
            match = _POSTER_RE.search(value or "")
            if match:
                self.card["poster"] = match.groups()
        if tag == "p":
            self.field = "title" if "label" in classes else "date" if "subtitle" in classes else None

    def handle_data(self, data):
        if self.card is not None and self.field:
            self.card[self.field] += data

    def handle_endtag(self, tag):
        if tag == "p":
            self.field = None
        if tag == "a" and self.card is not None:
            self.cards.append(self.card)
            self.card = None
            self.field = None

_DATE_HEAD = re.compile(r'([A-Z][a-z]+ \d{1,2}, \d{4})')

def _iso_date(text: str) -> str:
    m = _DATE_HEAD.match(text.strip())
    if not m:
        return ""
    # Trace uses full month names ("June 4, 2026"); accept abbreviated too.
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""

_TEAM_PATH_RE = re.compile(r'/traceid/team/([a-z0-9]+)')
_TEAM_HREF_RE = re.compile(r'href="(/traceid/team/[a-z0-9]+)"')

def team_paths(current_url: str, page_html: str) -> list[str]:
    """Team page paths to consider when adding an account. The current URL (the
    team the user has open) comes first — it's the reliable signal, since a team
    page doesn't link to itself — then any team links found on the page."""
    paths: list[str] = []
    m = _TEAM_PATH_RE.search(current_url or "")
    if m:
        paths.append(f"/traceid/team/{m.group(1)}")
    for href in _TEAM_HREF_RE.findall(page_html or ""):
        if href not in paths:
            paths.append(href)
    return paths

def parse_games(page_html: str) -> list[Game]:
    games: list[Game] = []
    seen: set[str] = set()
    parser = _Cards()
    parser.feed(page_html)
    for card in parser.cards:
        if not card["poster"]:
            continue
        team_id, gid = card["poster"]
        if gid in seen:
            continue
        seen.add(gid)
        title = card["title"].strip()
        date = _iso_date(card["date"])
        opponent = title.split(" vs. ", 1)[1].strip() if " vs. " in title else None
        games.append(Game(id=gid, team_id=team_id, date=date, opponent=opponent, title=title))
    return games

def _list_page_games(page: Page, team_url: str, max_games: int = 60, max_scrolls: int = 15) -> list[Game]:
    page.goto(team_url, wait_until="domcontentloaded")
    page.wait_for_selector("a.GameLink.GameCard", timeout=20000)
    seen = 0
    for _ in range(max_scrolls):
        cards = page.query_selector_all("a.GameLink.GameCard")
        if len(cards) >= max_games or len(cards) == seen:
            break
        seen = len(cards)
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(1200)
    games = parse_games(page.content())
    if not games:
        raise RuntimeError("The team page loaded, but its game cards could not be read.")
    return games[:max_games]

def _list_api_games(request, team_url, max_games):
    # Reuse the authenticated teamGames API already used by analytics when
    # Trace's rendered game cards are unavailable or have changed.
    from . import analytics
    slug = team_url.rstrip("/").rsplit("/", 1)[-1]
    team_id = analytics.team_numeric_id(request, slug)
    if not team_id:
        raise RuntimeError("This team was not found in your Trace account.")
    token = analytics.user_token(request)
    if not token.get("token"):
        raise RuntimeError("Trace did not return a session token. Reconnect your account.")
    rows = analytics.fetch_team_games(request, team_id, token)
    games = []
    for row in rows.values():
        if row.get("status") != "ready" or not (row.get("access") or {}).get("allowed"):
            continue
        side = analytics.our_side_for(row, team_id)
        if side is None:
            continue
        ours = row.get(side + "_team") or {}
        other = row.get("away_team" if side == "home" else "home_team") or {}
        opponent = other.get("title") or other.get("name") or ""
        games.append(Game(id=f"{slug}-{row['game_id']}", team_id=slug,
                          date=(row.get("full_date") or "")[:10], opponent=opponent,
                          title=(ours.get("title") or slug) + " vs. " + opponent))
    return sorted(games, key=lambda g: (g.date, int(g.id.rsplit("-", 1)[1])), reverse=True)[:max_games]


def list_games(page: Page, team_url: str, max_games: int = 60, max_scrolls: int = 15) -> list[Game]:
    try:
        return _list_page_games(page, team_url, max_games, max_scrolls)
    except Exception as page_error:
        try:
            return _list_api_games(page.context.request, team_url, max_games)
        except Exception as api_error:
            raise RuntimeError(
                f"Could not load games for {team_url}. "
                f"Team page: {page_error}. Trace API: {api_error}"
            ) from api_error


def list_new_games(page: Page, team_url: str, state_path: Path) -> list[Game]:
    games = list_games(page, team_url)
    fresh = set(new_game_ids([g.id for g in games], state_path))
    return [g for g in games if g.id in fresh]
