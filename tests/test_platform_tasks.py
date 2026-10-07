from unittest.mock import patch

def test_run_command_dev(monkeypatch):
    from trace_grabber import platform_tasks as pt, paths
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    cmd = pt.run_command()
    assert cmd[-1] == "--run" and "gui.entry" in cmd

def test_run_command_frozen(monkeypatch):
    from trace_grabber import platform_tasks as pt, paths
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    assert pt.run_command()[-1] == "--run"

def test_mac_enable_writes_plist(monkeypatch, tmp_path):
    from trace_grabber import platform_tasks as pt
    monkeypatch.setattr(pt, "LAUNCH_AGENT", tmp_path / "x.plist")
    monkeypatch.setattr(pt.sys, "platform", "darwin")
    with patch.object(pt.subprocess, "run") as run:
        pt.schedule_enable(3)
        assert (tmp_path / "x.plist").exists()
        assert "StartInterval" in (tmp_path / "x.plist").read_text()
        assert pt.schedule_enabled() is True
        run.assert_called()

def test_win_enable_builds_schtasks(monkeypatch):
    from trace_grabber import platform_tasks as pt
    with patch.object(pt.subprocess, "run") as run:
        pt._win_enable(3)
        argv = run.call_args[0][0]
        assert argv[0] == "schtasks" and "/Create" in argv and "TraceDownloader" in argv

def test_notify_never_raises():
    from trace_grabber import platform_tasks as pt
    pt.notify("hi")  # must not raise on any platform

def _record_execution_state(monkeypatch, platform="win32"):
    from trace_grabber import platform_tasks as pt
    calls = []
    monkeypatch.setattr(pt.sys, "platform", platform)
    monkeypatch.setattr(pt, "_set_execution_state", calls.append)
    return pt, calls

def test_keep_awake_holds_system_awake_then_releases_on_windows(monkeypatch):
    pt, calls = _record_execution_state(monkeypatch)
    with pt.keep_awake():
        assert calls == [pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED]
    assert calls[-1] == pt.ES_CONTINUOUS and len(calls) == 2

def test_keep_awake_releases_when_download_fails(monkeypatch):
    pt, calls = _record_execution_state(monkeypatch)
    try:
        with pt.keep_awake():
            raise RuntimeError("ffmpeg died")
    except RuntimeError:
        pass
    assert calls[-1] == pt.ES_CONTINUOUS

def test_keep_awake_does_nothing_off_windows(monkeypatch):
    pt, calls = _record_execution_state(monkeypatch, platform="darwin")
    with pt.keep_awake():
        pass
    assert calls == []

def test_keep_awake_never_blocks_the_download_if_windows_refuses(monkeypatch):
    from trace_grabber import platform_tasks as pt
    monkeypatch.setattr(pt.sys, "platform", "win32")
    def refuse(flags):
        raise OSError("no kernel32")
    monkeypatch.setattr(pt, "_set_execution_state", refuse)
    ran = []
    with pt.keep_awake():
        ran.append(True)
    assert ran == [True]

def _commands(monkeypatch, platform):
    from trace_grabber import platform_tasks as pt
    monkeypatch.setattr(pt.sys, "platform", platform)
    calls = []
    monkeypatch.setattr(pt.subprocess, "run", lambda argv, **kw: calls.append(argv))
    return pt, calls

def test_open_and_reveal_file_on_mac(monkeypatch):
    pt, calls = _commands(monkeypatch, "darwin")
    pt.open_file("/v/game.mp4")
    pt.reveal_file("/v/game.mp4")
    assert calls == [["open", "/v/game.mp4"], ["open", "-R", "/v/game.mp4"]]

def test_open_and_reveal_file_on_windows(monkeypatch):
    pt, calls = _commands(monkeypatch, "win32")
    pt.open_file("C:\\v\\game.mp4")
    pt.reveal_file("C:\\v\\game.mp4")
    assert calls == [["explorer", "C:\\v\\game.mp4"], ["explorer", "/select,C:\\v\\game.mp4"]]

def test_windows_notification_uses_the_built_in_toast(monkeypatch):
    from trace_grabber import platform_tasks as pt
    monkeypatch.setattr(pt.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(pt.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)))
    pt.notify("Saved vs O'Brien's \"XI\" <b>")
    (argv, kw), = calls
    script = argv[-1]
    assert argv[0] == "powershell" and "ToastNotificationManager" in script
    assert "BurntToast" not in script
    # The message travels in the environment, never inside the script text.
    assert "O'Brien" not in script
    assert kw["env"]["TRACEDOWN_MESSAGE"] == "Saved vs O'Brien's \"XI\" <b>"

