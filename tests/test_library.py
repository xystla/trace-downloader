from trace_grabber import library
from trace_grabber.naming import game_folders


def _file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _game(tmp_path):
    """A game in the per-game layout with a bit of everything; returns (folders, videos)."""
    folders = game_folders(tmp_path, "2026-06-04", "Rovers")
    video = _file(folders.full_game / "2026-06-04_vs-rovers.mp4", 1000)
    _file(folders.highlights / "01_half1_04m55s_shot.mp4", 100)
    _file(folders.legacy_highlights / "02_old.mp4", 50)
    _file(folders.players / "player-07.mp4", 30)
    _file(folders.my_clips / "half1_00m10s-00m20s.mp4", 20)
    _file(folders.root / "Bookmarks" / "bookmarks.json", 5)
    _file(folders.full_game / ".2026-06-04_vs-rovers_half2.pieces" / "00000.ts", 7)
    return folders, [video]


def test_size_of_a_file_a_folder_and_nothing(tmp_path):
    _file(tmp_path / "a" / "one.bin", 10)
    _file(tmp_path / "a" / "deep" / "two.bin", 5)
    assert library.size_of(tmp_path / "a") == 15 and library.size_of(tmp_path / "a" / "one.bin") == 10
    assert library.size_of(tmp_path / "missing") == 0


def test_a_games_usage_is_split_by_what_it_is(tmp_path):
    folders, videos = _game(tmp_path)
    assert library.usage(folders, videos, tmp_path) == {
        "full": 1000, "highlights": 150, "recaps": 30, "mine": 20, "unfinished": 7,
        "total": 1000 + 100 + 50 + 30 + 20 + 5 + 7, "elsewhere": False}


def test_a_loose_older_video_counts_for_its_game(tmp_path):
    folders = game_folders(tmp_path, "2026-06-04", "Rovers")
    loose = _file(tmp_path / "2026-06-04_vs-rovers.mp4", 400)
    assert library.usage(folders, [loose], tmp_path)["full"] == 400
    assert library.usage(folders, [loose], tmp_path)["total"] == 400


def test_a_video_found_elsewhere_is_not_counted(tmp_path):
    library_root = tmp_path / "library"
    folders = game_folders(library_root, "2026-06-04", "Rovers")
    away = _file(tmp_path / "other drive" / "game.mp4", 900)
    use = library.usage(folders, [away], library_root)
    assert (use["full"], use["total"], use["elsewhere"]) == (0, 0, True)


def test_removing_the_full_game_takes_its_folder_and_leaves_the_rest(tmp_path):
    folders, videos = _game(tmp_path)
    assert library.targets(folders, videos, tmp_path, everything=False) == [folders.full_game]


def test_removing_the_full_game_of_an_older_layout_takes_the_loose_video(tmp_path):
    folders = game_folders(tmp_path, "2026-06-04", "Rovers")
    loose = _file(tmp_path / "2026-06-04_vs-rovers.mp4", 400)
    assert library.targets(folders, [loose], tmp_path, everything=False) == [loose]


def test_removing_everything_takes_the_folder_the_older_highlights_and_the_loose_video(tmp_path):
    folders, _ = _game(tmp_path)
    loose = _file(tmp_path / "2026-06-04_vs-rovers-2.mp4", 400)
    assert library.targets(folders, [loose], tmp_path, everything=True) == [
        folders.root, folders.legacy_highlights, loose]


def test_a_video_found_elsewhere_is_never_a_target(tmp_path):
    library_root = tmp_path / "library"
    folders = game_folders(library_root, "2026-06-04", "Rovers")
    _file(folders.highlights / "01.mp4", 10)
    away = _file(tmp_path / "other drive" / "game.mp4", 900)
    assert library.targets(folders, [away], library_root, everything=False) == []
    assert library.targets(folders, [away], library_root, everything=True) == [folders.root]
    # Not even through a path that climbs out of the library and back.
    sneaky = library_root / ".." / "other drive" / "game.mp4"
    assert library.targets(folders, [sneaky], library_root, everything=True) == [folders.root]


def test_nothing_on_disk_means_nothing_to_remove(tmp_path):
    folders = game_folders(tmp_path, "2026-06-04", "Rovers")
    assert library.targets(folders, [], tmp_path, everything=True) == []
