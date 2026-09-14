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
