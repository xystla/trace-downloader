"""Download a half of a game piece by piece, so one that is cut off can carry on.

Trace serves video as a playlist of short (about two-second) pieces. Handing the
playlist to ffmpeg gives one MP4 that is useless until it is whole, so an
interruption loses everything. Here each piece is saved by itself in a hidden
folder beside the video; the next attempt fetches only what is missing, and the
pieces are joined into the MP4 once they are all there."""
import json
import math
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .tools import complete_or_nothing, ffmpeg_path, subprocess_flags

INFO = "info.json"
PLAYLIST = "index.m3u8"
TRIES = 3
PAUSE = 2          # seconds before trying a piece again, times the attempt number
DROPPED = "The connection dropped. What was downloaded is kept, so Resume carries on from here."


class Stopped(RuntimeError):
    """The download was stopped on request. The pieces fetched so far are kept."""


def folder_for(dest) -> Path:
    """Where a video's pieces are kept until it is whole: 'game_half1.mp4' ->
    '.game_half1.pieces' in the same folder."""
    dest = Path(dest)
    return dest.with_name(f".{dest.stem}.pieces")


def _piece(folder: Path, index: int) -> Path:
    return folder / f"{index:05d}.ts"


def _hide(folder: Path) -> None:
    """A leading dot hides the folder on macOS and Linux; Windows needs the attribute."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(folder), 0x02)
        except Exception:
            pass


def _prepare(folder: Path, quality: str, count: int) -> None:
    """Make the folder ready, keeping its pieces only if they belong to this same
    download: pieces of another quality, or of a playlist with a different number
    of pieces, would not fit together."""
    wanted = {"quality": quality, "count": count}
    try:
        same = json.loads((folder / INFO).read_text(encoding="utf-8")) == wanted
    except (OSError, ValueError):
        same = False
    if not same:
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    _hide(folder)
    for leftover in folder.glob("*.tmp"):          # a piece that was cut off mid-write
        leftover.unlink(missing_ok=True)
    (folder / INFO).write_text(json.dumps(wanted), encoding="utf-8")


def _get(url: str, headers: dict, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _write(path: Path, data: bytes) -> None:
    """Save a piece whole or not at all, so a piece on disk is always complete."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _fetch_piece(url: str, path: Path, headers: dict, should_stop) -> int:
    """Fetch one piece (three tries) and save it; returns its size."""
    data = None
    for attempt in range(1, TRIES + 1):
        if should_stop():
            raise Stopped("stopped")
        try:
            data = _get(url, headers)
            if data:
                break
        except Exception:
            data = None
        if attempt < TRIES:
            time.sleep(PAUSE * attempt)
    if not data:
        raise RuntimeError(DROPPED)
    _write(path, data)            # a failure here (a full disk) is not retried: it isn't the connection
    return len(data)


def _join(parts, folder: Path, dest: Path, on_proc) -> None:
    """Join the pieces into dest through a local playlist, so ffmpeg reads them
    just as it would read Trace's own playlist."""
    longest = max(seconds for seconds, _ in parts)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{math.ceil(longest)}",
             "#EXT-X-MEDIA-SEQUENCE:0"]
    for index, (seconds, _) in enumerate(parts):
        lines += [f"#EXTINF:{seconds:.6f},", _piece(folder, index).name]
    lines.append("#EXT-X-ENDLIST")
    playlist = folder / PLAYLIST
    playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with complete_or_nothing(dest) as part:
        cmd = [ffmpeg_path(), "-y", "-i", str(playlist), "-c", "copy", "-bsf:a", "aac_adtstoasc", str(part)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                **subprocess_flags())
        if on_proc is not None:
            on_proc(proc)
        returncode = proc.wait()
        if returncode != 0:
            raise RuntimeError(f"Putting the video together didn't finish (ffmpeg exit {returncode}).")


def fetch(parts, dest, headers: dict, quality: str, on_progress=None, should_stop=None,
          on_proc=None, workers: int = 4) -> None:
    """Download a half to dest. `parts` is segments.parse() output: (seconds, URL)
    for each piece, in order. Pieces already on disk from an earlier attempt are
    not fetched again. Raises Stopped when should_stop() says so, RuntimeError when
    the connection gives out or the join fails; either way the pieces are kept.

    on_progress(done_bytes, total_bytes, pieces_done, pieces_total) follows it, the
    total being a projection from the pieces fetched so far. on_proc(process) hands
    over the ffmpeg doing the final join so the caller can stop it."""
    dest = Path(dest)
    if not parts:
        raise RuntimeError("Trace has no video for this half yet.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    folder = folder_for(dest)
    asked_to_stop = should_stop or (lambda: False)
    _prepare(folder, quality, len(parts))
    sizes = {index: _piece(folder, index).stat().st_size
             for index in range(len(parts)) if _piece(folder, index).exists()}

    def report():
        if on_progress is None:
            return
        done = sum(sizes.values())
        total = int(done / len(sizes) * len(parts)) if sizes else 0
        on_progress(done, total, len(sizes), len(parts))

    report()
    missing = [index for index in range(len(parts)) if index not in sizes]
    failed = threading.Event()        # one piece gave up: the others stop instead of carrying on
    stop = lambda: asked_to_stop() or failed.is_set()
    error = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_piece, parts[index][1], _piece(folder, index), headers, stop): index
                   for index in missing}
        for future in as_completed(futures):
            if future.cancelled():
                continue
            try:
                sizes[futures[future]] = future.result()
            except Exception as e:
                if error is None:
                    error = e
                    failed.set()
                    for other in futures:
                        other.cancel()
                continue
            report()
    if error is not None:
        raise error
    if asked_to_stop():
        raise Stopped("stopped")
    _join(parts, folder, dest, on_proc)
    shutil.rmtree(folder, ignore_errors=True)


def progress_of(dest) -> float | None:
    """How much of a cut-off download is on disk, 0 to 1; None when there is none."""
    folder = folder_for(dest)
    try:
        count = int(json.loads((folder / INFO).read_text(encoding="utf-8"))["count"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if count <= 0:
        return None
    return min(1.0, len(list(folder.glob("*.ts"))) / count)


def bytes_on_disk(dest) -> int:
    """Bytes of pieces already fetched for dest."""
    folder = folder_for(dest)
    if not folder.is_dir():
        return 0
    return sum(p.stat().st_size for p in folder.glob("*.ts"))


def discard(dest) -> None:
    """Throw away a cut-off download's pieces."""
    shutil.rmtree(folder_for(dest), ignore_errors=True)
