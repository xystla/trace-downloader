import subprocess
import tempfile
from pathlib import Path

from .tools import ffmpeg_path, subprocess_flags

def build_concat_cmd(parts, dest, list_file):
    return [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(dest),
    ]


def concat_entry(path):
    # FFmpeg's list syntax is not shell syntax. Forward slashes also work on
    # Windows; escape apostrophes outside the quoted portion of each filename.
    name = path.as_posix().replace("'", "'\\''")
    return f"file '{name}'\n"

def combine(parts, dest) -> None:
    """Losslessly concatenate the part files into dest (raises on failure)."""
    parts = [Path(p) for p in parts]
    missing = [str(p) for p in parts if not p.exists()]
    if missing:
        raise RuntimeError(f"combine: missing input(s): {missing}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            f.write(concat_entry(p.resolve()))
        list_file = Path(f.name)
    try:
        cmd = build_concat_cmd(parts, dest, list_file)
        cmd[0] = ffmpeg_path()
        result = subprocess.run(cmd, capture_output=True, text=True, **subprocess_flags())
        if result.returncode != 0:
            raise RuntimeError(f"combine failed ({result.returncode}): {result.stderr[-400:]}")
        if not dest.exists() or dest.stat().st_size == 0:
            raise RuntimeError("combine produced no output")
    finally:
        list_file.unlink(missing_ok=True)
