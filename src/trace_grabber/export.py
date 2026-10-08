"""Export an edited game: the stretches of play joined, a fade at each break, and
the score bug with its running clock burned in.

One ffmpeg command does it. Each stretch is read with a seek, faded where it
meets a break, and joined; the bug's plate for the current score is laid over
the result, and the clock's digits are written on top from the output's own
time, which is exactly the play time because the breaks are gone."""
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import edit, scorebug
from .progress import parse_out_time, percent
from .tools import complete_or_nothing, ffmpeg_path, subprocess_flags

FADE = 0.5      # seconds of fade out before a break and fade in after it
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Piece:
    """A run of one video file that goes into the export."""
    path: Path
    start: float        # seconds into that file
    length: float
    fade_in: bool       # it begins after a break
    fade_out: bool      # it ends at a break


def video_info(path) -> dict:
    """What the export needs to know about a video: its length, size, frame rate,
    overall bitrate (kbit/s, None if not stated) and whether it has sound."""
    said = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, **subprocess_flags()).stderr
    length = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", said)
    size = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})[ ,\[]", said)
    if not length or not size:
        raise RuntimeError("That video couldn't be read.")
    rate = re.search(r"bitrate: (\d+) kb/s", said)
    frames = re.search(r"Video:.*?, (\d+(?:\.\d+)?) fps", said)
    hours, minutes, seconds = length.groups()
    return {"duration": round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3),
            "width": int(size.group(1)), "height": int(size.group(2)),
            "bitrate": int(rate.group(1)) if rate else None, "audio": "Audio:" in said,
            "fps": float(frames.group(1)) if frames else 30.0}


def pieces(segments, files) -> list[Piece]:
    """The stretches of play (on the game clock) as runs of the video files.
    `files` is [(path, length)] in game order: one file, or the two halves. A
    stretch that crosses from one file into the next becomes two pieces with no
    fade between them; fades belong only where a break was cut out."""
    made = []
    for n, (a, b) in enumerate(segments):
        runs, offset = [], 0.0
        for path, length in files:
            lo, hi = max(a, offset), min(b, offset + length)
            if hi - lo > 0.01:
                runs.append((Path(path), lo - offset, hi - lo))
            offset += length
        for i, (path, start, length) in enumerate(runs):
            made.append(Piece(path, start, length,
                              fade_in=n > 0 and i == 0,
                              fade_out=n < len(segments) - 1 and i == len(runs) - 1))
    return made


def _clock(lay: dict, font: str) -> list[str]:
    """Five drawtext filters, one for each glyph of MM:SS in its own slot."""
    clock = lay["clock"]
    glyphs = [r"%{eif\:floor(t/600)\:d}", r"%{eif\:mod(floor(t/60)\,10)\:d}", r"\:",
              r"%{eif\:floor(mod(t\,60)/10)\:d}", r"%{eif\:mod(floor(t)\,10)\:d}"]
    return [f"drawtext=fontfile={font}:text='{glyph}':x={lay['x'] + slot}-text_w/2:y={lay['y'] + clock['y']}-text_h/2"
            f":fontsize={clock['size']}:fontcolor=0x{clock['color'][1:]}"
            for glyph, slot in zip(glyphs, clock["slots"])]


def filter_script(pieces, plates, lay: dict, font: str, size=(1920, 1080), fps: float = 30.0,
                  audio: bool = True) -> str:
    """The filter graph. Inputs 0..n-1 are the pieces; after them come the
    plates, `plates` being [(file name, from, to)] in output time. Every piece
    is first brought to one frame rate, size and pixel format: two half files
    that differ in any of them would otherwise not join (a differing frame rate
    makes ffmpeg write frames without end)."""
    lines = []
    same = [f"fps={fps:g}", f"scale={size[0]}:{size[1]}", "format=yuv420p", "setsar=1"]
    for i, piece in enumerate(pieces):
        video, sound = list(same), []
        if piece.fade_in:
            video.append(f"fade=t=in:st=0:d={FADE}")
            sound.append(f"afade=t=in:st=0:d={FADE}")
        if piece.fade_out:
            at = max(0.0, piece.length - FADE)
            video.append(f"fade=t=out:st={at:.3f}:d={FADE}")
            sound.append(f"afade=t=out:st={at:.3f}:d={FADE}")
        lines.append(f"[{i}:v]{','.join(video)}[v{i}]")
        if audio:
            lines.append(f"[{i}:a]{','.join(sound) or 'anull'}[a{i}]")
    n = len(pieces)
    if audio:
        lines.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]")
    else:
        lines.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cv]")
    last = "cv"
    for k, (_, since, until) in enumerate(plates):
        lines.append(f"[{last}][{n + k}:v]overlay={lay['x']}:{lay['y']}"
                     f":enable='between(t,{since:.3f},{until:.3f})'[o{k}]")
        last = f"o{k}"
    lines.append(f"[{last}]" + ",".join(_clock(lay, font)) + "[out]")
    return ";\n".join(lines) + "\n"


