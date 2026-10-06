"""In-app updates: find a newer release on GitHub, download it, hand over to the
installer, and say what changed.

Everything goes through the system's own `curl` (present on macOS and on
Windows 10/11), which uses the operating system's certificates — the frozen
app's Python has none of its own to verify HTTPS with.
"""
import hashlib
import json
import os
import platform as _platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .tools import subprocess_flags

REPO = "xystla/trace-downloader"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


@dataclass
class Release:
    version: str                # "1.4.1"
    notes: list[str]            # one line per change
    url: str | None             # this computer's download, None if the release has none
    size: int = 0
    sha256: str | None = None   # GitHub's checksum for the download, when it gives one
    asset: str | None = None    # the download's file name


def _numbers(version: str):
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (version or "").strip())
    return tuple(int(n) for n in m.group(1).split(".")) if m else None


def is_newer(candidate: str, current: str) -> bool:
    a, b = _numbers(candidate), _numbers(current)
    return a is not None and b is not None and a > b


def asset_name(platform: str, machine: str):
    """The release file for this kind of computer, or None if there isn't one."""
    if platform == "win32":
        return "TraceDown-Windows-Setup.exe"
    if platform == "darwin":
        return ("TraceDown-macOS-AppleSilicon.zip" if machine.lower() in ("arm64", "aarch64")
                else "TraceDown-macOS-Intel.zip")
    return None


def _bullets(text: str) -> list[str]:
    """The '- ' list items of some Markdown as plain lines."""
    items: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if re.match(r"\s*[-*] ", line):
            items.append(re.sub(r"^\s*[-*] ", "", line))
        elif items and line.startswith((" ", "\t")) and line.strip():
            items[-1] += " " + line.strip()          # a wrapped item continues
        elif line.strip():
            items.append(None)                        # other text ends the current item
    return [re.sub(r"\*\*|__|`", "", item).strip() for item in items if item]


def notes_for(version: str, changelog: str) -> list[str]:
    """The changes listed under '## <version>' in the changelog."""
    wanted = (version or "").lstrip("v")
    section: list[str] = []
    inside = False
    for line in changelog.splitlines():
        heading = re.match(r"##\s+v?([\d.]+)", line)
        if heading:
            inside = heading.group(1) == wanted
        elif inside:
            section.append(line)
    return _bullets("\n".join(section))


def parse_release(data: dict, platform: str, machine: str) -> Release:
    name = asset_name(platform, machine)
    asset = next((a for a in data.get("assets") or [] if a.get("name") == name), None) or {}
    digest = asset.get("digest") or ""
    return Release(version=(data.get("tag_name") or "").lstrip("v"),
                   notes=_bullets(data.get("body") or ""),
                   url=asset.get("browser_download_url"),
                   size=asset.get("size") or 0,
                   sha256=digest[7:] if digest.startswith("sha256:") else None,
                   asset=name if asset else None)


def _curl_text(url: str) -> str:
    result = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "20",
         "-H", "Accept: application/vnd.github+json", "-H", "User-Agent: TraceDown", url],
        capture_output=True, text=True, **subprocess_flags())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exit {result.returncode}")
    return result.stdout


def check(current: str, fetch=None, platform: str | None = None, machine: str | None = None):
    """The latest release if it is newer than `current`, else None. Raises if
    GitHub can't be reached."""
    data = json.loads((fetch or _curl_text)(LATEST_URL))
    release = parse_release(data, platform or sys.platform, machine or _platform.machine())
    return release if is_newer(release.version, current) else None


def _curl_download(url: str, dest: Path, size: int = 0, on_progress=None) -> None:
    proc = subprocess.Popen(
        ["curl", "--fail", "--silent", "--show-error", "--location",
         "-H", "User-Agent: TraceDown", "--output", str(dest), url],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, **subprocess_flags())
    while proc.poll() is None:
        if on_progress and size and dest.exists():
            on_progress(min(99, int(dest.stat().st_size / size * 100)))
        time.sleep(0.4)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr.read() or "").strip() or f"curl exit {proc.returncode}")


