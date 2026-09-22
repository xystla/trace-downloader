from pathlib import Path
from trace_grabber.combine import build_concat_cmd

def test_build_concat_cmd():
    cmd = build_concat_cmd([Path("/v/a.mp4"), Path("/v/b.mp4")],
                           Path("/v/out.mp4"), Path("/tmp/list.txt"))
    assert cmd[0] == "ffmpeg"
    assert "concat" in cmd and "-safe" in cmd and "0" in cmd
    assert str(Path("/tmp/list.txt")) in cmd
    assert "copy" in cmd
    assert str(Path("/v/out.mp4")) in cmd


def test_windows_concat_path():
    from pathlib import PureWindowsPath
    from trace_grabber.combine import concat_entry
    assert concat_entry(PureWindowsPath("C:/Users/José O'Brien/Trace Videos/a.mp4")) == (
        "file 'C:/Users/José O'\\''Brien/Trace Videos/a.mp4'\n"
    )


def test_combine_unicode_and_apostrophe(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("trace_grabber.combine")
    source = tmp_path / "José O'Brien.mp4"
    source.write_bytes(b"part")
    dest = tmp_path / "out.mp4"
    lists = []
    def run(cmd, **kwargs):
        from types import SimpleNamespace
        manifest = Path(cmd[cmd.index("-i") + 1])
        lists.append(manifest)
        assert manifest.read_text(encoding="utf-8") == module.concat_entry(source.resolve())
        dest.write_bytes(b"combined")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, "run", run)
    module.combine([source], dest)
    assert dest.read_bytes() == b"combined"
    assert not lists[0].exists()


def test_real_ffmpeg_combines_special_paths(tmp_path):
    import shutil
    import subprocess
    import pytest
    from trace_grabber.combine import combine
    from trace_grabber.tools import ffmpeg_path, subprocess_flags
    ffmpeg = ffmpeg_path()
    if not shutil.which(ffmpeg):
        pytest.skip("FFmpeg is not installed")
    folder = tmp_path / "José O'Brien" / "Trace Videos"
    folder.mkdir(parents=True)
    source = folder / "half 1.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=s=16x16:d=0.1",
                    "-c:v", "mpeg4", str(source)], check=True, capture_output=True,
                   **subprocess_flags())
    dest = folder / "combined.mp4"
    combine([source, source], dest)
    subprocess.run([ffmpeg, "-v", "error", "-i", str(dest), "-f", "null", "-"],
                   check=True, capture_output=True, **subprocess_flags())
