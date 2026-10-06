from trace_grabber.games import Game
from gui.viewmodel import game_view, games_view, connection_state

def _g(i): return Game(id=i, team_id="t", date="2026-05-28", opponent="Rivals", title="T vs. Rivals")

def test_game_view_saved_vs_new():
    assert game_view(_g("t-1"), {"t-1"})["state"] == "saved"
    assert game_view(_g("t-2"), {"t-1"})["state"] == "new"

def test_game_view_fields():
    v = game_view(_g("t-9"), set())
    assert v["id"] == "t-9" and v["date"] == "2026-05-28" and v["opponent"] == "Rivals"
    assert v["team_id"] == "t"

def test_games_view_maps_all():
    views = games_view([_g("t-1"), _g("t-2")], {"t-1"})
    assert [v["state"] for v in views] == ["saved", "new"]

def test_connection_state_no_account_is_none_not_expired():
    # A fresh install (no account yet) must NOT read as a stale session —
    # otherwise the UI shows "Session expired" + Reconnect, a dead end.
    assert connection_state(has_account=False, logged_in=False) == "none"
    assert connection_state(has_account=False, logged_in=True) == "none"

def test_connection_state_with_account():
    assert connection_state(has_account=True, logged_in=False) == "expired"
    assert connection_state(has_account=True, logged_in=True) == "ok"

def test_game_view_date_label_is_human_readable():
    assert game_view(_g("t-1"), set())["date_label"] == "May 28, 2026"
    early = Game(id="t-1", team_id="t", date="2026-10-03", opponent="Rivals", title="T vs. Rivals")
    assert game_view(early, set())["date_label"] == "October 3, 2026"

def test_game_view_date_label_falls_back_to_raw_text():
    game = Game(id="t-1", team_id="t", date="sometime", opponent="Rivals", title="T vs. Rivals")
    assert game_view(game, set())["date_label"] == "sometime"

def _scored(us, them):
    return Game(id="t-1", team_id="t", date="2026-10-03", opponent="Rivals", title="T vs. Rivals",
                score_us=us, score_them=them)

def test_game_view_carries_the_score_and_result():
    assert game_view(_scored(5, 3), set())["score"] == {"us": 5, "them": 3, "result": "win"}
    assert game_view(_scored(2, 4), set())["score"] == {"us": 2, "them": 4, "result": "loss"}
    assert game_view(_scored(1, 1), set())["score"] == {"us": 1, "them": 1, "result": "draw"}

def test_game_view_has_no_score_when_none_was_entered():
    assert game_view(_g("t-1"), set())["score"] is None
    assert game_view(_scored(2, None), set())["score"] is None
