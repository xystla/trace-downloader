import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

GB = 1_000_000_000


@pytest.fixture
def lib(monkeypatch, tmp_path):
    """A worker whose library is tmp_path/library and whose data is tmp_path/data.
    The Trash is faked: `lib.trashed` records what was sent there, and the fake
    really moves it aside so the tests can see the library afterwards."""
    from trace_grabber import paths
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "data_dir", lambda: data)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", data)
    root = tmp_path / "library"
    root.mkdir()
    w = worker.Worker.__new__(worker.Worker)
    w._accounts = SimpleNamespace(active=SimpleNamespace(
        id="demo", label="Tiger Sharks", output_dir=lambda base: root, state_path=lambda r: data / "state.json"))
    w._cfg = SimpleNamespace(output_dir=root, combine_halves=False, quality="highest", file_name="")
    w._cancel = threading.Event()
    w.module, w.root, w.data = worker, root, data
    w.game = SimpleNamespace(id="demo-7", date="2026-09-22", opponent="Rivals", title="T vs. Rivals")
    w.other = SimpleNamespace(id="demo-8", date="2026-09-29", opponent="United", title="T vs. United")
    w.trashed = []
    w.trash_refuses = False
    def trash(paths_):
        if w.trash_refuses:
            raise RuntimeError("Couldn't move it to the Trash: no permission")
        bin_ = tmp_path / "bin"
        bin_.mkdir(exist_ok=True)
        for p in paths_:
            w.trashed.append(Path(p))
            Path(p).rename(bin_ / f"{len(w.trashed)}-{Path(p).name}")
    monkeypatch.setattr(worker.platform_tasks, "trash", trash)
    monkeypatch.setattr(worker.space, "free", lambda folder: 50 * GB)
    return w


