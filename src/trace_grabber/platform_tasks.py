import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from . import paths
from . import tools

PLIST_LABEL = "com.tracedownloader"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
WIN_TASK = "TraceDownloader"
# Opening TraceDown at login, so automatic downloads keep going after a restart.
LOGIN_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.tracedownloader.login.plist"
WIN_RUN_KEY = "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"
WIN_RUN_NAME = "TraceDown"
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def run_command() -> list[str]:
    if paths.is_frozen():
        return [sys.executable, "--run"]
    return [sys.executable, "-m", "gui.entry", "--run"]

def _mac_plist(interval_hours: int) -> str:
    args = "".join(f"      <string>{a}</string>\n" for a in run_command())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'  <key>Label</key><string>{PLIST_LABEL}</string>\n'
        f'  <key>ProgramArguments</key><array>\n{args}  </array>\n'
        f'  <key>StartInterval</key><integer>{interval_hours * 3600}</integer>\n'
        '</dict></plist>\n'
    )

def _mac_enable(interval_hours):
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT.write_text(_mac_plist(interval_hours))
    subprocess.run(["launchctl", "load", str(LAUNCH_AGENT)], check=False)

def _mac_disable():
    subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT)], check=False)
    if LAUNCH_AGENT.exists():
        LAUNCH_AGENT.unlink()

def _win_cmd_string():
    return " ".join(f'"{a}"' if " " in a else a for a in run_command())

def _win_enable(interval_hours):
    subprocess.run(["schtasks", "/Create", "/F", "/SC", "HOURLY", "/MO",
                    str(interval_hours), "/TN", WIN_TASK, "/TR", _win_cmd_string()],
                   check=False, **tools.subprocess_flags())

def _win_disable():
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", WIN_TASK], check=False, **tools.subprocess_flags())

def background_command() -> list[str]:
    """How to start the app quietly in the background (window hidden)."""
    if paths.is_frozen():
        return [sys.executable, "--background"]
    return [sys.executable, "-m", "gui.entry", "--background"]

def login_enable() -> None:
    """Open TraceDown, in the background, whenever this person logs in."""
    if sys.platform == "darwin":
        args = "".join(f"<string>{a}</string>" for a in background_command())
        LOGIN_AGENT.parent.mkdir(parents=True, exist_ok=True)
        LOGIN_AGENT.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            '<key>Label</key><string>com.tracedownloader.login</string>'
            f'<key>ProgramArguments</key><array>{args}</array>'
            '<key>RunAtLoad</key><true/>'
            '</dict></plist>\n', encoding="utf-8")
    elif sys.platform == "win32":
        exe, *rest = background_command()
        subprocess.run(["reg", "add", WIN_RUN_KEY, "/v", WIN_RUN_NAME, "/t", "REG_SZ",
                        "/d", " ".join([f'"{exe}"', *rest]), "/f"],
                       check=False, capture_output=True, **tools.subprocess_flags())

def login_disable() -> None:
    if sys.platform == "darwin":
        LOGIN_AGENT.unlink(missing_ok=True)
    elif sys.platform == "win32":
        subprocess.run(["reg", "delete", WIN_RUN_KEY, "/v", WIN_RUN_NAME, "/f"],
                       check=False, capture_output=True, **tools.subprocess_flags())

def login_enabled() -> bool:
    if sys.platform == "darwin":
        return LOGIN_AGENT.exists()
    if sys.platform == "win32":
        r = subprocess.run(["reg", "query", WIN_RUN_KEY, "/v", WIN_RUN_NAME],
                           check=False, capture_output=True, **tools.subprocess_flags())
        return r.returncode == 0
    return False

def schedule_enable(interval_hours: int = 3) -> None:
    if sys.platform == "darwin":
        _mac_enable(interval_hours)
    elif os.name == "nt":
        _win_enable(interval_hours)

def schedule_disable() -> None:
    if sys.platform == "darwin":
        _mac_disable()
    elif os.name == "nt":
        _win_disable()

