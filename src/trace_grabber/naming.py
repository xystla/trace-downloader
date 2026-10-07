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

def combined_path(output_dir: Path, date: str, opponent: str | None, stem: str | None = None) -> Path:
    return _unique(output_dir, stem or _game_stem(date, opponent))

def half_path(output_dir: Path, date: str, half: int, opponent: str | None, stem: str | None = None) -> Path:
    """The one name a half has while its game is being downloaded in the app. A
    download that was cut off must find its earlier half again, so unlike
    build_path this never moves on to a '-2' name. `stem` is the person's own
    name for the video (see custom_stem); without it the built-in one is used."""
    return Path(output_dir) / f"{stem or _game_stem(date, opponent)}_half{half}.mp4"

_NOT_IN_NAMES = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
STEM_MAX = 120

def custom_stem(pattern: str | None, date: str, opponent: str | None, team: str | None) -> str | None:
    """The file name (without '.mp4') a pattern such as '{team} vs {opponent} {date}'
    gives a game's video, or None when there is no pattern or it leaves nothing,
    which means the built-in name. Characters no file name may hold become '-',
    so a pattern can't reach outside the game's folder, and '_half' and a
    closing '.part' are kept for the app's own use: that is how a half is told
    from a whole game, and an unfinished video from a finished one."""
    pattern = (pattern or "").strip()
    if not pattern:
        return None
    values = {"date": date or "", "team": team or "", "opponent": opponent or "Unknown opponent"}
    text = re.sub(r"\{(date|team|opponent)\}", lambda m: values[m.group(1)], pattern)
    text = re.sub(r"\s+", " ", _NOT_IN_NAMES.sub("-", text))
    text = re.sub(r"_(half)", r"-\1", text, flags=re.IGNORECASE)
    text = text.strip(" .-")[:STEM_MAX].strip(" .-")
    # '<name>.part.mp4' is how the app marks a video that isn't finished yet.
    return re.sub(r"\.(part)$", r"-\1", text, flags=re.IGNORECASE) or None

def _game_stem(date: str, opponent: str | None) -> str:
    parts = [date]
    if opponent:
        parts.append(f"vs-{_slug(opponent)}")
    return "_".join(parts)

FULL_GAME = "Full Game"
HIGHLIGHTS = "Highlights"
PLAYER_HIGHLIGHTS = "Player Highlights"
THUMBNAIL = "Thumbnail"
MY_CLIPS = "My Clips"

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

    @property
    def my_clips(self) -> Path:
        """Clips the person cut out of the game themselves."""
        return self.root / MY_CLIPS

def game_folders(output_dir: Path, date: str, opponent: str | None) -> GameFolders:
    stem = _game_stem(date, opponent)
    return GameFolders(Path(output_dir) / stem, Path(output_dir) / f"{stem}_highlights")

def saved_files(output_dir: Path, date: str, opponent: str | None) -> list[Path]:
    """Existing video files for a game: the combined file first, then the halves.
    Whatever video is in the game's own Full Game folder is the game's video,
    under any name (the person may name it, or rename it by hand). Loose in the
    team folder, where older versions saved it, it is known by its name."""
    order = lambda p: ("_half" in p.name, p.name)
    folder = game_folders(output_dir, date, opponent).full_game
    if folder.is_dir():
        found = [p for p in folder.glob("*.mp4")
                 if not p.name.startswith(".") and not p.name.endswith(".part.mp4")]
        if found:
            return sorted(found, key=order)
    name = re.compile(re.escape(_game_stem(date, opponent)) + r"(_half\d+)?(-\d+)?\.mp4")
    if Path(output_dir).is_dir():
        return sorted((p for p in Path(output_dir).iterdir() if name.fullmatch(p.name)), key=order)
    return []
