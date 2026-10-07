from pathlib import Path

from trace_grabber import highlights
from trace_grabber.highlights import Clip


def _m(half, time, duration, *keywords, type_="touch_chain"):
    return {"type": type_, "half": half, "time": time, "duration": duration,
            "keywords": list(keywords)}


# Trace times a moment as if both halves' videos were joined end to end, so a
# second-half moment sits at (first-half video length + its place in the second half).
FULL = [_m(1, 0, 2309.5, type_="FullGameVideo"), _m(2, 2560, 2300, type_="FullGameVideo")]


def test_picks_shots_and_box_entries_in_match_order():
    moments = FULL + [
        _m(2, 2409.5, 10, "away-shot"),
        _m(1, 300, 20, "home-shot", "away-box"),
        _m(1, 50, 15, "away-box"),
        _m(1, 700, 30, "touch-chain"),                       # nothing notable
    ]
    clips = highlights.pick(moments, "home")
    assert [(c.half, c.label) for c in clips] == [(1, "box-entry"), (1, "shot"), (2, "opp-shot")]


def test_clip_is_padded_around_the_moment():
    (clip,) = highlights.pick([_m(1, 300, 20, "home-shot")], "home")
    assert (clip.start, clip.length) == (295, 30)
    (early,) = highlights.pick([_m(1, 2, 20, "home-shot")], "home")
    assert early.start == 0


def test_second_half_clip_is_measured_from_the_end_of_the_first_half_video():
    (clip,) = highlights.pick(FULL + [_m(2, 2409.5, 10, "away-shot")], "home")
    assert (clip.half, clip.start, clip.length) == (2, 95, 20)
    assert highlights.pick([_m(2, 2409.5, 10, "away-shot")], "home") == []   # start unknown


def test_overlapping_moments_become_one_clip_named_for_the_bigger_event():
    moments = [_m(1, 300, 40, "away-box"), _m(1, 320, 8, "home-shot")]
    (clip,) = highlights.pick(moments, "home")
    assert clip.label == "shot"
    assert (clip.start, clip.length) == (295, 50)


def test_moments_without_a_time_are_skipped():
    assert highlights.pick([{"half": 1, "duration": 5, "keywords": ["home-shot"]}], "home") == []


def test_half_one_length_comes_from_the_full_game_video_moment():
    moments = [_m(1, 0, 2309.5, type_="FullGameVideo"), _m(2, 0, 2400, type_="FullGameVideo")]
    assert highlights.half1_secs(moments) == 2309.5
    assert highlights.half1_secs([]) is None


def test_second_half_clip_is_offset_into_a_combined_file():
    combined = [Path("/v/2026-06-04_vs-rovers.mp4")]
    clip = Clip(half=2, start=100, length=20, label="shot")
    assert highlights.source_for(clip, combined, 2309.5) == (combined[0], 2409.5)
    assert highlights.source_for(clip, combined, None) is None
    first = Clip(half=1, start=100, length=20, label="shot")
    assert highlights.source_for(first, combined, None) == (combined[0], 100)


def test_separate_half_files_are_used_directly():
    files = [Path("/v/g_half1.mp4"), Path("/v/g_half2.mp4")]
    clip = Clip(half=2, start=100, length=20, label="shot")
    assert highlights.source_for(clip, files, None) == (files[1], 100)


def test_clip_names_sort_in_match_order_and_say_what_happened():
    assert highlights.clip_name(3, Clip(half=2, start=125, length=20, label="opp-shot")) == \
        "03_half2_02m05s_opp-shot.mp4"


