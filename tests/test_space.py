from types import SimpleNamespace

import pytest

from trace_grabber import space

GB = 1_000_000_000


def test_size_comes_from_bitrate_and_length():
    assert space.estimate(8_000_000, 2700) == 2_700_000_000      # 8 Mbit/s for 45 minutes
    assert space.estimate(0, 2700) == 0                          # Trace didn't say


def test_a_fresh_game_needs_its_halves_plus_room_to_join_one():
    halves = [(2 * GB, 0, False), (2 * GB, 0, False)]
    assert space.needed(halves, combine=False) == 4 * GB + 2 * GB + space.MARGIN


def test_combining_needs_room_for_the_combined_file_too():
    halves = [(2 * GB, 0, False), (2 * GB, 0, False)]
    assert space.needed(halves, combine=True) == 4 * GB + 2 * GB + 4 * GB + space.MARGIN


def test_what_is_already_downloaded_is_not_needed_again():
    halves = [(2 * GB, 0, True), (2 * GB, 1 * GB, False)]        # half 1 done, half 2 halfway
    assert space.needed(halves, combine=False) == 1 * GB + 2 * GB + space.MARGIN


def test_a_single_half_is_never_combined():
    assert space.needed([(2 * GB, 0, False)], combine=True) == 2 * GB + 2 * GB + space.MARGIN


def test_free_space_is_measured_where_the_folder_will_be(tmp_path, monkeypatch):
    asked = []
    def usage(path):
        asked.append(path)
        return SimpleNamespace(free=7 * GB)
    monkeypatch.setattr(space.shutil, "disk_usage", usage)
    assert space.free(tmp_path / "not" / "made" / "yet") == 7 * GB
    assert asked == [tmp_path]


def test_sizes_read_naturally():
    assert space.size_text(9_400_000_000) == "9.4 GB"
    assert space.size_text(212 * GB) == "212 GB"
    assert space.size_text(640_000_000) == "640 MB"


def test_too_little_room_is_refused_with_both_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(space.shutil, "disk_usage", lambda path: SimpleNamespace(free=3 * GB))
    space.check(tmp_path, 3 * GB)                                # exactly enough
    with pytest.raises(space.NotEnoughSpace) as refused:
        space.check(tmp_path, 9 * GB)
    assert str(refused.value) == "Not enough disk space: this game needs about 9.0 GB and 3.0 GB is free."
