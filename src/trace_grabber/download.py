import subprocess
import time
from pathlib import Path

from .progress import parse_out_time, parse_total_size, percent
from .tools import complete_or_nothing, ffmpeg_path, subprocess_flags

def build_ffmpeg_cmd(m3u8_url: str, dest: Path, headers: dict[str, str],
                     stream_progress: bool = False) -> list[str]:
    cmd = ["ffmpeg", "-y"]
    if headers:
        header_blob = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        cmd += ["-headers", header_blob]
    cmd += ["-i", m3u8_url, "-c", "copy", "-bsf:a", "aac_adtstoasc"]
    if stream_progress:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += [str(dest)]
    return cmd

def download(m3u8_url: str, dest: Path, headers: dict[str, str],
             progress_cb=None, duration: float = 0.0, on_proc=None) -> None:
    """Download a stream to dest. The file only appears under that name once it
    is whole (see complete_or_nothing)."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    with complete_or_nothing(dest) as part:
        _download(m3u8_url, part, headers, progress_cb, duration, on_proc)

def _download(m3u8_url, dest, headers, progress_cb, duration, on_proc) -> None:
    if progress_cb is None:
        cmd = build_ffmpeg_cmd(m3u8_url, dest, headers)
        cmd[0] = ffmpeg_path()
        result = subprocess.run(cmd, capture_output=True, text=True, **subprocess_flags())
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed ({result.returncode}): {result.stderr[-500:]}")
        return
    cmd = build_ffmpeg_cmd(m3u8_url, dest, headers, stream_progress=True)
    cmd[0] = ffmpeg_path()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **subprocess_flags())
    if on_proc is not None:
        on_proc(proc)
    cur_size, cur_time = 0, 0.0
    last_clock, last_size = None, 0
    for line in proc.stdout:
        ts = parse_total_size(line)
        if ts is not None:
            cur_size = ts
        ot = parse_out_time(line)
        if ot is not None:
            cur_time = ot
        if line.startswith("progress="):
            now = time.monotonic()
            mbps = 0.0
            if last_clock is not None and now > last_clock:
                mbps = max(0.0, (cur_size - last_size) / (now - last_clock) / 1_000_000)
            last_clock, last_size = now, cur_size
            progress_cb(percent(cur_time, duration), mbps)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode})")
    progress_cb(100, 0.0)
