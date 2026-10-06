"""Cut a game's notable moments (shots, box entries) out of its downloaded video."""
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import combine, segments
from .tools import ffmpeg_path, part_path, subprocess_flags

PAD_SECS = 5        # shown before and after each moment
REEL_NAME = "Team Highlight Reel.mp4"   # every clip joined into one video
MAX_CLIP_SECS = 120


@dataclass
class Clip:
    half: int
    start: float    # seconds into that half's own video
    length: float
    label: str      # "shot" | "opp-shot" | "box-entry"


# Most notable first: an overlapping pair of moments is named for the earlier entry.
def _labels(our_side: str) -> list[tuple[str, str]]:
    them = "away" if our_side == "home" else "home"
    return [(f"{our_side}-shot", "shot"), (f"{them}-shot", "opp-shot"), (f"{them}-box", "box-entry")]


def pick(moments: list[dict], our_side: str) -> list[Clip]:
    """Clips for our shots, the opponent's shots and our box entries, in match
    order. Moments that overlap in time become a single clip."""
    labels = _labels(our_side)
    rank = {label: i for i, (_, label) in enumerate(labels)}
    # Trace times a moment as if both halves' videos were joined end to end, so a
    # second-half moment is placed by subtracting the first-half video's length.
    # (The second-half FullGameVideo's own `time` is wall-clock and not usable.)
    half_start = {1: 0}
    if half1_secs(moments) is not None:
        half_start[2] = half1_secs(moments)
    found = []
    for m in moments:
        keywords = m.get("keywords") or []
        label = next((label for kw, label in labels if kw in keywords), None)
        if label is None or m.get("time") is None or m.get("half") not in half_start:
            continue
        at = m["time"] - half_start[m["half"]]
        start = max(0, at - PAD_SECS)
        end = at + (m.get("duration") or 0) + PAD_SECS
        found.append((m["half"], start, end, label))
    clips: list[Clip] = []
    for half, start, end, label in sorted(found):
        last = clips[-1] if clips else None
        if last and last.half == half and start <= last.start + last.length:
            last.length = max(last.start + last.length, end) - last.start
            if rank[label] < rank[last.label]:
                last.label = label
        else:
            clips.append(Clip(half, start, end - start, label))
    for clip in clips:
        clip.length = min(clip.length, MAX_CLIP_SECS)
    return clips


def half1_secs(moments: list[dict]):
    """Length of the first-half video, needed to find second-half moments in a
    combined file. None when Trace didn't say."""
    for m in moments:
        if m.get("type") == "FullGameVideo" and m.get("half") == 1 and m.get("duration"):
            return m["duration"]
    return None


def source_for(clip: Clip, files: list[Path], half1):
    """(video file, seconds into it) to cut this clip from, or None if unknown."""
    for f in files:
        if f"_half{clip.half}" in Path(f).name:
            return f, clip.start
    combined = [f for f in files if "_half" not in Path(f).name]
    if not combined:
        return None
    if clip.half == 1:
        return combined[0], clip.start
    if half1 is None:
        return None
    return combined[0], half1 + clip.start


def clip_name(index: int, clip: Clip) -> str:
    minutes, seconds = divmod(int(clip.start), 60)
    return f"{index:02d}_half{clip.half}_{minutes:02d}m{seconds:02d}s_{clip.label}.mp4"


def build_cut_cmd(source, start: float, length: float, dest) -> list[str]:
    # Stream copy: fast and lossless. The cut lands on the nearest keyframe, which
    # the padding around each moment absorbs.
    return ["ffmpeg", "-y", "-ss", f"{start:g}", "-i", str(source), "-t", f"{length:g}",
            "-c", "copy", "-avoid_negative_ts", "make_zero", str(dest)]


def clip_count(folder) -> int:
    """Team clips in a folder (named by clip_name); other videos there don't count."""
    return len(_clips(folder))


