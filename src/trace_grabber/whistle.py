"""Hearing the referee's whistle in a game's video.

A whistle is a burst of sound somewhere between about 2.5 and 4.5 kHz (where
depends on the whistle, and a pea whistle warbles over a few hundred Hz), far
louder than anything usually is at that pitch, lasting a fraction of a second.
Voices and cheering reach that high as well, but they are louder lower down
than they are up there; a whistle is not.

ffmpeg draws the sound of a stretch of the video as a picture (time across,
pitch up, loudness as brightness) and the whistle is looked for in that. Only
short stretches are looked at, around the moments a whistle would settle.
"""
import io
import subprocess

from PIL import Image

from .tools import ffmpeg_path, subprocess_flags

RATE = 16000                # samples a second: the picture runs up to half of this, 8 kHz
ROWS = 256                  # of pitch, so about 31 Hz a row
COLUMNS = 25                # a second, so 0.04 seconds a column
DB_A_STEP = 120 / 255       # ffmpeg spreads 120 dB over a pixel's 0-255

LOW, HIGH = 2500, 4500      # Hz: where a whistle's note is
VOICE = (500, 2300)         # Hz: where voices are loudest
NOTE_ROWS = 8               # the note and this many rows either side (about 250 Hz) are "the note"
CLEAR_DB = 25.0             # the note stands this far above the rest of its range at that moment...
JUMP_DB = 30.0              # ... and this far above what that pitch usually is in this stretch
OVER_VOICE_DB = -10.0       # ... and is not this much quieter than the loudest of the voices
MIN_SECS = 0.12             # a blast lasts at least this long
JOIN_SECS = 2.5             # blasts this close together are one signal


def _row(hz: float) -> int:
    """The picture's row for a pitch, counted from the bottom (0 Hz)."""
    return max(0, min(ROWS - 1, round(hz / (RATE / 2) * (ROWS - 1))))


def picture(path, start: float, seconds: float):
    """The sound of a stretch of a video as columns of loudness: one list for
    each 1/COLUMNS of a second, each with ROWS numbers (0-255) from the lowest
    pitch up. None when the video has no sound there, or ffmpeg can't say."""
    wide = max(2, round(seconds * COLUMNS))
    done = subprocess.run(
        [ffmpeg_path(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, start):.3f}", "-t", f"{seconds:.3f}",
         "-i", str(path), "-vn",
         "-lavfi", f"aformat=channel_layouts=mono,aresample={RATE},"
                   f"showspectrumpic=s={wide}x{ROWS}:legend=0:scale=log:fscale=lin:saturation=0",
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, **subprocess_flags())
    if done.returncode != 0 or not done.stdout:
        return None
    try:
        image = Image.open(io.BytesIO(done.stdout)).convert("L")
    except OSError:
        return None
    width, height = image.size
    pixels = image.tobytes()
    # The picture has the highest pitch at the top: turn each column over.
    return [[pixels[(height - 1 - y) * width + x] for y in range(height)] for x in range(width)]


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def blasts(columns) -> list[tuple[float, float]]:
    """(seconds in, how long) for each whistle blast in a stretch's picture."""
    if not columns:
        return []
    low, high = _row(LOW), _row(HIGH)
    usual = [_median([c[r] for c in columns]) for r in range(len(columns[0]))]      # how loud each pitch usually is
    voice = (_row(VOICE[0]), _row(VOICE[1]))
    loud = []                       # for each column: is a whistle sounding
    for c in columns:
        peak = max(range(low, high + 1), key=lambda r: c[r])
        rest = [c[r] for r in range(low, high + 1) if abs(r - peak) > NOTE_ROWS]
        clear = (c[peak] - _median(rest)) * DB_A_STEP >= CLEAR_DB
        jump = (c[peak] - usual[peak]) * DB_A_STEP >= JUMP_DB
        over = (c[peak] - max(c[voice[0]:voice[1] + 1])) * DB_A_STEP >= OVER_VOICE_DB
        loud.append(clear and jump and over)
    found, start = [], None
    for i, on in enumerate(loud + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if (i - start) / COLUMNS >= MIN_SECS:
                found.append((start / COLUMNS, (i - start) / COLUMNS))
            start = None
    return found


def signals(found, starts: float = 0.0) -> list[tuple[float, float]]:
    """Blasts close together as one signal each: (when it starts, when it ends),
    timed from `starts`."""
    out = []
    for at, length in found:
        if out and at + starts - out[-1][1] <= JOIN_SECS:
            out[-1] = (out[-1][0], at + length + starts)
        else:
            out.append((at + starts, at + length + starts))
    return out


def heard(path, start: float, seconds: float) -> list[tuple[float, float]] | None:
    """The whistle signals in a stretch of a video, timed from the video's
    start: [(when it starts, when it ends)]. None when there is no sound to hear."""
    columns = picture(path, start, seconds)
    if columns is None:
        return None
    return signals(blasts(columns), max(0.0, start))
