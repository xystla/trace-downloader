"""Videos the person pointed the app at after moving them: for each game, where
its full-game file (or halves) is now. The files are left where they are; if one
can't be reached (a drive that isn't connected) the place is still remembered."""
import json
from pathlib import Path


def load(path) -> dict[str, list[str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {game_id: [f for f in files if isinstance(f, str)]
            for game_id, files in data.items() if isinstance(files, list)}


def _save(path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps(data, indent=1), encoding="utf-8")
    part.replace(path)


def remember(path, game_id: str, files) -> None:
    data = load(path)
    data[game_id] = [str(f) for f in files]
    _save(path, data)


def forget(path, game_id: str) -> None:
    data = load(path)
    if data.pop(game_id, None) is not None:
        _save(path, data)


def existing(path, game_id: str) -> list[Path]:
    """The game's found files that can be reached right now: a whole game first,
    then halves, the order the rest of the app expects."""
    files = [Path(f) for f in load(path).get(game_id, [])]
    return sorted((f for f in files if f.is_file()), key=lambda f: ("_half" in f.name, f.name))
