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