def _clips(folder) -> list[Path]:
    """Finished team clips in match order ('.part.mp4' ones are still being cut)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("[0-9][0-9]_half*.mp4")
                  if not p.name.endswith(".part.mp4"))


def build_reel(folder):
    """Join a folder's clips, in match order, into one 'Team Highlight Reel' video
    there. Returns its path, or None when there are no clips or joining failed —
    never raises, because the clips themselves are already safely saved."""
    clips = _clips(folder)
    if not clips:
        return None
    reel = Path(folder) / REEL_NAME
    if reel.exists():
        return reel
    try:
        combine.combine(clips, reel)
    except Exception:
        return None
    return reel


def export(moments: list[dict], our_side: str, files: list[Path], folder):
    """Cut every highlight out of the game's video files into `folder`.
    Returns (folder, clips written), or (None, 0) when there was nothing to cut."""
    folder = Path(folder)
    files = [Path(f) for f in files]
    half1 = half1_secs(moments)
    jobs = [(clip, source_for(clip, files, half1)) for clip in pick(moments, our_side)]
    jobs = [(clip, source) for clip, source in jobs if source]
    if not jobs:
        return None, 0
    folder.mkdir(parents=True, exist_ok=True)
    # Cut every clip under a temporary name and only rename them once the whole
    # set is done, so an interrupted run never looks like finished highlights.
    cut = []
    for index, (clip, (source, start)) in enumerate(jobs, 1):
        dest = folder / clip_name(index, clip)
        part = part_path(dest)
        cmd = build_cut_cmd(source, start, clip.length, part)
        cmd[0] = ffmpeg_path()
        result = subprocess.run(cmd, capture_output=True, text=True, **subprocess_flags())
        if result.returncode == 0 and part.exists() and part.stat().st_size > 0:
            cut.append((part, dest))
        else:
            part.unlink(missing_ok=True)
    for part, dest in cut:
        part.replace(dest)
    return folder, len(cut)


def export_remote(moments: list[dict], our_side: str, playlists: dict, folder,
                  on_progress=None, on_proc=None, should_stop=None):
    """Fetch every highlight straight from Trace into `folder`, without the full
    game: each clip is just the run of short pieces that covers its moment.

    playlists maps a half (1, 2) to that half's pieces from segments.parse().
    on_progress(done, total) follows the clips; should_stop() ends it early, in
    which case nothing is kept. Returns (folder, clips written) or (None, 0)."""
    folder = Path(folder)
    jobs = []
    for clip in pick(moments, our_side):
        urls = segments.window(playlists.get(clip.half) or [], clip.start, clip.length)
        if urls:
            jobs.append((clip, urls))
    if not jobs:
        return None, 0
    folder.mkdir(parents=True, exist_ok=True)
    report = on_progress or (lambda done, total: None)
    fetched = []
    stopped = False
    for index, (clip, urls) in enumerate(jobs, 1):
        if should_stop is not None and should_stop():
            stopped = True
            break
        report(index - 1, len(jobs))
        dest = folder / clip_name(index, clip)
        part = part_path(dest)
        try:
            segments.download(urls, part, total_secs=clip.length, on_proc=on_proc)
            fetched.append((part, dest))
        except Exception:
            part.unlink(missing_ok=True)
    if stopped or (should_stop is not None and should_stop()):
        for part, _ in fetched:
            part.unlink(missing_ok=True)
        return folder, 0
    # As with local cutting, clips take their real names only once the set is done.
    for part, dest in fetched:
        part.replace(dest)
    report(len(jobs), len(jobs))
    return folder, len(fetched)


def timeline(moments: list[dict], our_side: str) -> dict:
    """The game's key moments on one clock, for a timeline and "jump to" list:
    {'duration': whole video seconds, 'half1': first-half video seconds,
     'moments': [{'t', 'half', 'label', 'len'}]}. `t` is seconds into the game
    video with both halves joined, which is how Trace times its moments. Empty
    for stats saved before those times were kept."""
    labels = _labels(our_side) + [(f"{our_side}-box", "opp-box-entry")]
    items = []
    for m in moments:
        keywords = m.get("keywords") or []
        label = next((label for kw, label in labels if kw in keywords), None)
        if label is None or m.get("time") is None:
            continue
        items.append({"t": round(m["time"], 1), "half": m.get("half"), "label": label,
                      "len": round(m.get("duration") or 0, 1)})
    items.sort(key=lambda item: item["t"])
    kept: list[dict] = []
    for item in items:      # Trace often tags one event twice, a second or two apart
        if not any(k["label"] == item["label"] and item["t"] - k["t"] <= 5 for k in kept[-3:]):
            kept.append(item)
    full = [m.get("duration") or 0 for m in moments if m.get("type") == "FullGameVideo"]
    return {"duration": sum(full) or None, "half1": half1_secs(moments), "moments": kept}


_CLIP_WORDS = {"shot": "Shot", "opp-shot": "Opponent shot", "box-entry": "Box entry"}


def clip_label(name: str) -> str:
    """'02_half2_01m35s_opp-shot.mp4' -> 'Opponent shot · 2nd half 1:35'."""
    m = re.fullmatch(r"\d+_half(\d)_(\d+)m(\d+)s_(.+)\.mp4", name)
    if not m:
        return Path(name).stem
    half = {"1": "1st half", "2": "2nd half"}.get(m.group(1), f"half {m.group(1)}")
    return f"{_CLIP_WORDS.get(m.group(4), m.group(4))} · {half} {int(m.group(2))}:{m.group(3)}"


def clip_place(name: str):
    """(half, seconds into that half) where a clip starts, read from its file
    name; (None, None) for anything that isn't a clip."""
    m = re.fullmatch(r"\d+_half(\d)_(\d+)m(\d+)s_.+\.mp4", name)
    return (int(m.group(1)), int(m.group(2)) * 60 + int(m.group(3))) if m else (None, None)


def saved_clips(folder) -> list[Path]:
    """Finished team clips in a folder, in match order."""
    return _clips(folder)
