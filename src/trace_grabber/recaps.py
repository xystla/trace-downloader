"""Trace's per-player "PlayerCam recap" videos: who has one for a game, and saving it."""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import analytics, segments

RECAPS_URL = "https://go.traceup.com/recaps/v5"
SEGMENT_SECS = 2   # Trace cuts recap video into 2-second segments

# With a game_id, teamMembers returns that game's roster (game_player_id set).
MEMBERS_Q = ("query getTeamMembers($team_hash: String!, $game_id: Int, $token: UserToken!, "
             "$include_all: Boolean) { teamMembers(team_hash: $team_hash game_id: $game_id "
             "token: $token include_all: $include_all) { is_player jersey_number game_player_id "
             "user_id user { user_id name is_dummy } } }")


@dataclass
class Player:
    user_id: int
    number: str   # shirt number as Trace has it; "" when unknown
    name: str     # "" for Trace's placeholder players


def players_from(members: list[dict]) -> list[Player]:
    """The players who took part in the game, in shirt-number order (unknown last)."""
    players = []
    for m in members:
        if not (m.get("is_player") and m.get("game_player_id")):
            continue
        user = m.get("user") or {}
        name = "" if user.get("is_dummy") else (user.get("name") or "").strip()
        if re.match(r"dummy[\s_-]*tracer", name, re.IGNORECASE):
            name = ""   # Trace's stand-in for a player with no account
        players.append(Player(m["user_id"], (m.get("jersey_number") or "").strip(), name))
    return sorted(players, key=lambda p: (not p.number.isdigit(),
                                          int(p.number) if p.number.isdigit() else 0, p.user_id))


def game_players(request, team_slug: str, game_num: int, token: dict) -> list[Player]:
    data = analytics.graphql(request, MEMBERS_Q, {"team_hash": team_slug, "game_id": game_num,
                                                  "token": token, "include_all": True})
    return players_from(data.get("teamMembers") or [])


def recap_url(player_user_id: int, game_num: int, today: str) -> str:
    return (f"{RECAPS_URL}?recap_type=last_games&recap_value=1&players={player_user_id}"
            f"&events=pt&date_from={today}&exclude_highlight_ids=&game_ids={game_num}")


def best_stream(recap: dict):
    """Playlist text of the highest-quality stream, or None when there is no recap."""
    streams = (recap.get("hls") or {}).get("streams") or []
    if not streams:
        return None
    return max(streams, key=lambda s: int(re.sub(r"\D", "", s.get("level") or "") or 0))["data"]


def segment_urls(playlist: str) -> list[str]:
    return [line.strip() for line in playlist.splitlines()
            if line.strip() and not line.startswith("#")]


def fetch_segments(request, player_user_id: int, game_num: int) -> list[str]:
    """Video segment URLs of a player's recap, in order ([] when Trace has none)."""
    resp = request.get(recap_url(player_user_id, game_num, date.today().isoformat()), timeout=30000)
    playlist = best_stream(resp.json()) if resp.ok else None
    return segment_urls(playlist) if playlist else []


def recap_name(player: Player) -> str:
    parts = ["player"]
    if player.number:
        parts.append(player.number.zfill(2))
    if player.name:
        parts.append(re.sub(r"[^a-z0-9]+", "-", player.name.lower()).strip("-"))
    if len(parts) == 1:
        parts.append(str(player.user_id))
    return "-".join(parts) + ".mp4"


def download(urls: list[str], dest, progress_cb=None, on_proc=None) -> None:
    """Join the recap's segments end to end into dest (raises on failure).

    The recap is many short cuts from different points of the game; joining them
    one after another gives a continuous video, where playing Trace's playlist
    as-is leaves a frozen gap at every cut."""
    segments.download(urls, dest, total_secs=len(urls) * SEGMENT_SECS,
                      progress_cb=progress_cb, on_proc=on_proc)


def recap_label(name: str) -> str:
    """'player-07-sage-s.mp4' -> '#7 Sage S'; 'player-10.mp4' -> '#10'."""
    parts = Path(name).stem.split("-")[1:]
    number = parts.pop(0).lstrip("0") or "0" if parts and parts[0].isdigit() else ""
    words = " ".join(w.capitalize() for w in parts)
    return " ".join(x for x in ("#" + number if number else "", words) if x) or "Player"
