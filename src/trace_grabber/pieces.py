"""Download a half of a game piece by piece, so one that is cut off can carry on.

Trace serves video as a playlist of short (about two-second) pieces. Handing the
playlist to ffmpeg gives one MP4 that is useless until it is whole, so an
interruption loses everything. Here each piece is saved by itself in a hidden
folder beside the video; the next attempt fetches only what is missing, and the
pieces are joined into the MP4 once they are all there."""
import json
import logging
import math
import os
import shutil
import ssl
import subprocess
import sys
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
MAC_ROOTS = "/System/Library/Keychains/SystemRootCertificates.keychain"
LOG = logging.getLogger(__name__)
_CONTEXT = None


class Stopped(RuntimeError):
    """The download was stopped on request. The pieces fetched so far are kept."""


def folder_for(dest) -> Path:
    """Where a video's pieces are kept until it is whole: 'game_half1.mp4' ->
    '.game_half1.pieces' in the same folder."""
    dest = Path(dest)
    return dest.with_name(f".{dest.stem}.pieces")


def _piece(folder: Path, index: int) -> Path:
    return folder / f"{index:05d}.ts"


def _record(dest) -> Path:
    """The note left beside a finished half saying which download made it."""
    dest = Path(dest)
    return dest.with_name(f".{dest.stem}.done")


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _hide(folder: Path) -> None:
    """A leading dot hides the folder on macOS and Linux; Windows needs the attribute."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(folder), 0x02)
        except Exception:
            pass


def _prepare(folder: Path, owner: str, quality: str, count: int) -> None:
    """Make the folder ready, keeping its pieces only if they belong to this same
    download: pieces of another game, of another quality, or of a playlist with a
    different number of pieces, would not fit together."""
    wanted = {"owner": owner, "quality": quality, "count": count}
    if _read(folder / INFO) != wanted:
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    _hide(folder)
    for leftover in folder.glob("*.tmp"):          # a piece that was cut off mid-write
        leftover.unlink(missing_ok=True)
    (folder / INFO).write_text(json.dumps(wanted), encoding="utf-8")


def _context():
    """The certificates HTTPS is checked against. The packaged Mac app's Python
    comes without any (the updater uses the system's curl for the same reason),
    so there the Mac's own root certificates are read from its keychain."""
    global _CONTEXT
    if _CONTEXT is None:
        context = ssl.create_default_context()
        if sys.platform == "darwin" and not context.cert_store_stats().get("x509_ca"):
            found = subprocess.run(["security", "find-certificate", "-a", "-p", MAC_ROOTS],
                                   capture_output=True, text=True, **subprocess_flags())
            if found.returncode == 0 and found.stdout:
                context.load_verify_locations(cadata=found.stdout)
        _CONTEXT = context
    return _CONTEXT


def _get(url: str, headers: dict, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout, context=_context()) as response:
        return response.read()


def _write(path: Path, data: bytes) -> None:
    """Save a piece whole or not at all, so a piece on disk is always complete."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _fetch_piece(url: str, path: Path, headers: dict, should_stop) -> int:
    """Fetch one piece (three tries) and save it; returns its size."""
    data = None
    why = None
    for attempt in range(1, TRIES + 1):
        if should_stop():
            raise Stopped("stopped")
        try:
            data = _get(url, headers)
            if data:
                break
            why = OSError("Trace sent an empty piece")
        except Exception as error:
            data, why = None, error
        if attempt < TRIES:
            time.sleep(PAUSE * attempt)
    if not data:
        # The person is told the connection dropped; the log keeps what really happened.
        LOG.info("piece %s failed after %s tries: %r", path.name, TRIES, why)
        raise RuntimeError(DROPPED) from why
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
          on_proc=None, workers: int = 4, owner: str = "") -> None:
    """Download a half to dest. `parts` is segments.parse() output: (seconds, URL)
    for each piece, in order. Pieces already on disk from an earlier attempt are
    not fetched again. Raises Stopped when should_stop() says so, RuntimeError when
    the connection gives out or the join fails; either way the pieces are kept.

    `owner` names whose download this is (the game's id). Two games can share a
    file name, so pieces are only carried on with for the same owner, and the
    finished half is left with a record of it (see finished()).

    on_progress(done_bytes, total_bytes, pieces_done, pieces_total) follows it, the
    total being a projection from the pieces fetched so far. on_proc(process) hands
    over the ffmpeg doing the final join so the caller can stop it."""
    dest = Path(dest)
    if not parts:
        raise RuntimeError("Trace has no video for this half yet.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    folder = folder_for(dest)
    asked_to_stop = should_stop or (lambda: False)
    _prepare(folder, owner, quality, len(parts))
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
    _record(dest).write_text(json.dumps({"owner": owner, "quality": quality}), encoding="utf-8")
    _hide(_record(dest))
    shutil.rmtree(folder, ignore_errors=True)


def finished(dest, owner: str, quality: str) -> bool:
    """Is dest a half this same download already finished? A video that merely
    has the name (another game's, one at another quality, one saved by hand)
    is not."""
    return Path(dest).exists() and _read(_record(dest)) == {"owner": owner, "quality": quality}


def belongs(dest, owner: str) -> bool:
    """Did a download for `owner` leave pieces or a finished half under this name?"""
    return owner in (_read(folder_for(dest) / INFO).get("owner"), _read(_record(dest)).get("owner"))


def owned_in(folder, owner: str) -> list[Path]:
    """The videos in `folder` that a download for `owner` has pieces or a finished
    half for, whatever they are called: a download carries on under the name it
    began with, even if the naming was changed since."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    names = {p.name[1:-len(".pieces")] for p in folder.glob(".*.pieces")}
    names |= {p.name[1:-len(".done")] for p in folder.glob(".*.done")}
    return sorted(dest for dest in (folder / f"{name}.mp4" for name in names) if belongs(dest, owner))


def forget(dest) -> None:
    """The game is saved: its halves are ordinary videos now, with nothing to resume."""
    _record(dest).unlink(missing_ok=True)


def progress_of(dest, owner: str | None = None, quality: str | None = None) -> float | None:
    """How much of a cut-off download is on disk, 0 to 1; None when there is none.
    With an owner or quality given, pieces of a different one don't count: the
    next attempt would throw them away."""
    folder = folder_for(dest)
    info = _read(folder / INFO)
    if (owner is not None and info.get("owner") != owner) or (
            quality is not None and info.get("quality") != quality):
        return None
    try:
        count = int(info["count"])
    except (ValueError, KeyError, TypeError):
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
    """Throw away a cut-off download's pieces and its record. The video itself,
    if there is one, is the caller's to keep or delete."""
    shutil.rmtree(folder_for(dest), ignore_errors=True)
    forget(dest)
