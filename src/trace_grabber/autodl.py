"""Automatic downloads: the on/off choice and which games it applies to.

Switching it on only covers games added from then on. A full game with its
highlights and player recaps is several gigabytes, so quietly fetching a whole
back catalogue would fill a disk; instead, the first time an account is looked
at, every game it already lists is remembered as "seen" and skipped for good.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FILE = "auto.json"


@dataclass
class AutoState:
    enabled: bool = False      # download new games (with highlights and recaps) by itself
    login: bool = False        # open TraceDown when the person logs in to the computer
    welcomed: bool = False     # the first-open questions have been answered
    seen: dict = field(default_factory=dict)   # account id -> game ids that were already there


def load(data_dir) -> AutoState:
    try:
        data = json.loads((Path(data_dir) / FILE).read_text(encoding="utf-8"))
        known = {k: data[k] for k in ("enabled", "login", "welcomed", "seen") if k in data}
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
