"""Trace serves video as a playlist of short (about two-second) pieces. These
helpers pick pieces out of a playlist and join a run of them into one file."""
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from .progress import parse_out_time, percent
from .tools import complete_or_nothing, ffmpeg_path, subprocess_flags


def parse(playlist: str, playlist_url: str) -> list[tuple[float, str]]:
    """(seconds, absolute URL) for each piece of a media playlist, in order."""
    pieces = []
    seconds = None
    for line in playlist.splitlines():
        line = line.strip()
        m = re.match(r"#EXTINF:([\d.]+)", line)
        if m:
            seconds = float(m.group(1))
        elif line and not line.startswith("#") and seconds is not None:
            pieces.append((seconds, urljoin(playlist_url, line)))
            seconds = None
    return pieces


def window(pieces: list[tuple[float, str]], start: float, length: float) -> list[str]:
    """URLs of the pieces that cover `length` seconds from `start`."""
    end = start + length
    urls = []
    at = 0.0
    for seconds, url in pieces:
        if at + seconds > start and at < end:
            urls.append(url)
        at += seconds
    return urls


def download(urls: list[str], dest, total_secs: float = 0.0, progress_cb=None, on_proc=None) -> None:
    """Join the pieces end to end into dest (raises on failure). The file only
    appears under that name once it is whole.

    progress_cb(percent) is called as it goes; on_proc(process) hands over the
    running ffmpeg so the caller can stop it."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.writelines(f"file '{url}'\n" for url in urls)
        list_file = Path(f.name)
    try:
        with complete_or_nothing(dest) as part:
            cmd = [ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
                   "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                   "-i", str(list_file), "-c", "copy", "-bsf:a", "aac_adtstoasc",
                   "-progress", "pipe:1", "-nostats", str(part)]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, **subprocess_flags())
            if on_proc is not None:
                on_proc(proc)
            last = None
            for line in proc.stdout:
                done = parse_out_time(line)
                if done is None or progress_cb is None:
                    continue
                pct = min(percent(done, total_secs), 99)   # 100 is reported once the file is whole
                if pct != last:
                    last = pct
                    progress_cb(pct)
            returncode = proc.wait()
            if returncode != 0:
                raise RuntimeError(f"The download didn't finish (ffmpeg exit {returncode}).")
        if progress_cb is not None:
            progress_cb(100)
    finally:
        list_file.unlink(missing_ok=True)
