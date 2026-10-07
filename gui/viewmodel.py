from datetime import date, datetime, timedelta

from trace_grabber.games import Game

def connection_state(has_account: bool, logged_in: bool) -> str:
    """Header connection state for the UI.

    Three states, not two: a fresh install with no account is "none" (prompt to
    connect), distinct from an added account whose session lapsed ("expired",
    which is what Reconnect is for). Collapsing them made new users see
    "Session expired" + a Reconnect button that can never succeed.
    """
    if not has_account:
        return "none"
    return "ok" if logged_in else "expired"

def date_label(raw: str) -> str:
    """'2026-10-03' -> 'October 3, 2026'; anything unparseable is shown as-is."""
    try:
        d = date.fromisoformat(raw[:10])
    except (TypeError, ValueError):
        return raw
    return f"{d:%B} {d.day}, {d.year}"

def score_view(game: Game):
    """{'us', 'them', 'result'} for a game with a score entered on Trace, else None."""
    us, them = game.score_us, game.score_them
    if us is None or them is None:
        return None
    return {"us": us, "them": them,
            "result": "win" if us > them else "loss" if us < them else "draw"}

def game_view(game: Game, downloaded_ids: set[str]) -> dict:
    return {
        "id": game.id,
        "team_id": game.team_id,
        "date": game.date,
        "date_label": date_label(game.date),
        "opponent": game.opponent or "",
        "title": game.title,
        "state": "saved" if game.id in downloaded_ids else "new",
        "thumb": None,
        "score": score_view(game),
    }

def games_view(games: list[Game], downloaded_ids: set[str]) -> list[dict]:
    return [game_view(g, downloaded_ids) for g in games]


def tray_status(now: datetime, downloading, checking: bool, expired: bool, last) -> str:
    """The line at the top of the tray menu: what the app is doing right now, else
    how the last check for new games went, else nothing. `downloading` is
    (game name, percent) or None; `last` is (when, games saved) or None."""
    if downloading:
        return f"Downloading {downloading[0]} · {int(downloading[1])}%"
    if checking:
        return "Checking for new games…"
    if expired:
        return "Trace login expired · reconnect to keep downloading"
    if not last:
        return ""
    when, saved = last
    clock = when.strftime("%I:%M %p").lstrip("0")
    if when.date() == now.date():
        day = "today"
    elif when.date() == now.date() - timedelta(days=1):
        day = "yesterday"
    else:
        day = f"{when:%b} {when.day}"
    found = "no new games" if not saved else f"{saved} new game{'' if saved == 1 else 's'} saved"
    return f"Last checked {day} at {clock} · {found}"
