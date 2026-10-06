from datetime import date

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
