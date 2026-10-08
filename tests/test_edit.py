import json

from trace_grabber import edit, scorebug


def _marks(*pairs):
    return [{"id": f"m{i}", "kind": kind, "t": t} for i, (kind, t) in enumerate(pairs)]


GAME = _marks(("start", 10), ("break", 610), ("resume", 700), ("goal_home", 300), ("goal_away", 800),
              ("goal_home", 900), ("end", 1300))


def test_marks_become_stretches_of_play():
    segments, problems = edit.outline(GAME)
    assert problems == [] and segments == [(10, 610), (700, 1300)]
    assert edit.play_length(segments) == 1200


def test_the_clock_runs_through_play_and_stops_for_breaks():
    segments, _ = edit.outline(GAME)
    assert edit.out_time(segments, 10) == 0 and edit.out_time(segments, 310) == 300
    assert edit.out_time(segments, 650) is None                    # in the break
    assert edit.out_time(segments, 700) == 600                     # carries on where it stopped
    assert edit.out_time(segments, 5) is None and edit.out_time(segments, 1400) is None
    assert edit.clock_text(0) == "00:00" and edit.clock_text(754.9) == "12:34" and edit.clock_text(6000) == "100:00"


def test_the_score_changes_at_each_goal_on_the_output_clock():
    segments, _ = edit.outline(GAME)
    assert edit.score_changes(GAME, segments) == [(0.0, 0, 0), (290.0, 1, 0), (700.0, 1, 1), (800.0, 2, 1)]


def test_a_game_with_no_breaks_is_one_stretch():
    assert edit.outline(_marks(("start", 5), ("end", 65))) == ([(5, 65)], [])


def test_what_is_missing_is_said_plainly():
    assert edit.outline([])[1] == ["Mark where the game starts.", "Mark where the game ends."]
    assert edit.outline(_marks(("start", 5)))[1] == ["Mark where the game ends."]
    assert edit.outline(_marks(("start", 5), ("start", 9), ("end", 99), ("end", 120)))[1] == [
        "There is more than one 'Game starts' mark.", "There is more than one 'Game ends' mark."]
    assert edit.outline(_marks(("start", 50), ("end", 20)))[1] == ["The game ends before it starts."]


def test_breaks_and_resumes_must_take_turns():
    two_breaks = _marks(("start", 0), ("break", 100), ("break", 1870), ("resume", 1900), ("end", 3000))
    assert edit.outline(two_breaks)[1] == ["There are two breaks in a row at 31:10. Add 'Play resumes' between them."]
    no_break = _marks(("start", 0), ("resume", 720), ("end", 3000))
    assert edit.outline(no_break)[1] == ["'Play resumes' at 12:00 has no break before it."]
    in_break = _marks(("start", 0), ("break", 100), ("end", 3000))
    assert edit.outline(in_break)[1] == ["The game ends during a break. Add 'Play resumes' or remove the last break."]


def test_marks_outside_the_game_and_goals_inside_a_break_are_problems():
    early = _marks(("goal_home", 5), ("start", 10), ("end", 100), ("break", 200))
    assert edit.outline(early)[1] == ["The mark at 0:05 is before the game starts.",
                                      "The mark at 3:20 is after the game ends."]
    goal = _marks(("start", 0), ("break", 1870), ("goal_away", 1880), ("resume", 1900), ("end", 3000))
    assert edit.outline(goal)[1] == ["The goal at 31:20 is inside a break."]


def test_a_period_too_short_to_show_is_a_problem():
    marks = _marks(("start", 0), ("break", 100), ("resume", 1870), ("break", 1871), ("resume", 1900), ("end", 3000))
    assert edit.outline(marks)[1] == ["The period starting at 31:10 is too short."]


