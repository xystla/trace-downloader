import json
from pathlib import Path
from trace_grabber.analytics import compute_game_stats, GameMeta, GameStats, Territory

FIX = Path(__file__).parent / "fixtures" / "game_moments.json"
MOMENTS = json.loads(FIX.read_text())

def test_stats_home():
    meta = GameMeta(game_id=1, date="2026-09-12", opponent="Latterman",
                    our_side="home", match_secs=200)
    s = compute_game_stats(MOMENTS, meta)
    assert s.game_id == 1 and s.date == "2026-09-12" and s.opponent == "Latterman"
    assert s.poss_secs_us == 100.0        # H1 60s + H2 40s of our ball-control
    assert s.poss_pct_us == 50.0          # 100s of a 200s match
    assert s.sequences_us == 2            # two home touch-chains
    assert s.passes_us == 7               # 3 + 4 touches ("?" excluded)
    assert s.shots_us == 2 and s.shots_them == 1
    assert s.box_us == 1                  # H2 has away-box
    assert s.att_third_us == 1            # H2 end_third offensive
    assert s.packing_us == 1             # H1 has packing
    assert s.territory_us == Territory(30.0, 30.0, 40.0)

def test_stats_away_mirrors():
    meta = GameMeta(game_id=2, date="2026-09-09", opponent="Us",
                    our_side="away", match_secs=200)
    s = compute_game_stats(MOMENTS, meta)
    assert s.poss_secs_us == 50.0         # A1 30s + A2 20s
    assert s.poss_pct_us == 25.0          # 50s of a 200s match
    assert s.passes_us == 3
    assert s.shots_us == 1 and s.shots_them == 2
    assert s.box_us == 0                  # no home-box in away chains
    assert s.att_third_us == 1            # A1 end_third offensive
    assert s.packing_us == 0
    assert s.territory_us == Territory(40.0, 30.0, 30.0)

def test_stats_pct_none_without_match_length():
    meta = GameMeta(game_id=4, date="", opponent="", our_side="home")  # match_secs=0
    s = compute_game_stats(MOMENTS, meta)
    assert s.poss_secs_us == 100.0 and s.poss_pct_us is None

def test_stats_empty():
    meta = GameMeta(game_id=3, date="", opponent="", our_side="home", match_secs=200)
    s = compute_game_stats([], meta)
    assert s.poss_secs_us == 0.0 and s.poss_pct_us == 0.0 and s.passes_us == 0
    assert s.territory_us == Territory(0.0, 0.0, 0.0)


def test_touches_are_counted_per_jersey_number_for_our_team_only():
    from trace_grabber.analytics import GameMeta, aggregate, compute_game_stats
    moments = [
        {"type": "touch_chain", "side": "home", "duration": 10, "trace_numbers": ["7", "?", "2", "7"]},
        {"type": "touch_chain", "side": "home", "duration": 10, "trace_numbers": ["2"]},
        {"type": "touch_chain", "side": "away", "duration": 10, "trace_numbers": ["9"]},
    ]
    stats = compute_game_stats(moments, GameMeta(1, "2026-06-04", "Rovers", "home"))
    assert stats.touches_by_number == {"7": 2, "2": 2}
    assert aggregate([stats, stats]).touches_by_number == {"7": 4, "2": 4}


def test_territory_map_can_take_its_ink_from_the_page():
    from trace_grabber.analytics import Territory, territory_svg
    svg = territory_svg(Territory(20, 30, 50), ink="currentColor")
    assert 'stroke="currentColor"' in svg and "#e8e8e8" not in svg and "#20303a" not in svg


def test_game_query_asks_for_what_highlight_clips_need():
    from trace_grabber.analytics import GAME_Q
    assert " time " in GAME_Q and " title " in GAME_Q


def test_opponent_box_entries_are_counted():
    from trace_grabber.analytics import GameMeta, aggregate, compute_game_stats
    moments = [
        {"type": "touch_chain", "side": "home", "duration": 10, "keywords": ["away-box"]},   # ours
        {"type": "away_shot home_box", "side": "away", "duration": 5, "keywords": ["away-shot", "home-box"]},
        {"type": "home_box", "side": "away", "duration": 5, "keywords": ["home-box"]},
    ]
    stats = compute_game_stats(moments, GameMeta(1, "2026-06-04", "Rovers", "home"))
    assert (stats.box_us, stats.box_them) == (1, 2)
    assert aggregate([stats, stats]).box_them == 4
