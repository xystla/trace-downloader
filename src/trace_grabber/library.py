"""What the saved games take on disk, and what removing one covers.

Nothing here deletes anything: targets() only says which files and folders a
removal is about, and the caller hands them to the Trash."""
from pathlib import Path


def size_of(path) -> int:
    """Bytes a file or a whole folder takes; 0 for something that isn't there."""
    path = Path(path)
    try:
        if path.is_file():
            return path.stat().st_size
        files = [p for p in path.rglob("*")] if path.is_dir() else []
    except OSError:
        return 0
    total = 0
    for p in files:
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass                    # gone or unreadable while we looked: it takes no space we can count
    return total


def inside(path, root) -> bool:
    """Is `path` really within `root`? Resolved first, so a path that climbs out
    with '..' or through a link does not count as inside."""
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except OSError:
        return False


def usage(folders, videos, root) -> dict:
    """Bytes one game takes in the library `root`, by kind. `videos` are its
    full-game files; one the person found elsewhere is outside the library, so
    it is not counted (and `elsewhere` says so)."""
    mine = [Path(v) for v in videos if inside(v, root)]
    loose = [v for v in mine if not inside(v, folders.root)]       # an older version saved it beside the folders
    pieces = folders.full_game.glob(".*.pieces") if folders.full_game.is_dir() else []
    return {
        "full": sum(size_of(v) for v in mine),
        "highlights": size_of(folders.highlights) + size_of(folders.legacy_highlights),
        "recaps": size_of(folders.players),
        "mine": size_of(folders.my_clips),
        "unfinished": sum(size_of(p) for p in pieces),
        "total": size_of(folders.root) + size_of(folders.legacy_highlights) + sum(size_of(v) for v in loose),
        "elsewhere": len(mine) < len(list(videos)),
    }


def targets(folders, videos, root, everything: bool) -> list[Path]:
    """What removing a game moves to the Trash. Just the full game: its Full Game
    folder (the video, and anything unfinished in it) and a loose older video.
    Everything: the game's whole folder, its older highlights folder and that
    loose video. A video outside the library is never among them."""
    loose = [Path(v) for v in videos if inside(v, root) and not inside(v, folders.root)]
    if everything:
        wanted = [folders.root, folders.legacy_highlights]
    else:
        wanted = [folders.full_game]
    found = [p for p in wanted if p.exists()] + loose
    # The last check before the Trash. Whatever the game's date and opponent
    # made of its folder, a removal covers things *within* the team's folder,
    # never that folder itself or anything above or beside it.
    here = Path(root).resolve()
    for path in [folders.root] + found:      # the game's own folder too: a game with no usable date has none
        if path.resolve() == here or not inside(path, root):
            raise ValueError(f"{path} is outside the games folder")
    return found
