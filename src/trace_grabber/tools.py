import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from . import paths

def part_path(dest) -> Path:
    """The temporary name a video is written under: 'game.mp4' -> 'game.part.mp4'
    (still ending .mp4, so ffmpeg picks the right format)."""
    dest = Path(dest)
    return dest.with_name(f"{dest.stem}.part{dest.suffix}")

@contextmanager
def complete_or_nothing(dest):
    """Yield a temporary path to write a video to. It takes its real name only if
    the block finishes and produced something; otherwise it is deleted. A video
    that exists under its real name is therefore always whole — one cut short by
    an error, a cancel or the app closing is never mistaken for a saved one."""
    dest = Path(dest)
    part = part_path(dest)
    part.unlink(missing_ok=True)
    try:
        yield part
        if not part.exists() or part.stat().st_size == 0:
            raise RuntimeError(f"nothing was written for {dest.name}")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)

def subprocess_flags() -> dict:
    """Kwargs to keep child processes from popping a console window on Windows.

    The frozen app is windowed (console=False); launching a console child
    (node/ffmpeg) without this would allocate a visible console window.
    CREATE_NO_WINDOW exists only on Windows, so it is referenced only there.
    """
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}

def _ffmpeg_name() -> str:
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

def ffmpeg_path() -> str:
    name = _ffmpeg_name()
    for base in (paths.resource_dir() / "bin", paths.data_dir() / "bin"):
        cand = base / name
        if cand.exists():
            return str(cand)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if Path(p).exists():
            return p
    return "ffmpeg"

def setup_browser_env() -> None:
    """Point Playwright at a bundled browsers folder when frozen.

    Prefer Chromium bundled into the app (no first-run download, fully
    portable). Fall back to the data dir (where install_chromium would put it)
    if the bundle is missing. In dev, leave the OS cache alone."""
    if not paths.is_frozen():
        return
    bundled = paths.resource_dir() / "ms-playwright"
    if any(bundled.glob("chromium-*")):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
    else:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(paths.data_dir() / "ms-playwright")

def _browsers_path() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"

def chromium_installed() -> bool:
    base = _browsers_path()
    return base.exists() and any(base.glob("chromium-*"))

def install_chromium() -> None:
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    driver = compute_driver_executable()
    args = list(driver) if isinstance(driver, (list, tuple)) else [driver]
    env = {**os.environ, **get_driver_env()}
    subprocess.run([*args, "install", "chromium"], env=env, check=True, **subprocess_flags())
