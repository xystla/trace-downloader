import hashlib
import json
from pathlib import Path

import pytest

from trace_grabber import updates

CHANGELOG = """# Changelog

## 1.4.1
- Fixed a thing.
- **Bold** start is kept as plain text.

## 1.4.0
- First line.
  continued on the next line.
- Second line.

## 1.3.15
- Older.
"""

RELEASE = {"tag_name": "v1.4.1", "body": "- Fixed a thing.\r\n- Another.\r\n\r\nNot a bullet.",
           "assets": [
               {"name": "TraceDown-Windows-Setup.exe", "browser_download_url": "https://gh/win.exe",
                "size": 300, "digest": "sha256:" + "a" * 64},
               {"name": "TraceDown-macOS-AppleSilicon.zip", "browser_download_url": "https://gh/arm.zip", "size": 200},
               {"name": "TraceDown-macOS-Intel.zip", "browser_download_url": "https://gh/intel.zip", "size": 210}]}


def test_versions_compare_by_number_not_by_text():
    assert updates.is_newer("v1.4.10", "1.4.9") and updates.is_newer("1.10.0", "1.9.9")
    assert not updates.is_newer("v1.4.0", "1.4.0") and not updates.is_newer("1.3.15", "1.4.0")
    assert not updates.is_newer("nightly", "1.4.0")              # unreadable tag: never "newer"


def test_each_computer_gets_its_own_download():
    assert updates.asset_name("win32", "AMD64") == "TraceDown-Windows-Setup.exe"
    assert updates.asset_name("darwin", "arm64") == "TraceDown-macOS-AppleSilicon.zip"
    assert updates.asset_name("darwin", "x86_64") == "TraceDown-macOS-Intel.zip"
    assert updates.asset_name("linux", "x86_64") is None


def test_changes_for_one_version_come_out_of_the_changelog():
    assert updates.notes_for("1.4.0", CHANGELOG) == ["First line. continued on the next line.", "Second line."]
    assert updates.notes_for("v1.4.1", CHANGELOG) == ["Fixed a thing.", "Bold start is kept as plain text."]
    assert updates.notes_for("9.9.9", CHANGELOG) == []


def test_release_is_read_for_this_computer():
    release = updates.parse_release(RELEASE, "win32", "AMD64")
    assert (release.version, release.url, release.size, release.sha256) == ("1.4.1", "https://gh/win.exe", 300, "a" * 64)
    assert release.notes == ["Fixed a thing.", "Another."]
    mac = updates.parse_release(RELEASE, "darwin", "arm64")
    assert (mac.url, mac.sha256) == ("https://gh/arm.zip", None)
    assert updates.parse_release(RELEASE, "linux", "x86_64").url is None


def test_check_says_whether_a_newer_version_exists():
    fetch = lambda url: json.dumps(RELEASE)
    found = updates.check("1.4.0", fetch=fetch, platform="darwin", machine="arm64")
    assert found.version == "1.4.1" and found.url == "https://gh/arm.zip"
    assert updates.check("1.4.1", fetch=fetch, platform="darwin", machine="arm64") is None
    assert updates.check("1.5.0", fetch=fetch, platform="darwin", machine="arm64") is None


def _fake_download(content):
    def run(url, dest):
        Path(dest).write_bytes(content)
    return run


def test_download_is_checked_against_githubs_checksum(tmp_path):
    content = b"installer"
    good = updates.Release("1.4.1", [], "https://gh/win.exe", len(content), hashlib.sha256(content).hexdigest(),
                           "TraceDown-Windows-Setup.exe")
    path = updates.download(good, tmp_path, run=_fake_download(content))
    assert path == tmp_path / "TraceDown-Windows-Setup.exe" and path.read_bytes() == content
    bad = updates.Release("1.4.1", [], "https://gh/win.exe", len(content), "0" * 64, "TraceDown-Windows-Setup.exe")
    with pytest.raises(RuntimeError, match="checksum"):
        updates.download(bad, tmp_path / "second", run=_fake_download(content))
    assert not (tmp_path / "second" / "TraceDown-Windows-Setup.exe").exists()      # nothing left to run


def test_a_failed_download_leaves_nothing_behind(tmp_path):
    release = updates.Release("1.4.1", [], "https://gh/win.exe", 9, None, "TraceDown-Windows-Setup.exe")
    def run(url, dest):
        Path(dest).write_bytes(b"half")
        raise RuntimeError("network dropped")
    with pytest.raises(RuntimeError):
        updates.download(release, tmp_path, run=run)
    assert list(tmp_path.iterdir()) == []


def test_windows_update_runs_the_installer_quietly_and_detached():
    argv = updates.windows_install_command(Path("C:/Temp/TraceDown-Windows-Setup.exe"))
    assert argv[:4] == ["cmd", "/c", "start", ""]              # not a child of the app the installer closes
    assert "/SILENT" in argv and str(Path("C:/Temp/TraceDown-Windows-Setup.exe")) in argv


def test_mac_update_swaps_the_app_only_after_it_has_quit_and_restores_on_failure():
    script = updates.mac_install_script()
    assert script.index("kill -0") < script.index("ditto") < script.index("mv ")
    assert ".previous" in script and "open " in script


def test_mac_app_can_only_be_replaced_where_it_is_safe(tmp_path):
    app = tmp_path / "Applications" / "TraceDown.app"
    exe = app / "Contents" / "MacOS" / "TraceDown"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert updates.mac_app_to_replace(exe) == app
    moved = tmp_path / "AppTranslocation" / "X" / "TraceDown.app" / "Contents" / "MacOS" / "TraceDown"
    moved.parent.mkdir(parents=True)
    moved.write_text("")
    assert updates.mac_app_to_replace(moved) is None            # macOS is running a read-only copy
    assert updates.mac_app_to_replace(tmp_path / "bin" / "python3") is None


def test_whats_new_shows_once_after_an_update(tmp_path):
    args = dict(current="1.4.0", changelog=CHANGELOG)
    (tmp_path / "accounts.json").write_text("{}")               # someone who was already using the app
    assert updates.pending_whats_new(tmp_path, **args) == {"version": "1.4.0",
                                                           "notes": ["First line. continued on the next line.", "Second line."]}
    updates.mark_seen(tmp_path, "1.4.0")
    assert updates.pending_whats_new(tmp_path, **args) is None
    assert updates.pending_whats_new(tmp_path, current="1.4.1", changelog=CHANGELOG)["version"] == "1.4.1"


def test_a_brand_new_install_is_not_told_what_changed(tmp_path):
    assert updates.pending_whats_new(tmp_path, current="1.4.0", changelog=CHANGELOG) is None
    assert (tmp_path / "last_version.txt").read_text() == "1.4.0"       # and the next update will be


def test_the_shipped_changelog_describes_the_shipped_version():
    from trace_grabber import paths
    text = (paths.resource_dir() / "CHANGELOG.md").read_text(encoding="utf-8")
    assert updates.notes_for(paths.APP_VERSION, text), "add a CHANGELOG.md section for this version"
