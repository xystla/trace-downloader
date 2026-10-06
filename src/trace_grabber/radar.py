"""Heat maps from Trace's player tracking ("radar") files.

Beside each half's video Trace keeps 'radar<half>_dynamic.json': where every
tracked person stood, twice a second, on a field measured 0-1000 each way. Some
of them are tied to a team and shirt number; those of our team (goalkeeper left
out) are counted into a grid, always turned so our team attacks to the right.
"""
import json
from pathlib import Path

COLS, ROWS = 30, 20
FIELD = 1000
KEEPER_ZONE = 150       # how near a goal line a goalkeeper stays, on average
KEEPER_SPREAD = 100     # and how little they move along the field
ANALYTICS_FOLDER = "Analytics"
HEAT_FILE = "heatmap.json"


def radar_url(master_url: str, half: int) -> str:
    """The tracking file for a half, from that half's video playlist address."""
    return f"{master_url.rsplit('/', 2)[0]}/radar{half}_dynamic.json"


def _spots(tracking: dict):
    """(athlete id, x, y) for every sighting in the file."""
    for frame in tracking.get("frm") or []:
        people = frame.get("a") if isinstance(frame, dict) else None
        if not isinstance(people, dict):
            continue
        for athlete_id, seen in people.items():
            where = seen.get("l") if isinstance(seen, dict) else None
            if isinstance(where, list) and len(where) >= 2:
                yield athlete_id, where[0], where[1]


def _mean(values):
    return sum(values) / len(values)


def _keeper(xs_by_player: dict):
    """(athlete id, x) of a team's goalkeeper, or None: the most-seen player who
    stays by one goal line. Trace's own 'goalie' label is often on someone else."""
    best = None
    for athlete_id, xs in xs_by_player.items():
        mean = _mean(xs)
        spread = (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5
        if (mean < KEEPER_ZONE or mean > FIELD - KEEPER_ZONE) and spread < KEEPER_SPREAD:
            if best is None or len(xs) > len(xs_by_player[best]):
                best = athlete_id
    return (best, _mean(xs_by_player[best])) if best else None


def heat(tracking: dict, team: str):
    """{"grid": ROWS rows of COLS counts, "samples", "players"} for one half,
    or None when the file tracks none of our outfield players."""
    athletes = (tracking.get("setup") or {}).get("athletes") or {}
    ours, theirs = {}, {}            # athlete id -> [(x, y)], named players only
    for athlete_id, x, y in _spots(tracking):
        who = athletes.get(athlete_id)
        if who:
            side = ours if who.get("team") == team else theirs
            side.setdefault(athlete_id, []).append((min(max(x, 0), FIELD), min(max(y, 0), FIELD)))
    xs = lambda side: {k: [x for x, _ in v] for k, v in side.items()}
    our_keeper, their_keeper = _keeper(xs(ours)), _keeper(xs(theirs))
    # We attack away from our own goalkeeper, towards theirs; failing both, away
    # from the end our players stand nearer to than the other team's.
    if our_keeper:
        right = our_keeper[1] < FIELD / 2
        ours.pop(our_keeper[0])
    elif their_keeper:
        right = their_keeper[1] > FIELD / 2
    elif ours and theirs:
        everyone = lambda side: _mean([x for v in side.values() for x, _ in v])
        right = everyone(ours) < everyone(theirs)
    else:
        right = True
    grid = [[0] * COLS for _ in range(ROWS)]
    samples = 0
    for spots in ours.values():
        for x, y in spots:
            if not right:
                x, y = FIELD - x, FIELD - y
            grid[min(ROWS - 1, int(y * ROWS / FIELD))][min(COLS - 1, int(x * COLS / FIELD))] += 1
            samples += 1
    if not samples:
        return None
    return {"grid": grid, "samples": samples, "players": len(ours)}


def build(halves: dict):
    """The saved form: each half and the two added together; None if there is nothing."""
    first, second = halves.get(1), halves.get(2)
    parts = [h for h in (first, second) if h]
    if not parts:
        return None
    whole = {"grid": [[sum(h["grid"][r][c] for h in parts) for c in range(COLS)] for r in range(ROWS)],
             "samples": sum(h["samples"] for h in parts),
             "players": max(h["players"] for h in parts)}
    return {"cols": COLS, "rows": ROWS, "whole": whole, "first": first, "second": second}


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if data.get("whole") else None
    except (OSError, ValueError, AttributeError):
        return None


def _write(folder: Path, name: str, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (name + ".part")
    part.write_text(json.dumps(data), encoding="utf-8")
    part.replace(folder / name)


def save(directory, game_number: int, data: dict, game_root=None) -> None:
    """Keep a game's heat map with the app's data, and with the game itself when
    it has a folder, so the videos folder carries it to another computer."""
    _write(Path(directory), f"{game_number}.json", data)
    copy_to_game(game_root, data)


def copy_to_game(game_root, data: dict) -> bool:
    """Put the heat map in '<game folder>/Analytics' if the game has a folder and
    doesn't hold one yet; returns whether it was written."""
    if not game_root or not Path(game_root).is_dir():
        return False
    folder = Path(game_root) / ANALYTICS_FOLDER
    if (folder / HEAT_FILE).exists():
        return False
    try:
        _write(folder, HEAT_FILE, data)
    except OSError:
        return False
    return True


def load(directory, game_number: int, game_root=None):
    found = _read(Path(directory) / f"{game_number}.json")
    if not found and game_root:
        found = _read(Path(game_root) / ANALYTICS_FOLDER / HEAT_FILE)
    return found
