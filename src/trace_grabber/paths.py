import sys
from pathlib import Path

import platformdirs

APP_NAME = "TraceDown"
APP_VERSION = "1.3.11"

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

def _portable_dir() -> Path | None:
    """A writable 'data' folder next to the frozen executable, or None if that
    location can't be used (not frozen, inside a macOS .app, or read-only)."""
    if not is_frozen():
        return None
    if sys.platform == "darwin":
        # A .app's executable lives in Contents/MacOS — never portable.
        return None
    cand = Path(sys.executable).resolve().parent / "data"
    try:
        cand.mkdir(parents=True, exist_ok=True)
        probe = cand / ".write-test"
        probe.write_text("")
        probe.unlink()
        return cand
    except Exception:
        return None

def data_dir() -> Path:
    d = _portable_dir()
    if d is None:
        d = Path(platformdirs.user_data_dir(APP_NAME))
    d.mkdir(parents=True, exist_ok=True)
    return d

def resource_dir() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]