def _put(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _saved(lib, *ids):
    (lib.data / "state.json").write_text(json.dumps(sorted(ids)))


def _done(lib):
    path = lib.data / "state.json"
    return set(json.loads(path.read_text())) if path.exists() else set()


def _full(lib, name="2026-09-22_vs-rivals.mp4", size=1000):
    return _put(lib.root / "2026-09-22_vs-rivals" / "Full Game" / name, size)


def test_a_saved_game_whose_video_is_gone_is_missing(lib):
    _saved(lib, "demo-7", "demo-8")
    _put(lib.root / "2026-09-29_vs-united.mp4")                       # demo-8, an older loose file
    assert lib.missing([lib.game, lib.other], {"demo-7", "demo-8"}) == {"demo-7"}
    assert lib.missing([lib.game], set()) == set()                    # never saved: not missing, just new


def test_pointing_at_a_moved_video_makes_the_game_saved_again(lib, tmp_path):
    _saved(lib, "demo-7")
    moved = _put(tmp_path / "external" / "rivals.mp4")
    assert lib.set_found("demo-7", [str(moved)]) is True
    assert lib.missing([lib.game], {"demo-7"}) == set()
    assert lib.game_files("demo-7", "2026-09-22", "Rivals") == [str(moved)]
    assert lib._game_media("demo-7", "2026-09-22", "Rivals")["full"] == [str(moved)]


def test_a_found_video_on_a_drive_that_is_not_connected_is_missing_until_it_is(lib, tmp_path):
    _saved(lib, "demo-7")
    moved = tmp_path / "external" / "rivals.mp4"
    lib.set_found("demo-7", [str(moved)])
    assert lib.missing([lib.game], {"demo-7"}) == {"demo-7"}
    _put(moved)
    assert lib.missing([lib.game], {"demo-7"}) == set()


def test_a_video_in_the_library_wins_over_a_found_one(lib, tmp_path):
    here = _full(lib)
    lib.set_found("demo-7", [str(_put(tmp_path / "external" / "rivals.mp4"))])
    assert lib.game_files("demo-7", "2026-09-22", "Rivals") == [str(here)]


def test_storage_lists_each_game_with_what_it_takes(lib):
    _saved(lib, "demo-7")
    _full(lib, size=1000)
    _put(lib.root / "2026-09-22_vs-rivals" / "Highlights" / "01.mp4", 100)
    _put(lib.root / "2026-09-29_vs-united.mp4", 400)
    _put(lib.root / "someone elses notes.txt", 25)
    third = SimpleNamespace(id="demo-9", date="2026-10-01", opponent="Athletic", title="T vs. Athletic")
    report = lib.storage([lib.other, lib.game, third])
    assert [(r["id"], r["title"], r["saved"], r["full"], r["total"]) for r in report["rows"]] == [
        ("demo-7", "vs Rivals", True, 1000, 1100), ("demo-8", "vs United", False, 400, 400)]
    assert (report["used"], report["other"], report["free"]) == (1525, 25, 50 * GB)


def test_removing_the_full_game_keeps_the_rest_and_un_saves_it(lib):
    _saved(lib, "demo-7", "demo-8")
    _full(lib, size=1000)
    clip = _put(lib.root / "2026-09-22_vs-rivals" / "Highlights" / "01.mp4", 100)
    assert lib.remove_game("demo-7", "2026-09-22", "Rivals", False) == 1000
    assert lib.trashed == [lib.root / "2026-09-22_vs-rivals" / "Full Game"]
    assert clip.exists() and _done(lib) == {"demo-8"}


def test_removing_everything_takes_the_whole_game(lib):
    _saved(lib, "demo-7")
    _full(lib, size=1000)
    _put(lib.root / "2026-09-22_vs-rivals" / "Bookmarks" / "bookmarks.json", 5)
    _put(lib.root / "2026-09-22_vs-rivals_highlights" / "old.mp4", 50)
    assert lib.remove_game("demo-7", "2026-09-22", "Rivals", True) == 1055
    assert lib.trashed == [lib.root / "2026-09-22_vs-rivals", lib.root / "2026-09-22_vs-rivals_highlights"]
    assert _done(lib) == set() and list(lib.root.iterdir()) == []


def test_a_video_found_elsewhere_is_forgotten_not_trashed(lib, tmp_path):
    _saved(lib, "demo-7")
    moved = _put(tmp_path / "external" / "rivals.mp4", 900)
    lib.set_found("demo-7", [str(moved)])
    _put(lib.root / "2026-09-22_vs-rivals" / "Highlights" / "01.mp4", 100)
    assert lib.remove_game("demo-7", "2026-09-22", "Rivals", False) == 0
    assert lib.trashed == [] and moved.exists()
    assert lib.game_files("demo-7", "2026-09-22", "Rivals") == [] and _done(lib) == set()
    lib.set_found("demo-7", [str(moved)])
    lib.remove_game("demo-7", "2026-09-22", "Rivals", True)
    assert lib.trashed == [lib.root / "2026-09-22_vs-rivals"] and moved.exists()


def test_when_the_trash_refuses_nothing_is_forgotten(lib):
    _saved(lib, "demo-7")
    video = _full(lib)
    lib.trash_refuses = True
    with pytest.raises(RuntimeError, match="Couldn't move it to the Trash"):
        lib.remove_game("demo-7", "2026-09-22", "Rivals", True)
    assert video.exists() and _done(lib) == {"demo-7"}


def test_a_game_that_is_downloading_cannot_be_removed(lib):
    _full(lib)
    lib._downloading = "demo-7"
    with pytest.raises(RuntimeError, match="is downloading"):
        lib.remove_game("demo-7", "2026-09-22", "Rivals", False)
    assert lib.trashed == []


def test_new_downloads_take_the_persons_file_name(lib):
    lib._cfg.file_name = "{team} vs {opponent} {date}"
    dests = lib._half_dests("demo-7", "2026-09-22", "Rivals")
    assert [d.name for d in dests] == ["Tiger Sharks vs Rivals 2026-09-22_half1.mp4",
                                       "Tiger Sharks vs Rivals 2026-09-22_half2.mp4"]
    assert dests[0].parent == lib.root / "2026-09-22_vs-rivals" / "Full Game"        # the folder keeps its name
    assert lib.team_label() == "Tiger Sharks"


def test_a_download_begun_under_the_old_name_carries_on_there(lib):
    old = lib.root / "2026-09-22_vs-rivals" / "Full Game" / "2026-09-22_vs-rivals_half1.mp4"
    _put(old)
    (old.parent / ".2026-09-22_vs-rivals_half1.done").write_text(json.dumps({"owner": "demo-7", "quality": "highest"}))
    lib._cfg.file_name = "{team} vs {opponent}"                       # changed while half 2 was still to come
    dests = lib._half_dests("demo-7", "2026-09-22", "Rivals")
    assert [d.name for d in dests] == ["2026-09-22_vs-rivals_half1.mp4", "2026-09-22_vs-rivals_half2.mp4"]      # one name for the pair
    assert lib._partials([lib.game], done=set()) == {"demo-7": 0.5}


def _begun_as(lib, stem, with_pieces_for_half_2=False):
    """Half 1 finished under `stem`; optionally half 2 partway, as pieces."""
    full = lib.root / "2026-09-22_vs-rivals" / "Full Game"
    _put(full / f"{stem}_half1.mp4")
    (full / f".{stem}_half1.done").write_text(json.dumps({"owner": "demo-7", "quality": "highest"}))
    if with_pieces_for_half_2:
        folder = full / f".{stem}_half2.pieces"
        _put(folder / "00000.ts")
        (folder / "info.json").write_text(json.dumps({"owner": "demo-7", "quality": "highest", "count": 2}))


def test_changing_from_one_pattern_to_another_mid_download_keeps_the_resume(lib):
    lib._cfg.file_name = "{team} vs {opponent}"
    _begun_as(lib, "Tiger Sharks vs Rivals", with_pieces_for_half_2=True)
    lib._cfg.file_name = "{opponent} {date}"
    assert [d.name for d in lib._half_dests("demo-7", "2026-09-22", "Rivals")] == [
        "Tiger Sharks vs Rivals_half1.mp4", "Tiger Sharks vs Rivals_half2.mp4"]
    assert lib._partials([lib.game], done=set()) == {"demo-7": 0.75}


def test_clearing_the_pattern_mid_download_keeps_the_resume(lib):
    lib._cfg.file_name = "{team} vs {opponent}"
    _begun_as(lib, "Tiger Sharks vs Rivals")
    lib._cfg.file_name = ""
    assert [d.name for d in lib._half_dests("demo-7", "2026-09-22", "Rivals")] == [
        "Tiger Sharks vs Rivals_half1.mp4", "Tiger Sharks vs Rivals_half2.mp4"]
    assert lib._partials([lib.game], done=set()) == {"demo-7": 0.5}


def test_a_game_that_shares_its_folder_with_another_cannot_be_removed_from_the_app(lib):
    # Two games on one day against the same opponent live in one folder: removing
    # "one" would take the other's video too.
    _saved(lib, "demo-7", "demo-6")
    _full(lib)
    twin = SimpleNamespace(id="demo-6", date="2026-09-22", opponent="Rivals", title="T vs. Rivals")
    for everything in (False, True):
        with pytest.raises(RuntimeError, match="shares its folder with vs Rivals"):
            lib.remove_game("demo-7", "2026-09-22", "Rivals", everything, games=[lib.game, twin, lib.other])
    assert lib.trashed == [] and _done(lib) == {"demo-6", "demo-7"}
    lib.remove_game("demo-7", "2026-09-22", "Rivals", False, games=[lib.game, lib.other])      # alone in its folder: fine
    assert len(lib.trashed) == 1


def test_a_game_whose_folder_cannot_be_told_apart_from_the_library_is_never_removed(lib):
    _full(lib)
    with pytest.raises(RuntimeError, match="nothing was removed"):
        lib.remove_game("demo-7", ".", None, True)
    assert lib.trashed == []


def test_storage_says_whether_removal_is_possible_for_each_row(lib):
    _full(lib)
    twin = SimpleNamespace(id="demo-6", date="2026-09-22", opponent="Rivals", title="T vs. Rivals")
    rows = {r["id"]: r["shared"] for r in lib.storage([lib.game, twin])["rows"]}
    assert rows == {"demo-7": True, "demo-6": True}
    assert lib.storage([lib.game])["rows"][0]["shared"] is False
