import json
from pathlib import Path

def load_state(path: Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")))

def mark_done(path: Path, game_id: str) -> None:
    done = load_state(path)
    done.add(game_id)
    Path(path).write_text(json.dumps(sorted(done), indent=2))

def new_game_ids(game_ids: list[str], path: Path) -> list[str]:
    done = load_state(path)
    return [g for g in game_ids if g not in done]