def test_team_details_are_tidied():
    cleaned = edit.clean({"home": {"name": "  Tiger   Sharks ", "code": "  tiger   sharks u-12 ", "color": "#16A05A"},
                          "away": {"name": "", "code": "", "color": "blue"},
                          "marks": [{"id": "a", "kind": "goal_home", "t": 30}, {"kind": "start", "t": 2.26},
                                    {"id": "x", "kind": "kickoff", "t": 3}, {"id": "y", "kind": "end", "t": "late"},
                                    {"id": "z", "kind": "end", "t": -4}, "junk", {"id": "n", "kind": "end", "t": float("nan")}]})
    assert cleaned["home"] == {"name": "Tiger Sharks", "code": "TIGER SHARKS U-12", "color": "#16a05a"}
    assert cleaned["away"] == {"name": "", "code": "AWY", "color": "#1e5ac8"}
    assert [(m["kind"], m["t"]) for m in cleaned["marks"]] == [("start", 2.26), ("goal_home", 30.0)]
    assert all(isinstance(m["id"], str) and m["id"] for m in cleaned["marks"])
    assert edit.clean("nonsense")["marks"] == [] and edit.clean(None)["home"]["code"] == "HOM"
    assert len(edit.clean({"home": {"code": "x" * 90}})["home"]["code"]) == 40


def test_the_picture_settings_travel_with_the_edit():
    plain = {"exposure": 0, "contrast": 0, "saturation": 0}
    assert edit.clean({})["grade"] == plain == edit.clean({"grade": "vivid"})["grade"] == edit.default_project("T", "R")["grade"]
    assert edit.clean({"grade": {"exposure": 25.4, "contrast": -40, "saturation": 300, "sharpen": 35}})["grade"] == {"exposure": 25, "contrast": -40, "saturation": 100}
    assert edit.clean({"grade": {"exposure": "x", "contrast": True, "saturation": -500}})["grade"] == {**plain, "saturation": -100}


def test_which_crests_are_shown_travels_with_the_edit():
    assert edit.clean({})["crests"] == {"home": False, "away": False, "league": False}
    assert edit.clean({"crests": {"home": True, "league": 1, "away": "yes", "ref": True}})["crests"] == {"home": True, "away": False, "league": False}
    assert edit.clean({"crests": "all"})["crests"] == {"home": False, "away": False, "league": False}


def test_a_crest_is_kept_with_the_game_as_a_small_png(tmp_path):
    from PIL import Image
    big = tmp_path / "club badge.jpg"
    Image.new("RGB", (1600, 1200), (200, 30, 30)).save(big)
    kept = edit.set_crest(tmp_path / "game", "home", big)
    assert kept == tmp_path / "game" / "Edit" / "crest-home.png" == edit.crest_path(tmp_path / "game", "home")
    with Image.open(kept) as saved:
        assert saved.format == "PNG" and saved.mode == "RGBA" and saved.size == (512, 384)
    pictures = edit.crest_images(tmp_path / "game", {"home": True, "away": True, "league": False})
    assert set(pictures) == {"home"} and pictures["home"].size == (512, 384)        # only those asked for that are there
    assert edit.crest_images(tmp_path / "game", {"home": False}) == {}
    edit.remove_crest(tmp_path / "game", "home")
    edit.remove_crest(tmp_path / "game", "home")                                     # twice is fine
    assert not kept.exists() and edit.crest_images(tmp_path / "game", {"home": True}) == {}


