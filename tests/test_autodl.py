from types import SimpleNamespace

from trace_grabber import autodl


def _games(*ids):
    return [SimpleNamespace(id=i) for i in ids]


def test_settings_survive_a_restart_and_start_out_off(tmp_path):
    state = autodl.load(tmp_path)
    assert (state.enabled, state.login, state.welcomed, state.seen) == (False, False, False, {})
    state.enabled = state.welcomed = True
    state.seen = {"demo": ["g-1"]}
    autodl.save(tmp_path, state)
    again = autodl.load(tmp_path)
    assert (again.enabled, again.welcomed, again.seen) == (True, True, {"demo": ["g-1"]})


def test_a_damaged_settings_file_is_treated_as_new(tmp_path):
    (tmp_path / "auto.json").write_text("{not json")
    assert autodl.load(tmp_path).enabled is False


def test_only_games_added_after_switching_on_are_fetched():
    state = autodl.AutoState(enabled=True)
    listed, done = _games("g-3", "g-2", "g-1"), {"g-1"}
    # First look at an account: everything already there is skipped for good.
    assert autodl.pending(state, "demo", listed, done) == []
    assert state.seen == {"demo": ["g-2", "g-3"]}
    # A game that appears later is the only one fetched.
    later = _games("g-4", "g-3", "g-2", "g-1")
    assert [g.id for g in autodl.pending(state, "demo", later, done)] == ["g-4"]
    # Once downloaded it is no longer pending.
    assert autodl.pending(state, "demo", later, done | {"g-4"}) == []


def test_each_account_gets_its_own_starting_line():
    state = autodl.AutoState(enabled=True, seen={"demo": ["g-1"]})
    assert autodl.pending(state, "other", _games("x-9", "x-8"), set()) == []      # a second team added later
    assert state.seen == {"demo": ["g-1"], "other": ["x-8", "x-9"]}


def test_nothing_is_pending_while_switched_off():
    state = autodl.AutoState(enabled=False, seen={"demo": []})
    assert autodl.pending(state, "demo", _games("g-4"), set()) == []


import json
from datetime import date


def test_new_choices_default_to_everything(tmp_path):
    state = autodl.load(tmp_path)
    assert (state.full, state.highlights, state.recaps, state.tried, state.low_disk) == (True, True, True, {}, False)
    state.recaps = False
    state.tried = {"g-9": "2026-10-01"}
    autodl.save(tmp_path, state)
    again = autodl.load(tmp_path)
    assert (again.recaps, again.tried) == (False, {"g-9": "2026-10-01"})


def test_settings_from_an_older_version_keep_their_choices(tmp_path):
    (tmp_path / "auto.json").write_text(json.dumps(
        {"enabled": True, "login": True, "welcomed": True, "seen": {"demo": ["g-1"]}}))
    state = autodl.load(tmp_path)
    assert (state.enabled, state.login, state.seen) == (True, True, {"demo": ["g-1"]})
    assert (state.full, state.highlights, state.recaps) == (True, True, True)


def test_settings_from_a_newer_version_still_load(tmp_path):
    (tmp_path / "auto.json").write_text(json.dumps({"enabled": True, "something_new": 5}))
    assert autodl.load(tmp_path).enabled is True


def test_a_game_handled_without_its_video_is_not_fetched_again():
    state = autodl.AutoState(enabled=True, seen={"demo": ["g-1"]})
    assert autodl.settle(state, "demo", "g-2", got=True, today=date(2026, 10, 7)) is True
    assert state.seen == {"demo": ["g-1", "g-2"]} and state.tried == {}


def test_a_game_with_nothing_ready_is_tried_again_for_three_days_then_left_alone():
    state = autodl.AutoState(enabled=True, seen={"demo": []})
    assert autodl.settle(state, "demo", "g-2", got=False, today=date(2026, 10, 7)) is False
    assert state.tried == {"g-2": "2026-10-07"} and state.seen == {"demo": []}
    assert autodl.settle(state, "demo", "g-2", got=False, today=date(2026, 10, 9)) is False
    assert autodl.settle(state, "demo", "g-2", got=False, today=date(2026, 10, 10)) is True
    assert state.seen == {"demo": ["g-2"]} and state.tried == {}
