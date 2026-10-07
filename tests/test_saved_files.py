from trace_grabber.naming import saved_files


def _touch(folder, *names):
    for name in names:
        (folder / name).write_bytes(b"")


def test_combined_file_comes_before_halves(tmp_path):
    _touch(tmp_path, "2026-06-04_vs-rovers_half1.mp4", "2026-06-04_vs-rovers_half2.mp4",
           "2026-06-04_vs-rovers.mp4")
    assert [p.name for p in saved_files(tmp_path, "2026-06-04", "Rovers")] == [
        "2026-06-04_vs-rovers.mp4", "2026-06-04_vs-rovers_half1.mp4",
        "2026-06-04_vs-rovers_half2.mp4"]


def test_other_games_on_the_same_day_are_not_matched(tmp_path):
    _touch(tmp_path, "2026-06-04_vs-rovers.mp4", "2026-06-04_vs-rovers-reserves.mp4",
           "2026-06-04_vs-united.mp4", "2026-06-04_vs-rovers.txt")
    assert [p.name for p in saved_files(tmp_path, "2026-06-04", "Rovers")] == ["2026-06-04_vs-rovers.mp4"]


def test_redownloaded_copies_are_matched(tmp_path):
    _touch(tmp_path, "2026-06-04_vs-rovers.mp4", "2026-06-04_vs-rovers-2.mp4")
    assert len(saved_files(tmp_path, "2026-06-04", "Rovers")) == 2


def test_missing_folder_or_game_gives_nothing(tmp_path):
    assert saved_files(tmp_path / "nowhere", "2026-06-04", "Rovers") == []
    assert saved_files(tmp_path, "2026-06-04", None) == []


def test_each_game_gets_one_folder_with_three_inside(tmp_path):
    from trace_grabber.naming import game_folders
    folders = game_folders(tmp_path, "2026-06-04", "Rovers")
    game = tmp_path / "2026-06-04_vs-rovers"
    assert folders.full_game == game / "Full Game"
    assert folders.highlights == game / "Highlights"
    assert folders.players == game / "Player Highlights"
    assert game_folders(tmp_path, "2026-06-04", None).root == tmp_path / "2026-06-04"


def test_videos_are_found_in_the_games_full_game_folder(tmp_path):
    from trace_grabber.naming import game_folders
    full = game_folders(tmp_path, "2026-06-04", "Rovers").full_game
    full.mkdir(parents=True)
    _touch(full, "2026-06-04_vs-rovers_half2.mp4", "2026-06-04_vs-rovers.mp4")
    assert saved_files(tmp_path, "2026-06-04", "Rovers") == [
        full / "2026-06-04_vs-rovers.mp4", full / "2026-06-04_vs-rovers_half2.mp4"]


def test_videos_saved_by_older_versions_are_still_found(tmp_path):
    _touch(tmp_path, "2026-06-04_vs-rovers.mp4")           # loose in the team folder
    assert saved_files(tmp_path, "2026-06-04", "Rovers") == [tmp_path / "2026-06-04_vs-rovers.mp4"]


def test_older_highlights_folder_is_still_known(tmp_path):
    from trace_grabber.naming import game_folders
    assert game_folders(tmp_path, "2026-06-04", "Rovers").legacy_highlights == \
        tmp_path / "2026-06-04_vs-rovers_highlights"


def test_any_video_in_the_games_own_folder_is_its_video(tmp_path):
    from trace_grabber.naming import game_folders
    full = game_folders(tmp_path, "2026-06-04", "Rovers").full_game
    full.mkdir(parents=True)
    _touch(full, "Tiger Sharks vs Rovers_half2.mp4", "Tiger Sharks vs Rovers_half1.mp4")
    assert [p.name for p in saved_files(tmp_path, "2026-06-04", "Rovers")] == [
        "Tiger Sharks vs Rovers_half1.mp4", "Tiger Sharks vs Rovers_half2.mp4"]
    _touch(full, "renamed by hand.mp4")
    assert saved_files(tmp_path, "2026-06-04", "Rovers")[0].name == "renamed by hand.mp4"      # one file before halves


def test_unfinished_and_hidden_files_are_not_videos(tmp_path):
    from trace_grabber.naming import game_folders
    full = game_folders(tmp_path, "2026-06-04", "Rovers").full_game
    full.mkdir(parents=True)
    _touch(full, "2026-06-04_vs-rovers.part.mp4", ".hidden.mp4", "notes.txt")
    (full / ".2026-06-04_vs-rovers_half1.pieces").mkdir()
    assert saved_files(tmp_path, "2026-06-04", "Rovers") == []
