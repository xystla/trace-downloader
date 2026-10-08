"""A game's edit: who played, how the score bug looks, and the marks that say where the game starts,
pauses, resumes and ends and where each goal was scored.

Kept in the game's folder ('Edit/edit.json'). Marks are timed on the game clock
(seconds with both halves joined), like bookmarks. The rules here turn marks
into the stretches of play that are kept, the time the score bug's clock shows,
and what is wrong when the marks don't make sense."""
import json
import math
import re
import secrets
from pathlib import Path

from . import scorebug

FOLDER = "Edit"
FILE = "edit.json"
KINDS = ("start", "break", "resume", "goal_home", "goal_away", "end")
MIN_PERIOD = 2.0        # seconds: shorter than this there is nothing to fade in and out of
COLORS = {"home": "#16a05a", "away": "#1e5ac8"}
CODES = {"home": "HOM", "away": "AWY"}


def clock_text(seconds: float) -> str:
    """What the score bug's clock reads: 754.9 -> '12:34'."""
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _when(t: float) -> str:
    """A moment of the recording as people say it: 1870 -> '31:10'."""
    s = max(0, int(t))
    return f"{s // 60}:{s % 60:02d}"


def code_from(name, fallback: str) -> str:
    """The first three letters or digits of a team's name, or the fallback."""
    return re.sub(r"[^A-Za-z0-9]", "", name or "")[:3].upper() or fallback


def _team(team, side: str) -> dict:
    team = team if isinstance(team, dict) else {}
    name = " ".join(team["name"].split())[:40] if isinstance(team.get("name"), str) else ""
    code = " ".join(team["code"].split())[:40].strip().upper() if isinstance(team.get("code"), str) else ""
    color = team.get("color")
    color = color.lower() if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else COLORS[side]
    return {"name": name, "code": code or code_from(name, CODES[side]), "color": color}


GRADE = ("exposure", "contrast", "saturation")      # each from -100 to 100; 0 leaves the picture alone
SHARPEN = "sharpen"                                 # from 0 (as it is) to 100


def _grade(grade) -> dict:
    grade = grade if isinstance(grade, dict) else {}

    def one(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return 0
        return int(min(100, max(-100, round(value))))

    return {**{key: one(grade.get(key)) for key in GRADE}, SHARPEN: max(0, one(grade.get(SHARPEN)))}


def clean(project) -> dict:
    """A project as the app keeps it, whatever was handed in: tidy teams, and
    only marks that are marks, in order."""
    project = project if isinstance(project, dict) else {}
    marks = []
    for m in project.get("marks") if isinstance(project.get("marks"), list) else []:
        if not isinstance(m, dict) or m.get("kind") not in KINDS:
            continue
        t = m.get("t")
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            continue
        mark_id = m["id"] if isinstance(m.get("id"), str) and m["id"] else secrets.token_hex(4)
        marks.append({"id": mark_id, "kind": m["kind"], "t": round(float(t), 3)})
    return {"home": _team(project.get("home"), "home"), "away": _team(project.get("away"), "away"),
            "bug": scorebug.style(project.get("bug")), "grade": _grade(project.get("grade")),
            "marks": sorted(marks, key=lambda m: m["t"])}


def default_project(home_name, away_name, remembered=None, bug=None) -> dict:
    """A new edit: the person's team and the bug's look (as they set them up
    last time, if they did) against the opponent, with no marks yet."""
    home = remembered if isinstance(remembered, dict) else {"name": home_name or ""}
    return clean({"home": home, "away": {"name": away_name or ""}, "bug": bug, "marks": []})


def _path(game_root) -> Path:
    return Path(game_root) / FOLDER / FILE


def load(game_root) -> dict | None:
    """The game's saved edit, or None when there is none (or it can't be read)."""
    try:
        return clean(json.loads(_path(game_root).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save(game_root, project) -> dict:
    """Keep the edit (tidied first); returns what was kept."""
    kept = clean(project)
    path = _path(game_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    part.replace(path)
    return kept


def outline(marks) -> tuple[list[tuple[float, float]], list[str]]:
    """(stretches of play, problems). The marks must read: the game starts, then
    any number of breaks each followed by play resuming, then the game ends.
    With no problems the stretches are what the export keeps; with problems
    they are as far as the marks could be followed."""
    marks = sorted(marks, key=lambda m: m["t"])
    problems = []
    starts = [m["t"] for m in marks if m["kind"] == "start"]
    ends = [m["t"] for m in marks if m["kind"] == "end"]
    if not starts:
        problems.append("Mark where the game starts.")
    if len(starts) > 1:
        problems.append("There is more than one 'Game starts' mark.")
    if not ends:
        problems.append("Mark where the game ends.")
    if len(ends) > 1:
        problems.append("There is more than one 'Game ends' mark.")
    if problems:
        return [], problems
    start, end = starts[0], ends[0]
    if end <= start:
        return [], ["The game ends before it starts."]
    segments = []
    playing, since = True, start
    for m in marks:
        kind, t = m["kind"], m["t"]
        if kind in ("start", "end"):
            continue
        if t < start:
            problems.append(f"The mark at {_when(t)} is before the game starts.")
        elif t > end:
            problems.append(f"The mark at {_when(t)} is after the game ends.")
        elif kind == "break":
            if playing:
                segments.append((since, t))
                playing = False
            else:
                problems.append(f"There are two breaks in a row at {_when(t)}. Add 'Play resumes' between them.")
        elif kind == "resume":
            if playing:
                problems.append(f"'Play resumes' at {_when(t)} has no break before it.")
            else:
                playing, since = True, t
    if playing:
        segments.append((since, end))
    else:
        problems.append("The game ends during a break. Add 'Play resumes' or remove the last break.")
    for a, b in segments:
        if b - a < MIN_PERIOD:
            problems.append(f"The period starting at {_when(a)} is too short.")
    for m in marks:
        if m["kind"].startswith("goal") and start <= m["t"] <= end and out_time(segments, m["t"]) is None:
            problems.append(f"The goal at {_when(m['t'])} is inside a break.")
    return segments, problems


def out_time(segments, t: float) -> float | None:
    """Where a moment of the recording falls in the exported game, which is also
    what the clock shows then; None when that moment isn't kept."""
    before = 0.0
    for a, b in segments:
        if a <= t <= b:
            return before + (t - a)
        before += b - a
    return None


def play_length(segments) -> float:
    return sum(b - a for a, b in segments)


def score_changes(marks, segments) -> list[tuple[float, int, int]]:
    """(output time, home, away) from 0-0 on, one entry for each goal in play."""
    changes = [(0.0, 0, 0)]
    home = away = 0
    for m in sorted(marks, key=lambda m: m["t"]):
        if not m["kind"].startswith("goal"):
            continue
        at = out_time(segments, m["t"])
        if at is None:
            continue
        home, away = home + (m["kind"] == "goal_home"), away + (m["kind"] == "goal_away")
        changes.append((at, home, away))
    return changes
