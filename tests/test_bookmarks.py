import json

from trace_grabber import bookmarks


def test_a_game_starts_with_no_bookmarks(tmp_path):
    assert bookmarks.load(tmp_path / "2026-06-04_vs-rovers") == []


def test_bookmarks_are_kept_in_the_games_own_folder_in_match_order(tmp_path):
    late = bookmarks.add(tmp_path, 2400.26, 2, "Late press")
    early = bookmarks.add(tmp_path, 95, 1)
    assert (tmp_path / "Bookmarks" / "bookmarks.json").exists()
    saved = bookmarks.load(tmp_path)
    assert [b["id"] for b in saved] == [early["id"], late["id"]]
    assert saved[1] == {"id": late["id"], "t": 2400.3, "half": 2, "note": "Late press", "made": late["made"]}
    assert early["note"] == "" and early["id"] != late["id"] and len(late["made"]) == 10


def test_a_note_can_be_changed_and_a_bookmark_deleted(tmp_path):
    a = bookmarks.add(tmp_path, 10, 1, "first")
    b = bookmarks.add(tmp_path, 20, 1)
    assert bookmarks.edit(tmp_path, b["id"], "second") is True
    assert bookmarks.remove(tmp_path, a["id"]) is True
    assert [(x["t"], x["note"]) for x in bookmarks.load(tmp_path)] == [(20.0, "second")]
    assert bookmarks.edit(tmp_path, "nope", "x") is False and bookmarks.remove(tmp_path, "nope") is False


def test_notes_are_tidied_and_kept_short(tmp_path):
    made = bookmarks.add(tmp_path, 5, 1, "  good   press\nfrom the\tfront  ")
    assert made["note"] == "good press from the front"
    assert len(bookmarks.add(tmp_path, 6, 1, "x" * 500)["note"]) == bookmarks.NOTE_MAX
    assert bookmarks.add(tmp_path, 7, 1, None)["note"] == ""


def test_a_half_that_makes_no_sense_counts_as_the_first(tmp_path):
    assert bookmarks.add(tmp_path, 5, 0)["half"] == 1 and bookmarks.add(tmp_path, 6, "2")["half"] == 2


def test_a_damaged_file_reads_as_no_bookmarks_and_is_repaired_by_the_next_save(tmp_path):
    folder = tmp_path / "Bookmarks"
    folder.mkdir()
    (folder / "bookmarks.json").write_text("{not json")
    assert bookmarks.load(tmp_path) == []
    bookmarks.add(tmp_path, 12, 1, "kept")
    assert [b["note"] for b in json.loads((folder / "bookmarks.json").read_text())] == ["kept"]


def test_entries_that_are_not_bookmarks_are_left_out(tmp_path):
    folder = tmp_path / "Bookmarks"
    folder.mkdir()
    (folder / "bookmarks.json").write_text(json.dumps([
        {"id": "a1", "t": 30, "half": 1, "note": "fine", "made": "2026-10-07"},
        {"id": "a2", "half": 1},                      # no time
        {"t": 40},                                    # no id
        "junk",
        {"id": "a3", "t": "soon"},                    # time isn't a number
        {"id": "a4", "t": 12, "note": 7},             # note isn't text
    ]))
    assert [(b["id"], b["note"], b["half"]) for b in bookmarks.load(tmp_path)] == [("a4", "", 1), ("a1", "fine", 1)]
    (folder / "bookmarks.json").write_text(json.dumps({"id": "a1", "t": 30}))      # not a list at all
    assert bookmarks.load(tmp_path) == []


def test_saving_never_leaves_a_half_written_file(tmp_path):
    bookmarks.add(tmp_path, 1, 1)
    assert sorted(p.name for p in (tmp_path / "Bookmarks").iterdir()) == ["bookmarks.json"]
