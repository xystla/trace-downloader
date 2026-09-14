import json
from pathlib import Path
from trace_grabber.analytics import compute_game_stats, GameMeta, GameStats, Territory

FIX = Path(__file__).parent / "fixtures" / "game_moments.json"
MOMENTS = json.loads(FIX.read_text())

def test_stats_home():
    meta = GameMeta(game_id=1, date="2026-09-12", opponent="Latterman", our_side="home")
    s = compute_game_stats(MOMENTS, meta)
    assert s.game_id == 1 and s.date == "2026-09-12" and s.opponent == "Latterman"
    assert s.poss_pct_us == 66.7          # home 100s of 150s
    assert s.passes_us == 7               # 3 + 4 touches ("?" excluded elsewhere)
    assert s.passes_them == 3             # away 2 + 1 (one "?" dropped)
    assert s.shots_us == 2 and s.shots_them == 1
    assert s.box_us == 1                  # H2 has away-box
    assert s.att_third_us == 1            # H2 end_third offensive
    assert s.packing_us == 1             # H1 has packing
    assert s.territory_us == Territory(30.0, 30.0, 40.0)

def test_stats_away_mirrors():
    meta = GameMeta(game_id=2, date="2026-09-09", opponent="Us", our_side="away")
    s = compute_game_stats(MOMENTS, meta)
    assert s.poss_pct_us == 33.3
    assert s.passes_us == 3 and s.passes_them == 7
    assert s.shots_us == 1 and s.shots_them == 2
    assert s.box_us == 0                  # no home-box in away chains
    assert s.att_third_us == 1            # A1 end_third offensive
    assert s.packing_us == 0
    assert s.territory_us == Territory(40.0, 30.0, 30.0)

def test_stats_empty():
    meta = GameMeta(game_id=3, date="", opponent="", our_side="home")
    s = compute_game_stats([], meta)
    assert s.poss_pct_us == 0.0 and s.passes_us == 0 and s.passes_them == 0
    assert s.territory_us == Territory(0.0, 0.0, 0.0)