def test_start_at_login_on_mac_writes_a_launch_agent(monkeypatch, tmp_path):
    from trace_grabber import platform_tasks as pt, paths
    monkeypatch.setattr(pt.sys, "platform", "darwin")
    monkeypatch.setattr(pt, "LOGIN_AGENT", tmp_path / "com.tracedownloader.login.plist")
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(pt.sys, "executable", "/Applications/TraceDown.app/Contents/MacOS/TraceDown")
    assert pt.login_enabled() is False
    pt.login_enable()
    text = (tmp_path / "com.tracedownloader.login.plist").read_text()
    assert "<key>RunAtLoad</key><true/>" in text and "--background" in text
    assert "/Applications/TraceDown.app/Contents/MacOS/TraceDown" in text
    assert pt.login_enabled() is True
    pt.login_disable()
    assert pt.login_enabled() is False

def test_start_at_login_on_windows_uses_the_users_run_key(monkeypatch):
    from trace_grabber import platform_tasks as pt, paths
    monkeypatch.setattr(pt.sys, "platform", "win32")
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(pt.sys, "executable", "C:\\Users\\Jo Bloggs\\AppData\\Local\\Programs\\TraceDown\\TraceDown.exe")
    calls = []
    monkeypatch.setattr(pt.subprocess, "run", lambda argv, **kw: calls.append(argv) or type("R", (), {"returncode": 0})())
    pt.login_enable()
    pt.login_disable()
    assert pt.login_enabled() is True
    add, delete, query = calls
    assert add[:2] == ["reg", "add"] and "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in add
    assert add[add.index("/d") + 1] == '"C:\\Users\\Jo Bloggs\\AppData\\Local\\Programs\\TraceDown\\TraceDown.exe" --background'
    assert delete[:2] == ["reg", "delete"] and query[:2] == ["reg", "query"]


import sys
from types import SimpleNamespace

import pytest


def _fake_mac_file_manager(monkeypatch, pt, answer):
    asked = []
    class Manager:
        def trashItemAtURL_resultingItemURL_error_(self, url, resulting, error):
            asked.append(url)
            return answer
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSFileManager=SimpleNamespace(defaultManager=lambda: Manager()),
        NSURL=SimpleNamespace(fileURLWithPath_=lambda path: "url:" + path)))
    monkeypatch.setattr(pt.sys, "platform", "darwin")
    return asked


def test_removing_goes_to_the_mac_trash_not_to_deletion(monkeypatch, tmp_path):
    from trace_grabber import platform_tasks as pt
    asked = _fake_mac_file_manager(monkeypatch, pt, (True, None, None))
    video = tmp_path / "game.mp4"
    video.write_bytes(b"x")
    pt.trash([video, tmp_path / "already gone.mp4"])
    assert asked == ["url:" + str(video)] and video.exists()        # the fake moved nothing; trash() itself never deletes
    assert pt.bin_name() == "Trash"


def test_a_trash_that_refuses_is_an_error_naming_the_file(monkeypatch, tmp_path):
    from trace_grabber import platform_tasks as pt
    _fake_mac_file_manager(monkeypatch, pt, (False, None, "the volume has no Trash"))
    video = tmp_path / "game.mp4"
    video.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="Couldn't move game.mp4 to the Trash"):
        pt.trash([video])


def test_removal_is_not_offered_on_windows_until_it_is_proven_safe_there(monkeypatch, tmp_path):
    # Windows' own "send to the Recycle Bin" call deletes for good, without asking, when a
    # drive has no bin (a network share, a memory card) or the folder is too big for it.
    from trace_grabber import platform_tasks as pt
    monkeypatch.setattr(pt.sys, "platform", "win32")
    monkeypatch.setattr(pt.subprocess, "run", lambda *a, **k: pytest.fail("nothing may be run"))
    folder = tmp_path / "2026-06-04_vs-rovers"
    folder.mkdir()
    assert pt.can_trash() is False
    with pytest.raises(RuntimeError, match="isn't available on Windows yet"):
        pt.trash([folder])
    assert folder.exists()
    monkeypatch.setattr(pt.sys, "platform", "darwin")
    assert pt.can_trash() is True
