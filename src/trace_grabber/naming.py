import re
from dataclasses import dataclass
from pathlib import Path

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def _unique(output_dir: Path, base: str) -> Path:
    candidate = Path(output_dir) / f"{base}.mp4"
    n = 2
    while candidate.exists():
        candidate = Path(output_dir) / f"{base}-{n}.mp4"
        n += 1
    return candidate

def build_path(output_dir: Path, date: str, half: int, opponent: str | None) -> Path:
    parts = [date]
    if opponent:
        parts.append(f"vs-{_slug(opponent)}")
    parts.append(f"half{half}")
    return _unique(output_dir, "_".join(parts))

def combined_path(output_dir: Path, date: str, opponent: str | None) -> Path:
    parts = [date]
    if opponent:
        parts.append(f"vs-{_slug(opponent)}")
    return _unique(output_dir, "_".join(parts))

def _game_stem(date: str, opponent: str | None) -> str:
    parts = [date]
    if opponent:
        parts.append(f"vs-{_slug(opponent)}")
    return "_".join(parts)

FULL_GAME = "Full Game"
HIGHLIGHTS = "Highlights"
PLAYER_HIGHLIGHTS = "Player Highlights"
THUMBNAIL = "Thumbnail"

@dataclass(frozen=True)
class GameFolders:
    """Where one game's files live: a folder per game holding three folders."""
    root: Path                # <team folder>/<date>_vs-<opponent>
    legacy_highlights: Path   # '<game>_highlights' beside the videos, used before

    @property
    def full_game(self) -> Path:
        return self.root / FULL_GAME

    @property
    def highlights(self) -> Path:
        return self.root / HIGHLIGHTS

    @property
    def players(self) -> Path:
        return self.root / PLAYER_HIGHLIGHTS

    @property
    def thumbnail(self) -> Path:
        """The game's poster image, kept with the game so the folder is self-contained."""
        return self.root / THUMBNAIL / "thumbnail.jpg"

def game_folders(output_dir: Path, date: str, opponent: str | None) -> GameFolders:
    stem = _game_stem(date, opponent)
    return GameFolders(Path(output_dir) / stem, Path(output_dir) / f"{stem}_highlights")

def saved_files(output_dir: Path, date: str, opponent: str | None) -> list[Path]:
    """Existing video files for a game: the combined file first, then the halves.
    Looks in the game's Full Game folder, then loose in the team folder, where
    older versions saved them."""
    name = re.compile(re.escape(_game_stem(date, opponent)) + r"(_half\d+)?(-\d+)?\.mp4")
    for folder in (game_folders(output_dir, date, opponent).full_game, Path(output_dir)):
        if folder.is_dir():
            found = [p for p in folder.iterdir() if name.fullmatch(p.name)]
            if found:
                return sorted(found, key=lambda p: ("_half" in p.name, p.name))
    return []
