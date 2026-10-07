import json
from pathlib import Path

import pytest

from trace_grabber import pieces


class _Trace:
    """Stands in for Trace's servers and for ffmpeg. `fail` maps a piece address
    to how many times it fails first (None = always); `asked` records fetches."""

    def __init__(self, monkeypatch):
        self.asked, self.fail, self.joined, self.join_code = [], {}, [], 0
        monkeypatch.setattr(pieces, "_get", self.get)
        monkeypatch.setattr(pieces, "PAUSE", 0)
        monkeypatch.setattr(pieces.subprocess, "Popen", self.popen)

    def get(self, url, headers, timeout=30):
        self.asked.append(url)
        left = self.fail.get(url, 0)
        if left is None or left > 0:
            if left:
                self.fail[url] = left - 1
            raise OSError("connection reset")
        return b"<" + url.encode() + b">"

    def popen(self, cmd, **kwargs):
        trace = self
        playlist = Path(cmd[cmd.index("-i") + 1])
        trace.joined.append([line for line in playlist.read_text().splitlines() if line.endswith(".ts")])

        class Proc:
            returncode = trace.join_code
            def wait(self):
                if trace.join_code == 0:
                    folder = playlist.parent
                    Path(cmd[-1]).write_bytes(b"".join((folder / name).read_bytes() for name in trace.joined[-1]))
                return trace.join_code
        return Proc()


def _parts(*names):
    return [(2.0, f"https://t/{name}.ts") for name in names]


@pytest.fixture
def trace(monkeypatch):
    return _Trace(monkeypatch)


def test_every_piece_is_fetched_and_joined_in_order(trace, tmp_path):
    dest = tmp_path / "Full Game" / "game_half1.mp4"
    pieces.fetch(_parts("a", "b", "c"), dest, {"Cookie": "s=1"}, "highest", workers=1)
    assert dest.read_bytes() == b"<https://t/a.ts><https://t/b.ts><https://t/c.ts>"
    assert trace.joined == [["00000.ts", "00001.ts", "00002.ts"]]
    # The pieces folder is gone; a small record says which download finished this half.
    assert sorted(p.name for p in dest.parent.iterdir()) == [".game_half1.done", "game_half1.mp4"]