def schedule_enabled() -> bool:
    if sys.platform == "darwin":
        return LAUNCH_AGENT.exists()
    if os.name == "nt":
        r = subprocess.run(["schtasks", "/Query", "/TN", WIN_TASK],
                           capture_output=True, text=True, **tools.subprocess_flags())
        return r.returncode == 0
    return False

def _set_execution_state(flags: int) -> None:
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(flags)

def _try_execution_state(flags: int) -> None:
    try:
        _set_execution_state(flags)
    except Exception:
        pass

@contextmanager
def keep_awake():
    """Stop Windows idle-sleeping for the duration (the display may still turn off).

    The request belongs to the calling thread, so enter and exit on the same one.
    """
    if sys.platform != "win32":
        yield
        return
    _try_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        _try_execution_state(ES_CONTINUOUS)

def open_file(path) -> None:
    """Open a file in the default app (a video in the default player)."""
    opener = "open" if sys.platform == "darwin" else "explorer" if sys.platform == "win32" else "xdg-open"
    subprocess.run([opener, str(path)], check=False)

def reveal_file(path) -> None:
    """Show a file selected in Finder / Explorer."""
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", f"/select,{path}"], check=False)
    else:
        subprocess.run(["xdg-open", str(Path(path).parent)], check=False)

# A toast through the notification system built into Windows 10/11 — no add-on
# module. It is posted under Windows PowerShell's own app identity, the one
# identity every PC already has registered, so the toast is not silently dropped.
# The message is read from the environment so it never needs escaping, and the
# script has no double quotes, so passing it on the command line cannot mangle it.
_WIN_TOAST = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
    "$xml.LoadXml('<toast><visual><binding template=''ToastGeneric''><text>TraceDown</text><text></text></binding></visual></toast>'); "
    "$xml.GetElementsByTagName('text').Item(1).AppendChild($xml.CreateTextNode($env:TRACEDOWN_MESSAGE)) | Out-Null; "
    "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml; "
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)"
)

def notify(message: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e",
                f'display notification "{message}" with title "TraceDown"'],
                check=False)
        elif sys.platform == "win32":
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _WIN_TOAST],
                           check=False, env={**os.environ, "TRACEDOWN_MESSAGE": message},
                           **tools.subprocess_flags())
    except Exception:
        pass


# ---- the Trash: removing a game is never a deletion ----
_WIN_RECYCLE = (
    "Add-Type -AssemblyName Microsoft.VisualBasic; "
    "$p = $env:TRACEDOWN_PATH; "
    "if (Test-Path -LiteralPath $p -PathType Container) "
    "{ [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, 'OnlyErrorDialogs', 'SendToRecycleBin') } "
    "else { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin') }"
)


def bin_name() -> str:
    """What this computer calls the place removed files go."""
    return "Recycle Bin" if sys.platform == "win32" else "Trash"


def _trash_one(path: Path) -> None:
    if sys.platform == "darwin":
        from Foundation import NSFileManager, NSURL
        ok, _, error = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            NSURL.fileURLWithPath_(str(path)), None, None)
        if not ok:
            raise RuntimeError(str(error or "the Trash refused it"))
    elif sys.platform == "win32":
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _WIN_RECYCLE],
                              capture_output=True, text=True, check=False,
                              env={**os.environ, "TRACEDOWN_PATH": str(path)}, **tools.subprocess_flags())
        if done.returncode != 0:
            raise RuntimeError((done.stderr or "").strip()[-200:] or "the Recycle Bin refused it")
    else:
        done = subprocess.run(["gio", "trash", str(path)], capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise RuntimeError((done.stderr or "").strip()[-200:] or "the Trash refused it")


def trash(paths) -> None:
    """Move files and folders to the Trash (Recycle Bin on Windows), where they
    can be put back. Raises RuntimeError naming what couldn't be moved; anything
    already gone is skipped."""
    for path in (Path(p) for p in paths):
        if not path.exists():
            continue
        try:
            _trash_one(path)
        except Exception as error:
            raise RuntimeError(f"Couldn't move {path.name} to the {bin_name()}: {error}") from error