def test_export_cuts_each_clip_into_a_highlights_folder(tmp_path, monkeypatch):
    video = tmp_path / "2026-06-04_vs-rovers.mp4"
    video.write_bytes(b"x")
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"clip")
        return type("R", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(highlights.subprocess, "run", fake_run)
    moments = FULL + [_m(1, 300, 20, "home-shot"), _m(2, 2409.5, 10, "away-shot")]
    target = tmp_path / "2026-06-04_vs-rovers" / "Highlights"
    folder, count = highlights.export(moments, "home", [video], target)
    assert folder == target and count == 2
    assert sorted(p.name for p in folder.iterdir()) == [
        "01_half1_04m55s_shot.mp4", "02_half2_01m35s_opp-shot.mp4"]
    assert commands[1][commands[1].index("-ss") + 1] == "2404.5"
    assert "-c" in commands[0] and "copy" in commands[0]


def test_export_reports_nothing_to_cut(tmp_path):
    video = tmp_path / "g.mp4"
    video.write_bytes(b"x")
    assert highlights.export([_m(1, 700, 30, "touch-chain")], "home", [video], tmp_path / "H") == (None, 0)
    assert not (tmp_path / "H").exists()


def test_only_team_clips_are_counted_in_a_folder(tmp_path):
    folder = tmp_path / "Highlights"
    assert highlights.clip_count(folder) == 0                 # no folder yet
    folder.mkdir()
    (folder / "player-10.mp4").write_bytes(b"recap")          # a player recap is not a team clip
    assert highlights.clip_count(folder) == 0
    (folder / "01_half1_04m55s_shot.mp4").write_bytes(b"clip")
    (folder / "02_half2_01m35s_opp-shot.mp4").write_bytes(b"clip")
    assert highlights.clip_count(folder) == 2
    (folder / "03_half2_09m00s_shot.part.mp4").write_bytes(b"half")   # still being cut
    (folder / highlights.REEL_NAME).write_bytes(b"reel")
    assert highlights.clip_count(folder) == 2


def test_reel_joins_the_clips_in_match_order(tmp_path, monkeypatch):
    for name in ("02_half2_01m35s_opp-shot.mp4", "01_half1_04m55s_shot.mp4", "player-10.mp4"):
        (tmp_path / name).write_bytes(b"clip")
    joined = []
    def fake_combine(parts, dest):
        joined.append(([Path(p).name for p in parts], dest))
        Path(dest).write_bytes(b"reel")
    monkeypatch.setattr(highlights.combine, "combine", fake_combine)
    reel = highlights.build_reel(tmp_path)
    assert reel == tmp_path / "Team Highlight Reel.mp4"
    assert joined == [(["01_half1_04m55s_shot.mp4", "02_half2_01m35s_opp-shot.mp4"], reel)]
    assert highlights.build_reel(tmp_path) == reel and len(joined) == 1      # kept, not rebuilt


def test_no_reel_without_clips(tmp_path):
    assert highlights.build_reel(tmp_path) is None
    assert highlights.build_reel(tmp_path / "nowhere") is None


def test_a_reel_problem_does_not_spoil_the_clips(tmp_path, monkeypatch):
    (tmp_path / "01_half1_04m55s_shot.mp4").write_bytes(b"clip")
    def broken(parts, dest):
        raise RuntimeError("combine failed")
    monkeypatch.setattr(highlights.combine, "combine", broken)
    assert highlights.build_reel(tmp_path) is None


def _remote(monkeypatch, fail=()):
    """Fake segment downloads; returns the list of (urls, file name) that were fetched."""
    fetched = []
    def download(urls, dest, total_secs=None, progress_cb=None, on_proc=None):
        if Path(dest).name in fail:
            raise RuntimeError("download failed")
        fetched.append((urls, Path(dest).name))
        Path(dest).write_bytes(b"clip")
    monkeypatch.setattr(highlights.segments, "download", download)
    return fetched


def test_clips_can_be_fetched_from_trace_without_the_full_game(tmp_path, monkeypatch):
    fetched = _remote(monkeypatch)
    playlists = {1: [(2.0, f"a{i}") for i in range(1200)], 2: [(2.0, f"b{i}") for i in range(1200)]}
    moments = FULL + [_m(1, 300, 20, "home-shot"), _m(2, 2409.5, 10, "away-shot")]
    progress = []
    folder, count = highlights.export_remote(moments, "home", playlists, tmp_path / "Highlights",
                                             on_progress=lambda done, total: progress.append((done, total)))
    assert (folder, count) == (tmp_path / "Highlights", 2)
    assert sorted(p.name for p in folder.iterdir()) == [
        "01_half1_04m55s_shot.mp4", "02_half2_01m35s_opp-shot.mp4"]
    # 295s..325s of half 1 is pieces 147..162; 95s..115s of half 2 is pieces 47..57
    assert fetched[0][0][0] == "a147" and fetched[0][0][-1] == "a162"
    assert fetched[1][0][0] == "b47" and fetched[1][0][-1] == "b57"
    assert progress == [(0, 2), (1, 2), (2, 2)]


def test_remote_clips_only_appear_once_the_whole_set_is_done(tmp_path, monkeypatch):
    _remote(monkeypatch)
    playlists = {1: [(2.0, f"a{i}") for i in range(1200)]}
    moments = FULL + [_m(1, 300, 20, "home-shot"), _m(1, 900, 20, "home-shot")]
    stops = iter([False, True])                      # Stop pressed after the first clip
    folder, count = highlights.export_remote(moments, "home", playlists, tmp_path / "H",
                                             should_stop=lambda: next(stops))
    assert count == 0
    assert highlights.clip_count(tmp_path / "H") == 0          # nothing half-done looks finished


def test_a_clip_that_fails_to_download_is_left_out(tmp_path, monkeypatch):
    _remote(monkeypatch, fail={"01_half1_04m55s_shot.part.mp4"})
    playlists = {1: [(2.0, f"a{i}") for i in range(1200)]}
    moments = FULL + [_m(1, 300, 20, "home-shot"), _m(1, 900, 20, "home-shot")]
    folder, count = highlights.export_remote(moments, "home", playlists, tmp_path / "H")
    assert count == 1 and [p.name for p in folder.iterdir()] == ["02_half1_14m55s_shot.mp4"]


def test_remote_export_reports_nothing_to_fetch(tmp_path, monkeypatch):
    _remote(monkeypatch)
    assert highlights.export_remote([_m(1, 700, 30, "touch-chain")], "home", {1: []}, tmp_path / "H") == (None, 0)
    assert not (tmp_path / "H").exists()


def test_timeline_lists_the_key_moments_in_match_time():
    moments = FULL + [
        _m(2, 2409.5, 10, "away-shot"),                 # 100s into the second half
        _m(1, 300, 20, "home-shot", "away-box"),
        _m(1, 302, 5, "home-shot"),                     # the same shot, tagged twice
        _m(1, 50, 15, "away-box"),
        _m(1, 900, 12, "home-box"),                     # they got into our box
        _m(1, 700, 30, "touch-chain"),                  # nothing notable
    ]
    line = highlights.timeline(moments, "home")
    assert line["half1"] == 2309.5 and line["duration"] == 4609.5
    assert [(m["t"], m["half"], m["label"]) for m in line["moments"]] == [
        (50, 1, "box-entry"), (300, 1, "shot"), (900, 1, "opp-box-entry"), (2409.5, 2, "opp-shot")]


def test_timeline_is_empty_for_stats_saved_without_times():
    old = [{"type": "touch_chain", "half": 1, "duration": 5, "keywords": ["home-shot"]}]
    assert highlights.timeline(old, "home") == {"duration": None, "half1": None, "moments": []}


def test_a_clips_place_in_the_game_is_read_from_its_name():
    assert highlights.clip_place("02_half2_01m35s_opp-shot.mp4") == (2, 95)
    assert highlights.clip_place("Team Highlight Reel.mp4") == (None, None)


import pytest


def test_my_clip_is_named_for_where_it_sits_in_the_game():
    assert highlights.my_clip_name(2, 724.9, 751.2) == "half2_12m04s-12m31s.mp4"
    assert highlights.my_clip_name(0, 3605, 3660) == "60m05s-61m00s.mp4"          # one file: no half
    assert highlights.my_clip_label("half2_12m04s-12m31s.mp4") == "2nd half 12:04 – 12:31"
    assert highlights.my_clip_label("60m05s-61m00s.mp4") == "60:05 – 61:00"
    assert highlights.my_clip_label("half1_00m05s-00m09s-2.mp4") == "1st half 0:05 – 0:09"      # a second copy
    assert highlights.my_clip_label("something else.mp4") == "something else"


def test_my_clips_lists_finished_clips_in_order(tmp_path):
    assert highlights.my_clips(tmp_path / "missing") == []
    for name in ("half2_01m00s-01m10s.mp4", "half1_05m00s-05m10s.mp4", "half1_05m00s-05m10s.part.mp4", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in highlights.my_clips(tmp_path)] == ["half1_05m00s-05m10s.mp4", "half2_01m00s-01m10s.mp4"]


def test_a_clip_is_cut_without_re_encoding(tmp_path, monkeypatch):
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"clip")
        return type("R", (), {"returncode": 0, "stderr": ""})()
    monkeypatch.setattr(highlights.subprocess, "run", fake_run)
    dest = tmp_path / "My Clips" / "half1_12m04s-12m31s.mp4"
    highlights.cut_clip(tmp_path / "game.mp4", 724.5, 27, dest)
    (cmd,) = commands
    assert cmd[cmd.index("-ss") + 1] == "724.5" and cmd[cmd.index("-t") + 1] == "27"
    assert cmd[cmd.index("-c") + 1] == "copy" and cmd[cmd.index("-i") + 1] == str(tmp_path / "game.mp4")
    assert [p.name for p in dest.parent.iterdir()] == ["half1_12m04s-12m31s.mp4"]


def test_a_cut_that_fails_leaves_no_file(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"half a cl")
        return type("R", (), {"returncode": 1, "stderr": "boom"})()
    monkeypatch.setattr(highlights.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="couldn't be saved"):
        highlights.cut_clip(tmp_path / "game.mp4", 5, 10, tmp_path / "My Clips" / "c.mp4")
    assert list((tmp_path / "My Clips").iterdir()) == []