def test_pieces_already_on_disk_are_not_fetched_again(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.fail["https://t/c.ts"] = None                       # the connection drops at the third piece
    with pytest.raises(RuntimeError, match="connection dropped"):
        pieces.fetch(_parts("a", "b", "c"), dest, {}, "highest", workers=1)
    assert not dest.exists() and pieces.progress_of(dest) == pytest.approx(2 / 3)
    trace.fail.clear()
    trace.asked.clear()
    pieces.fetch(_parts("a", "b", "c"), dest, {}, "highest", workers=1)
    assert trace.asked == ["https://t/c.ts"]
    assert dest.read_bytes() == b"<https://t/a.ts><https://t/b.ts><https://t/c.ts>"


def test_resume_goes_by_position_when_trace_hands_out_new_addresses(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.fail["https://t/b.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    trace.asked.clear()
    pieces.fetch([(2.0, "https://new/a.ts?sig=2"), (2.0, "https://new/b.ts?sig=2")], dest, {}, "highest", workers=1)
    assert trace.asked == ["https://new/b.ts?sig=2"]


def test_a_piece_is_tried_three_times_before_giving_up(trace, tmp_path):
    trace.fail["https://t/a.ts"] = 2                          # fails twice, then works
    pieces.fetch(_parts("a"), tmp_path / "ok.mp4", {}, "highest", workers=1)
    assert trace.asked.count("https://t/a.ts") == 3
    trace.fail["https://t/b.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("b"), tmp_path / "bad.mp4", {}, "highest", workers=1)
    assert trace.asked.count("https://t/b.ts") == 3


def test_a_stop_keeps_what_was_fetched(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    stop = lambda: len(trace.asked) >= 2                      # asked to stop after two pieces
    with pytest.raises(pieces.Stopped):
        pieces.fetch(_parts("a", "b", "c", "d"), dest, {}, "highest", should_stop=stop, workers=1)
    assert not dest.exists() and trace.joined == []
    assert pieces.progress_of(dest) == pytest.approx(0.5)


def test_changing_quality_starts_the_half_afresh(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.fail["https://t/b.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    trace.fail.clear()
    trace.asked.clear()
    pieces.fetch(_parts("a", "b"), dest, {}, "1000k", workers=1)
    assert trace.asked == ["https://t/a.ts", "https://t/b.ts"]


def test_a_different_number_of_pieces_starts_the_half_afresh(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.fail["https://t/b.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    trace.fail.clear()
    trace.asked.clear()
    pieces.fetch(_parts("a", "b", "c"), dest, {}, "highest", workers=1)
    assert len(trace.asked) == 3


def test_a_piece_cut_off_mid_write_is_fetched_again(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    folder = pieces.folder_for(dest)
    folder.mkdir()
    (folder / "info.json").write_text(json.dumps({"owner": "", "quality": "highest", "count": 2}))
    (folder / "00000.ts.tmp").write_bytes(b"half a pie")
    pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    assert sorted(trace.asked) == ["https://t/a.ts", "https://t/b.ts"]


def test_a_failed_join_keeps_the_pieces_so_only_the_join_is_redone(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.join_code = 1
    with pytest.raises(RuntimeError, match="together"):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    assert not dest.exists() and pieces.progress_of(dest) == 1.0
    assert [p.name for p in tmp_path.iterdir()] == [".game_half1.pieces"]      # no half-written video
    trace.join_code = 0
    trace.asked.clear()
    pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    assert trace.asked == [] and dest.exists()


def test_progress_counts_bytes_and_includes_what_was_already_there(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.fail["https://t/c.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("a", "b", "c"), dest, {}, "highest", workers=1)
    trace.fail.clear()
    seen = []
    pieces.fetch(_parts("a", "b", "c"), dest, {}, "highest", workers=1,
                 on_progress=lambda *numbers: seen.append(numbers))
    size = len(b"<https://t/a.ts>")
    assert seen == [(2 * size, 3 * size, 2, 3), (3 * size, 3 * size, 3, 3)]


def test_a_full_disk_fails_at_once_with_the_real_reason(trace, tmp_path, monkeypatch):
    dest = tmp_path / "game_half1.mp4"
    def no_room(path, data):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(pieces, "_write", no_room)
    with pytest.raises(OSError, match="No space left"):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    assert trace.asked.count("https://t/a.ts") == 1           # not retried: it isn't the connection


def test_a_half_with_no_pieces_is_an_error_not_an_empty_video(trace, tmp_path):
    with pytest.raises(RuntimeError, match="no video"):
        pieces.fetch([], tmp_path / "game_half1.mp4", {}, "highest")
    assert list(tmp_path.iterdir()) == []


def test_discard_removes_a_cut_off_download(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    assert pieces.progress_of(dest) is None and pieces.bytes_on_disk(dest) == 0
    trace.fail["https://t/b.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", workers=1)
    assert pieces.bytes_on_disk(dest) == len(b"<https://t/a.ts>")
    pieces.discard(dest)
    assert pieces.progress_of(dest) is None and list(tmp_path.iterdir()) == []


def test_stop_can_end_the_join(trace, tmp_path):
    procs = []
    pieces.fetch(_parts("a"), tmp_path / "g.mp4", {}, "highest", on_proc=procs.append, workers=1)
    assert len(procs) == 1


def test_the_real_reason_a_piece_failed_is_kept_for_the_log(trace, tmp_path, caplog):
    trace.fail["https://t/a.ts"] = None
    with caplog.at_level("INFO"), pytest.raises(RuntimeError) as dropped:
        pieces.fetch(_parts("a"), tmp_path / "g.mp4", {}, "highest", workers=1)
    assert isinstance(dropped.value.__cause__, OSError) and "connection reset" in str(dropped.value.__cause__)
    assert "connection reset" in caplog.text


class _Store:
    """Stands in for Python's certificate store: `known` is how many it starts with."""
    def __init__(self, known):
        self.known, self.loaded = known, []
    def cert_store_stats(self):
        return {"x509_ca": self.known}
    def load_verify_locations(self, cadata=None):
        self.loaded.append(cadata)


def test_certificates_come_from_the_mac_keychain_when_python_has_none(monkeypatch):
    # The packaged Mac app's Python ships without certificates, so HTTPS to Trace
    # would fail to verify; the system's own are used instead.
    store = _Store(known=0)
    monkeypatch.setattr(pieces, "_CONTEXT", None)
    monkeypatch.setattr(pieces.ssl, "create_default_context", lambda: store)
    monkeypatch.setattr(pieces.sys, "platform", "darwin")
    asked = []
    def run(cmd, **kwargs):
        asked.append(cmd)
        return type("Done", (), {"returncode": 0, "stdout": "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n"})()
    monkeypatch.setattr(pieces.subprocess, "run", run)
    assert pieces._context() is store and pieces._context() is store        # made once
    assert len(asked) == 1 and asked[0][0] == "security"
    assert store.loaded == ["-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n"]


def test_pythons_own_certificates_are_used_when_it_has_them(monkeypatch):
    store = _Store(known=140)
    monkeypatch.setattr(pieces, "_CONTEXT", None)
    monkeypatch.setattr(pieces.ssl, "create_default_context", lambda: store)
    monkeypatch.setattr(pieces.sys, "platform", "darwin")
    monkeypatch.setattr(pieces.subprocess, "run", lambda *a, **k: pytest.fail("the keychain was not needed"))
    assert pieces._context() is store and store.loaded == []


def test_a_finished_half_is_known_by_its_game_and_quality(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    assert pieces.finished(dest, "g-1", "highest") is False
    pieces.fetch(_parts("a"), dest, {}, "highest", owner="g-1", workers=1)
    assert pieces.finished(dest, "g-1", "highest") is True
    assert pieces.finished(dest, "g-2", "highest") is False                 # another game with the same name
    assert pieces.finished(dest, "g-1", "1000k") is False                   # the quality was changed since
    assert pieces.belongs(dest, "g-1") and not pieces.belongs(dest, "g-2")
    pieces.forget(dest)                                                     # the game is saved: it is just a video now
    assert dest.exists() and not pieces.belongs(dest, "g-1")
    assert [p.name for p in tmp_path.iterdir()] == ["game_half1.mp4"]


def test_a_video_without_a_record_is_never_taken_for_a_finished_half(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    dest.write_bytes(b"saved by hand or by an older version")
    assert pieces.finished(dest, "g-1", "highest") is False and not pieces.belongs(dest, "g-1")


def test_pieces_of_another_game_with_the_same_name_are_not_reused(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    trace.fail["https://t/b.ts"] = None
    with pytest.raises(RuntimeError):
        pieces.fetch(_parts("a", "b"), dest, {}, "highest", owner="g-1", workers=1)
    assert pieces.progress_of(dest, owner="g-1", quality="highest") == 0.5
    assert pieces.progress_of(dest, owner="g-2", quality="highest") is None
    assert pieces.progress_of(dest, owner="g-1", quality="1000k") is None
    assert pieces.belongs(dest, "g-1") and not pieces.belongs(dest, "g-2")
    trace.fail.clear()
    trace.asked.clear()
    pieces.fetch(_parts("a", "b"), dest, {}, "highest", owner="g-2", workers=1)
    assert trace.asked == ["https://t/a.ts", "https://t/b.ts"]


def test_discard_also_forgets_a_finished_half(trace, tmp_path):
    dest = tmp_path / "game_half1.mp4"
    pieces.fetch(_parts("a"), dest, {}, "highest", owner="g-1", workers=1)
    pieces.discard(dest)
    assert not pieces.belongs(dest, "g-1") and [p.name for p in tmp_path.iterdir()] == ["game_half1.mp4"]
