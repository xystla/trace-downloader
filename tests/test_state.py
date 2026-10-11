from trace_grabber.state import load_state, mark_done, new_game_ids

def test_load_empty_when_missing(tmp_path):
    assert load_state(tmp_path / "state.json") == set()

def test_mark_done_and_reload(tmp_path):
    p = tmp_path / "state.json"
    mark_done(p, "game-123")
    mark_done(p, "game-456")
    assert load_state(p) == {"game-123", "game-456"}

def test_new_game_ids_filters_known(tmp_path):
    p = tmp_path / "state.json"
    mark_done(p, "game-1")
    assert new_game_ids(["game-1", "game-2", "game-3"], p) == ["game-2", "game-3"]

def test_mark_done_creates_the_missing_folder(tmp_path):
    # A brand-new install has no "state" folder yet.
    p = tmp_path / "state" / "team.json"
    mark_done(p, "game-1")
    assert load_state(p) == {"game-1"}