def test_a_file_that_is_not_a_picture_is_refused_plainly(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("not a picture")
    for bad in (notes, tmp_path / "missing.png"):
        try:
            edit.set_crest(tmp_path / "game", "league", bad)
        except RuntimeError as e:
            assert str(e) == "That file isn't a picture TraceDown can use. Try a PNG or JPEG."
        else:
            raise AssertionError("accepted")
    assert not (tmp_path / "game" / "Edit" / "crest-league.png").exists()
    try:
        edit.set_crest(tmp_path / "game", "mascot", notes)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted an unknown crest")


def test_score_bug_looks_can_be_saved_by_name_and_taken_away(tmp_path):
    kept = tmp_path / "data" / "edit_looks.json"
    assert edit.looks(kept) == []
    first = edit.save_look(kept, "  Night   games ", {"font": "anton", "size": 9, "junk": 1})
    assert first == [{"name": "Night games", "bug": {**scorebug.USUAL, "font": "anton", "size": 2.0}}] == edit.looks(kept)
    edit.save_look(kept, "League final", {"design": "slim"})
    again = edit.save_look(kept, "night GAMES", {"font": "poppins"})                   # the same name replaces, whatever its capitals
    assert [(look["name"], look["bug"]["font"]) for look in again] == [("League final", "bebas"), ("night GAMES", "poppins")]
    assert [look["name"] for look in edit.delete_look(kept, "league FINAL")] == ["night GAMES"]
    assert edit.delete_look(kept, "never saved") == edit.looks(kept)
    for bad in ("", "   ", None, 7):
        try:
            edit.save_look(kept, bad, {})
        except RuntimeError as e:
            assert str(e) == "Give the look a name first."
        else:
            raise AssertionError("saved without a name")
    assert len(edit.save_look(kept, "x" * 90, {})[-1]["name"]) == 40
    kept.write_text("not json")
    assert edit.looks(kept) == []                                                       # a damaged file is no looks, not an error
    kept.write_text('[{"name": "ok", "bug": {}}, {"name": 3}, "junk", {"bug": {}}]')
    assert [look["name"] for look in edit.looks(kept)] == ["ok"]


def test_the_bug_settings_travel_with_the_edit():
    usual = dict(scorebug.USUAL)
    assert edit.clean({})["bug"] == usual
    assert edit.clean({"bug": {"size": 1.5, "font": "anton"}})["bug"] == {**usual, "size": 1.5, "font": "anton"}
    assert edit.clean({"bug": {"size": 40, "font": "wingdings"}})["bug"] == {**usual, "size": 2.0}
    assert usual["font"] == "bebas" and usual["timer"] == "right"                # the look a first edit starts with
    look = {"size": 1.3, "font": "bebas", "color": "#0a2a5c", "clock": 20, "strip": 18, "round": 0, "timer": "right", "animate": False, "design": "slim", "color2": "#ff5500", "crest_shadow": True, "timer_full": True, "timer_text": 80}
    assert edit.default_project("T", "R", None, look)["bug"] == look


def test_a_code_is_taken_from_the_name():
    assert edit.code_from("Tiger Sharks", "HOM") == "TIG" and edit.code_from("FC 1907", "AWY") == "FC1"
    assert edit.code_from("", "AWY") == "AWY" and edit.code_from("!!!", "HOM") == "HOM"


def test_a_new_edit_starts_from_the_teams_and_what_was_used_last_time():
    fresh = edit.default_project("Tiger Sharks", "Blue Dragons")
    assert fresh["home"] == {"name": "Tiger Sharks", "code": "TIG", "color": "#16a05a"}
    assert fresh["away"] == {"name": "Blue Dragons", "code": "BLU", "color": "#1e5ac8"} and fresh["marks"] == []
    again = edit.default_project("Tiger Sharks", None, {"name": "Tiger Sharks", "code": "TSH", "color": "#ff8800"})
    assert again["home"] == {"name": "Tiger Sharks", "code": "TSH", "color": "#ff8800"}
    assert again["away"]["code"] == "AWY"


def test_an_edit_is_kept_in_the_games_folder(tmp_path):
    assert edit.load(tmp_path) is None
    saved = edit.save(tmp_path, {"home": {"name": "T", "code": "t", "color": "#000000"}, "marks": GAME})
    assert (tmp_path / "Edit" / "edit.json").exists() and saved["home"]["code"] == "T"
    assert [m["t"] for m in edit.load(tmp_path)["marks"]] == sorted(m["t"] for m in GAME)
    assert sorted(p.name for p in (tmp_path / "Edit").iterdir()) == ["edit.json"]
    (tmp_path / "Edit" / "edit.json").write_text("{not json")
    assert edit.load(tmp_path) is None
