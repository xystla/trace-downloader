"""Automatic downloads: the on/off choice and which games it applies to.

Switching it on only covers games added from then on. A full game with its
highlights and player recaps is several gigabytes, so quietly fetching a whole
back catalogue would fill a disk; instead, the first time an account is looked
at, every game it already lists is remembered as "seen" and skipped for good.
"""
import json
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path

FILE = "auto.json"


GIVE_UP_DAYS = 3     # how long a game with nothing ready on Trace is tried again


@dataclass
class AutoState:
    enabled: bool = False      # download new games by itself
    login: bool = False        # open TraceDown when the person logs in to the computer
    welcomed: bool = False     # the first-open questions have been answered
    seen: dict = field(default_factory=dict)   # account id -> game ids that were already there
    full: bool = True          # what it fetches for a new game: the full game…
    highlights: bool = True    # …its highlights and reel…
    recaps: bool = True        # …and each player's recap
    tried: dict = field(default_factory=dict)  # game id -> first day it was tried without the full game
    low_disk: bool = False     # the "not enough disk space" notification has been sent
    expired_notified: bool = False   # the "login has expired" notification has been sent


def load(data_dir) -> AutoState:
    try:
        data = json.loads((Path(data_dir) / FILE).read_text(encoding="utf-8"))
        known = {f.name: data[f.name] for f in fields(AutoState) if f.name in data}
        return AutoState(**known)
    except (OSError, ValueError, TypeError):
        return AutoState()


def save(data_dir, state: AutoState) -> None:
    path = Path(data_dir) / FILE
    part = path.with_suffix(".part")
    part.write_text(json.dumps(asdict(state), indent=1), encoding="utf-8")
    part.replace(path)


def pending(state: AutoState, account_id: str, games: list, done: set) -> list:
    """The games automatic downloading should fetch now, newest first as listed.
    The first call for an account records its current games as seen and returns
    nothing; the caller saves the state afterwards."""
    if account_id not in state.seen:
        state.seen[account_id] = sorted(g.id for g in games if g.id not in done)
        return []
    if not state.enabled:
        return []
    seen = set(state.seen[account_id])
    return [g for g in games if g.id not in done and g.id not in seen]


def settle(state: AutoState, account_id: str, game_id: str, got: bool, today: date) -> bool:
    """Record how an automatic fetch went for a game whose full video isn't wanted
    (the full video marks a game done by itself). Once something was saved, or
    Trace has had nothing for GIVE_UP_DAYS, the game counts as seen and is left
    alone; until then it is tried again. Returns whether it is finished with."""
    first = state.tried.setdefault(game_id, today.isoformat())
    if not got and (today - date.fromisoformat(first)).days < GIVE_UP_DAYS:
        return False
    state.tried.pop(game_id, None)
    state.seen[account_id] = sorted(set(state.seen.get(account_id, [])) | {game_id})
    return True
