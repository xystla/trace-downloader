from dataclasses import dataclass, field
from pathlib import Path
import yaml

VALID_QUALITY = {"highest", "2000k", "1000k"}

@dataclass
class Config:
    output_dir: Path
    check_interval_hours: int
    quality: str
    team_urls: list[str] = field(default_factory=list)
    combine_halves: bool = True

def load_config(path: Path) -> Config:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    quality = data["quality"]
    if quality not in VALID_QUALITY:
        raise ValueError(f"quality must be one of {VALID_QUALITY}, got {quality!r}")
    # team_urls in config is vestigial — accounts.json is the source of truth.
    # It may be empty (fresh install) or absent.
    team_urls = data.get("team_urls") or []
    combine = bool(data.get("combine_halves", True))
    return Config(
        output_dir=Path(data["output_dir"]).expanduser(),
        check_interval_hours=int(data["check_interval_hours"]),
        quality=quality,
        team_urls=list(team_urls),
        combine_halves=combine,
    )