def download(release: Release, folder, run=None, on_progress=None) -> Path:
    """Download the release's file into `folder` and return its path. It is
    checked against GitHub's checksum (when given) and only appears under its
    real name once whole and verified."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / release.asset
    part = dest.with_name(dest.name + ".part")
    try:
        if run is not None:
            run(release.url, part)
        else:
            _curl_download(release.url, part, release.size, on_progress)
        if release.sha256:
            digest = hashlib.sha256()
            with open(part, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != release.sha256.lower():
                raise RuntimeError("The download didn't match its checksum, so it was not installed.")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    if on_progress:
        on_progress(100)
    return dest


# ---- handing over to the installer ----

def windows_install_command(installer: Path) -> list[str]:
    """Run the installer quietly. `start` launches it on its own rather than as a
    child of this app, because the installer's first act is to close TraceDown
    and everything TraceDown started. The installer reopens the app when done."""
    return ["cmd", "/c", "start", "", str(installer), "/SILENT", "/SP-", "/NORESTART"]


def mac_app_to_replace(executable):
    """The .app bundle this executable runs from, if it can safely be replaced:
    a real TraceDown.app in a folder we can write to, not one of the read-only
    copies macOS runs from when an app is opened straight from Downloads."""
    exe = Path(executable)
    app = exe.parents[2] if len(exe.parents) > 2 else None
    if app is None or app.suffix != ".app" or exe.parent.name != "MacOS":
        return None
    if "AppTranslocation" in app.parts or not os.access(app.parent, os.W_OK):
        return None
    return app


def mac_install_script() -> str:
    """Shell script: wait for the app to quit, unpack the new one, swap it in
    (putting the old one back if that fails), and reopen. Args: pid zip app."""
    return """#!/bin/sh
PID="$1"; ZIP="$2"; APP="$3"
# Wait for the app to quit; if it is somehow still running after a minute, leave it alone.
N=0
while kill -0 "$PID" 2>/dev/null; do
  N=$((N + 1)); [ "$N" -gt 200 ] && exit 1
  sleep 0.3
done
TMP=$(mktemp -d) || exit 1
/usr/bin/ditto -x -k "$ZIP" "$TMP" || { /usr/bin/open "$APP"; exit 1; }
NEW="$TMP/$(basename "$APP")"
[ -d "$NEW" ] || { /usr/bin/open "$APP"; exit 1; }
OLD="$APP.previous"
rm -rf "$OLD"
mv "$APP" "$OLD" || { /usr/bin/open "$APP"; exit 1; }
if mv "$NEW" "$APP"; then
  rm -rf "$OLD" "$TMP" "$ZIP"
else
  mv "$OLD" "$APP"
fi
/usr/bin/open "$APP"
"""


def start_install(path: Path, platform: str | None = None, executable=None, pid: int | None = None) -> bool:
    """Start replacing the running app with the downloaded one. Returns True if
    the app should now quit (the installer takes over), False if it couldn't be
    done automatically and the download should be shown to the person instead."""
    platform = platform or sys.platform
    if platform == "win32":
        subprocess.Popen(windows_install_command(path), **subprocess_flags())
        return True
    if platform == "darwin":
        app = mac_app_to_replace(executable or sys.executable)
        if app is None:
            return False
        script = Path(path).with_name("install-update.sh")
        script.write_text(mac_install_script(), encoding="utf-8")
        subprocess.Popen(["/bin/sh", str(script), str(pid or os.getpid()), str(path), str(app)],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False


# ---- "what's new", shown once after an update ----

def _seen_file(data_dir) -> Path:
    return Path(data_dir) / "last_version.txt"


def mark_seen(data_dir, version: str) -> None:
    _seen_file(data_dir).write_text(version, encoding="utf-8")


def pending_whats_new(data_dir, current: str, changelog: str):
    """{'version', 'notes'} if this version's changes haven't been shown yet,
    else None. A brand-new install has nothing to compare with, so it is just
    recorded; someone already using the app (they have accounts) is told."""
    seen = _seen_file(data_dir)
    last = seen.read_text(encoding="utf-8").strip() if seen.exists() else None
    if last == current:
        return None
    if last is None and not (Path(data_dir) / "accounts.json").exists():
        mark_seen(data_dir, current)
        return None
    notes = notes_for(current, changelog)
    if not notes:
        mark_seen(data_dir, current)
        return None
    return {"version": current, "notes": notes}