def build_cmd(pieces, plate_names, dest, quality: str, bitrate=None, audio: bool = True) -> list[str]:
    """The ffmpeg command, to be run in the folder holding graph.txt, the
    plates and the typeface (so none of their names needs escaping)."""
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    for piece in pieces:
        cmd += ["-ss", f"{piece.start:.3f}", "-t", f"{piece.length:.3f}", "-i", str(piece.path)]
    for name in plate_names:
        cmd += ["-i", name]
    cmd += ["-filter_complex_script", "graph.txt", "-map", "[out]"]
    if audio:
        cmd += ["-map", "[ca]"]
    if quality == "faster" and sys.platform == "darwin":
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", f"{int((bitrate or 6000) * 1.3)}k"]      # the Mac's video hardware
    elif quality == "faster":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]                          # visually lossless
    cmd += ["-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    return cmd + ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(dest)]


def run(cmd, total: float, cwd, progress_cb=None, on_proc=None) -> None:
    """Run the export (raises RuntimeError if it doesn't finish). progress_cb
    (percent, seconds exported) follows it; on_proc(process) hands over the
    running ffmpeg so the caller can stop it. What ffmpeg said is kept in
    'ffmpeg.log' in `cwd` for the caller to read on failure."""
    said = Path(cwd) / "ffmpeg.log"
    with open(said, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True, cwd=str(cwd),
                                **subprocess_flags())
        try:
            if on_proc is not None:
                on_proc(proc)
            for line in proc.stdout:
                done = parse_out_time(line)
                if done is not None and progress_cb is not None:
                    progress_cb(percent(done, total), done)
            code = proc.wait()
        finally:
            # Whatever went wrong here (the window gone, the app closing), an
            # export nobody is following must not carry on by itself.
            if proc.poll() is None:
                proc.terminate()
    if code != 0:
        try:
            LOG.info("export failed (ffmpeg exit %s): %s", code,
                     " | ".join(said.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]))
        except OSError:
            pass
        raise RuntimeError("The export didn't finish.")


def export(project: dict, files, dest, quality: str = "best", progress_cb=None, on_proc=None) -> None:
    """Export the edit of a game whose video is `files` (one file, or the halves
    in order) to dest. The file appears only once it is whole; an earlier
    export there is replaced only then. Raises RuntimeError with a message for
    the person: the first problem with the marks, or that it didn't finish."""
    segments, problems = edit.outline(project["marks"])
    if problems:
        raise RuntimeError(problems[0])
    dest = Path(dest)
    infos = [video_info(f) for f in files]
    parts = pieces(segments, [(f, info["duration"]) for f, info in zip(files, infos)])
    audio = all(info["audio"] for info in infos)
    scale = infos[0]["height"] / 1080
    total = edit.play_length(segments)
    changes = edit.score_changes(project["marks"], segments)
    with tempfile.TemporaryDirectory(prefix="tracedown-export-") as folder:
        work = Path(folder)
        shutil.copyfile(scorebug.font_path(), work / "font.ttf")
        plates = []
        for k, (since, home, away) in enumerate(changes):
            until = changes[k + 1][0] if k + 1 < len(changes) else total + 1
            name = f"plate{k}.png"
            scorebug.render(project["home"], project["away"], home, away, scale).save(work / name)
            plates.append((name, since, until))
        (work / "graph.txt").write_text(
            filter_script(parts, plates, scorebug.layout(scale), "font.ttf",
                          size=(infos[0]["width"], infos[0]["height"]), fps=infos[0]["fps"], audio=audio),
            encoding="utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_out(dest, parts, plates, work, quality, infos, audio, total, progress_cb, on_proc)


def _write_out(dest, parts, plates, work, quality, infos, audio, total, progress_cb, on_proc) -> None:
    try:
        with complete_or_nothing(dest) as part:
                # The hardware encoder is given a bitrate to aim for: 1.3 times the
                # source's, but never so little that the bug's lettering goes soft
                # (about 0.07 bits a pixel a frame, some 4.4 Mbit/s at 1080 lines).
                enough = infos[0]["width"] * infos[0]["height"] * 30 * 0.07 / 1000 / 1.3
                cmd = build_cmd(parts, [name for name, _, _ in plates], part.resolve(), quality,
                                max(infos[0]["bitrate"] or 0, enough), audio)
                cmd[0] = ffmpeg_path()
                run(cmd, total, work, progress_cb, on_proc)
    except PermissionError as error:
        # Windows won't replace a video that is open: the earlier export is playing somewhere.
        raise RuntimeError("The earlier export is open in a player, so it couldn't be replaced. "
                           "Close it and export again.") from error
