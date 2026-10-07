from pathlib import Path
from trace_grabber.naming import build_path, combined_path

def test_basic_name(tmp_path):
    p = build_path(tmp_path, date="2026-06-04", half=1, opponent=None)
    assert p == tmp_path / "2026-06-04_half1.mp4"

def test_opponent_slugified(tmp_path):
    p = build_path(tmp_path, date="2026-06-04", half=2, opponent="FC Rivals!")
    assert p == tmp_path / "2026-06-04_vs-fc-rivals_half2.mp4"

def test_collision_suffix(tmp_path):
    (tmp_path / "2026-06-04_half1.mp4").write_text("x")
    p = build_path(tmp_path, date="2026-06-04", half=1, opponent=None)
    assert p == tmp_path / "2026-06-04_half1-2.mp4"

def test_combined_path_with_opponent(tmp_path):
    assert combined_path(tmp_path, "2026-06-04", "FC Rivals!") == tmp_path / "2026-06-04_vs-fc-rivals.mp4"

def test_combined_path_no_opponent(tmp_path):
    assert combined_path(tmp_path, "2026-06-04", None) == tmp_path / "2026-06-04.mp4"

def test_combined_path_collision(tmp_path):
    (tmp_path / "2026-06-04.mp4").write_text("x")
    assert combined_path(tmp_path, "2026-06-04", None) == tmp_path / "2026-06-04-2.mp4"


from trace_grabber.naming import half_path


def test_a_half_in_progress_keeps_one_name_even_when_the_file_exists(tmp_path):
    first = half_path(tmp_path, "2026-06-04", 1, "FC Rivals!")
    assert first == tmp_path / "2026-06-04_vs-fc-rivals_half1.mp4"
    first.write_text("x")
    assert half_path(tmp_path, "2026-06-04", 1, "FC Rivals!") == first      # no '-2'
    assert half_path(tmp_path, "2026-06-04", 2, None) == tmp_path / "2026-06-04_half2.mp4"


from trace_grabber.naming import game_folders


def test_a_game_has_a_folder_for_clips_of_your_own(tmp_path):
    assert game_folders(tmp_path, "2026-06-04", "Rovers").my_clips == tmp_path / "2026-06-04_vs-rovers" / "My Clips"
