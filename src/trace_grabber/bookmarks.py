"""The person's own bookmarks in a game: a moment and an optional note.

They are kept in the game's folder ('Bookmarks/bookmarks.json'), so they travel
with the game. `t` is seconds into the game with both halves joined, the same
clock Trace times its moments on, so a bookmark means the same moment whether
the halves are saved as one file or two."""
import json
import secrets
from datetime import date
from pathlib import Path

FOLDER = "Bookmarks"
FILE = "bookmarks.json"
NOTE_MAX = 200


def _path(game_root) -> Path:
    return Path(game_root) / FOLDER / FILE


def _note(text) -> str:
    """One tidy line, kept short."""
    return " ".join(text.split())[:NOTE_MAX] if isinstance(text, str) else ""


def _half(value) -> int:
    return 2 if str(value) == "2" else 1


def load(game_root) -> list[dict]:
    """The game's bookmarks in match order. A missing or damaged file is no
    bookmarks; entries in it that aren't bookmarks are left out."""
    try:
        data = json.loads(_path(game_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    marks = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if isinstance(item.get("t"), bool) or not isinstance(item.get("t"), (int, float)):
            continue
        marks.append({"id": item["id"], "t": float(item["t"]), "half": _half(item.get("half")),
                      "note": _note(item.get("note")), "made": str(item.get("made") or "")})
    return sorted(marks, key=lambda mark: mark["t"])


def _save(game_root, marks: list[dict]) -> None:
    path = _path(game_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps(sorted(marks, key=lambda mark: mark["t"]), indent=1), encoding="utf-8")
    part.replace(path)


def add(game_root, t: float, half: int, note: str = "") -> dict:
    """Bookmark a moment; returns the new bookmark."""
    mark = {"id": secrets.token_hex(4), "t": round(float(t), 1), "half": _half(half),
            "note": _note(note), "made": date.today().isoformat()}
    _save(game_root, load(game_root) + [mark])
    return mark


def edit(game_root, bookmark_id: str, note: str) -> bool:
    """Change a bookmark's note; False when there is no such bookmark."""
    marks = load(game_root)
    found = [mark for mark in marks if mark["id"] == bookmark_id]
    for mark in found:
        mark["note"] = _note(note)
    if found:
        _save(game_root, marks)
    return bool(found)


def remove(game_root, bookmark_id: str) -> bool:
    """Delete a bookmark; False when there is no such bookmark."""
    marks = load(game_root)
    kept = [mark for mark in marks if mark["id"] != bookmark_id]
    if len(kept) != len(marks):
        _save(game_root, kept)
    return len(kept) != len(marks)
