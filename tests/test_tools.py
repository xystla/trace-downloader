def test_ffmpeg_prefers_bundled(monkeypatch, tmp_path):
    from trace_grabber import tools, paths
    binp = tmp_path / "bin"; binp.mkdir(); (binp / tools._ffmpeg_name()).write_text("x")
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    assert tools.ffmpeg_path() == str(binp / tools._ffmpeg_name())

def test_ffmpeg_falls_back_to_which(monkeypatch, tmp_path):
    from trace_grabber import tools, paths
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(tools.shutil, "which", lambda n: "/somewhere/ffmpeg")
    assert tools.ffmpeg_path() == "/somewhere/ffmpeg"

def test_subprocess_flags_windows(monkeypatch):
    from trace_grabber import tools
    monkeypatch.setattr(tools.os, "name", "nt")
    # CREATE_NO_WINDOW only exists on Windows Python; provide it for the test.
    monkeypatch.setattr(tools.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert tools.subprocess_flags() == {"creationflags": 0x08000000}

def test_subprocess_flags_non_windows(monkeypatch):
    from trace_grabber import tools
    monkeypatch.setattr(tools.os, "name", "posix")
    assert tools.subprocess_flags() == {}

def test_setup_browser_env_prefers_bundled(monkeypatch, tmp_path):
    from trace_grabber import tools, paths
    env = {}
    monkeypatch.setattr(tools.os, "environ", env)
    (tmp_path / "ms-playwright" / "chromium-1234").mkdir(parents=True)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    tools.setup_browser_env()
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "ms-playwright")

def test_setup_browser_env_falls_back_to_data_dir(monkeypatch, tmp_path):
    from trace_grabber import tools, paths
    env = {}
    monkeypatch.setattr(tools.os, "environ", env)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path / "res")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    tools.setup_browser_env()
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "data" / "ms-playwright")

def test_setup_browser_env_falls_back_when_bundle_empty(monkeypatch, tmp_path):
    from trace_grabber import tools, paths
    env = {}
    monkeypatch.setattr(tools.os, "environ", env)
    (tmp_path / "ms-playwright").mkdir()  # exists but has no chromium-* => not usable
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    tools.setup_browser_env()
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "data" / "ms-playwright")

def test_setup_browser_env_noop_in_dev(monkeypatch):
    from trace_grabber import tools, paths
    env = {}
    monkeypatch.setattr(tools.os, "environ", env)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    tools.setup_browser_env()
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env


def test_a_video_only_gets_its_real_name_once_it_is_whole(tmp_path):
    from trace_grabber.tools import complete_or_nothing
    dest = tmp_path / "player-10.mp4"
    with complete_or_nothing(dest) as part:
        assert part.name == "player-10.part.mp4"
        part.write_bytes(b"video")
        assert not dest.exists()                 # still being written
    assert dest.read_bytes() == b"video" and not part.exists()


def test_an_interrupted_video_leaves_nothing_behind(tmp_path):
    import pytest
    from trace_grabber.tools import complete_or_nothing
    dest = tmp_path / "player-10.mp4"
    with pytest.raises(RuntimeError):
        with complete_or_nothing(dest) as part:
            part.write_bytes(b"half")
            raise RuntimeError("ffmpeg died")
    assert list(tmp_path.iterdir()) == []


def test_an_empty_result_is_a_failure_not_a_saved_video(tmp_path):
    import pytest
    from trace_grabber.tools import complete_or_nothing
    with pytest.raises(RuntimeError):
        with complete_or_nothing(tmp_path / "a.mp4") as part:
            part.write_bytes(b"")
    assert list(tmp_path.iterdir()) == []


def test_a_leftover_from_a_killed_run_is_cleared_before_trying_again(tmp_path):
    from trace_grabber.tools import complete_or_nothing
    (tmp_path / "a.part.mp4").write_bytes(b"stale")
    with complete_or_nothing(tmp_path / "a.mp4") as part:
        assert not part.exists()
        part.write_bytes(b"video")
    assert [p.name for p in tmp_path.iterdir()] == ["a.mp4"]


def test_browser_left_by_an_older_version_does_not_count_as_installed(tmp_path, monkeypatch):
    from trace_grabber import tools
    # After an update the app can carry a newer Playwright than the Chromium
    # downloaded for the previous version: that must trigger the download again,
    # not a launch that fails with "Executable doesn't exist".
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(tools, "_wanted_browser_folders", lambda: ["chromium-1243", "chromium_headless_shell-1243"])
    (tmp_path / "chromium-1223").mkdir()
    (tmp_path / "chromium_headless_shell-1223").mkdir()
    assert tools.chromium_installed() is False
    (tmp_path / "chromium-1243").mkdir()
    assert tools.chromium_installed() is False            # the headless one is what the app runs
    (tmp_path / "chromium_headless_shell-1243").mkdir()
    assert tools.chromium_installed() is True


def test_wanted_browser_folders_come_from_the_playwright_in_use():
    from trace_grabber import tools
    folders = tools._wanted_browser_folders()
    assert len(folders) == 2 and folders[0].startswith("chromium-") and folders[1].startswith("chromium_headless_shell-")
    assert folders[0].split("-")[1] == folders[1].split("-")[1]
