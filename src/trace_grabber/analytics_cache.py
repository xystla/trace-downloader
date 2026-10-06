"""On-disk copy of each game's Trace moments, one JSON file per game.

Trace only serves moments for a plan-limited number of recent games, so a game's
stats are kept here the first time they load and reused once Trace stops
returning them.
"""
import json
from dataclasses import asdict
from pathlib import Path

from .analytics import GameMeta, compute_split


def save(directory, meta: GameMeta, moments: list[dict]) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{meta.game_id}.json").write_text(
        json.dumps({"meta": asdict(meta), "moments": moments}), encoding="utf-8")


def load(directory, game_id: int):
    """(meta, moments) for a saved game, or None if absent or unreadable."""
    try:
        data = json.loads((Path(directory) / f"{game_id}.json").read_text(encoding="utf-8"))
        return GameMeta(**data["meta"]), data["moments"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cached_ids(directory) -> set[int]:
    return {int(p.stem) for p in Path(directory).glob("*.json") if p.stem.isdigit()}


# Games Trace returned no stats for are not asked about again for a day: on a
# limited plan that is every older game, and re-asking each time is the bulk of
# the wait. A day later they are rechecked, so a plan upgrade is picked up.
EMPTY_RECHECK_SECS = 24 * 3600
_EMPTY_FILE = "_empty.json"


def _read_empty(directory) -> dict:
    try:
        return json.loads((Path(directory) / _EMPTY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_empty(directory, game_ids, now: float) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    checked = {**_read_empty(directory), **{str(g): now for g in game_ids}}
    (directory / _EMPTY_FILE).write_text(json.dumps(checked), encoding="utf-8")


def known_empty(directory, now: float) -> set[int]:
    return {int(g) for g, when in _read_empty(directory).items()
            if now - when <= EMPTY_RECHECK_SECS}


# Stats are only fetched in the background for someone who has opened the
# Analytics page at least once for this account.
_VIEWED_FILE = "_viewed"


def mark_viewed(directory) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / _VIEWED_FILE).touch()


def was_viewed(directory) -> bool:
    return (Path(directory) / _VIEWED_FILE).exists()


# A copy of each downloaded game's stats also lives in the game's own folder, so
# the videos folder can be moved to another computer and keep its stats.
ANALYTICS_FOLDER = "Analytics"
STATS_FILE = "stats.json"


def save_with_game(game_root, meta: GameMeta, moments: list[dict]) -> bool:
    """Write '<game folder>/Analytics/stats.json': the computed numbers (whole
    game and each half) for reading, plus the raw moments the app works from.
    Only for a game that already has a folder; returns whether it was written."""
    game_root = Path(game_root)
    if not game_root.is_dir():
        return False
    split = compute_split(moments, meta)
    data = {"meta": asdict(meta),
            "stats": {"whole": asdict(split.whole), "first": asdict(split.first),
                      "second": asdict(split.second)},
            "moments": moments}
    try:
        folder = game_root / ANALYTICS_FOLDER
        folder.mkdir(exist_ok=True)
        part = folder / (STATS_FILE + ".part")
        part.write_text(json.dumps(data, indent=1), encoding="utf-8")
        part.replace(folder / STATS_FILE)
    except OSError:
        return False
    return True


def load_file(path):
    """(meta, moments) from a stats file, or None if absent or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return GameMeta(**data["meta"]), data["moments"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def in_game_folders(videos_dir) -> dict[int, Path]:
    """{game id: stats file} for every game folder under videos_dir that has one."""
    found = {}
    for path in Path(videos_dir).glob(f"*/{ANALYTICS_FOLDER}/{STATS_FILE}"):
        loaded = load_file(path)
        if loaded:
            found[loaded[0].game_id] = path
    return found
