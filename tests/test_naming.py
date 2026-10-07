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


from trace_grabber.naming import combined_path as _combined, custom_stem


def test_a_pattern_names_the_video_from_the_game():
    assert custom_stem("{team} vs {opponent} {date}", "2026-06-04", "Rovers", "Tiger Sharks") == \
        "Tiger Sharks vs Rovers 2026-06-04"
    assert custom_stem("  {date}   {opponent}  ", "2026-06-04", None, "T") == "2026-06-04 Unknown opponent"
    assert custom_stem("{date} {score}", "2026-06-04", "Rovers", "T") == "2026-06-04 {score}"      # not a token


def test_no_pattern_means_the_usual_name():
    for nothing in ("", "   ", None):
        assert custom_stem(nothing, "2026-06-04", "Rovers", "T") is None


def test_a_pattern_can_never_leave_the_games_folder_or_break_a_file_name():
    assert custom_stem("{opponent}: {date}/../x", "2026-06-04", "Rovers", "T") == "Rovers- 2026-06-04-..-x"
    assert custom_stem("../../{team}", "2026-06-04", "Rovers", "A/B\\C") == "A-B-C"
    assert custom_stem('??? <>|"*', "2026-06-04", "Rovers", "T") is None       # nothing left: the usual name
    assert custom_stem("...", "2026-06-04", "Rovers", "T") is None


def test_a_custom_name_is_kept_short_and_never_looks_like_a_half():
    assert len(custom_stem("{opponent}" * 40, "2026-06-04", "Rovers United", "T")) <= 120
    assert custom_stem("{team}_half1", "2026-06-04", "Rovers", "Tiger Sharks") == "Tiger Sharks-half1"


def test_halves_and_the_combined_file_take_the_custom_name(tmp_path):
    assert half_path(tmp_path, "2026-06-04", 2, "Rovers", "T vs Rovers") == tmp_path / "T vs Rovers_half2.mp4"
    assert _combined(tmp_path, "2026-06-04", "Rovers", "T vs Rovers") == tmp_path / "T vs Rovers.mp4"
    (tmp_path / "T vs Rovers.mp4").write_text("x")
    assert _combined(tmp_path, "2026-06-04", "Rovers", "T vs Rovers") == tmp_path / "T vs Rovers-2.mp4"
    assert half_path(tmp_path, "2026-06-04", 1, "Rovers") == tmp_path / "2026-06-04_vs-rovers_half1.mp4"
