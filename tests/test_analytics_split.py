import json
from pathlib import Path
from trace_grabber.analytics import compute_split, GameMeta, Territory

FIX = Path(__file__).parent / "fixtures" / "game_moments.json"
MOMENTS = json.loads(FIX.read_text())

def test_split_whole_and_halves_home():
    meta = GameMeta(game_id=1, date="2026-09-12", opponent="Latterman",
                    our_side="home", match_secs=200)  # half = 100s
    sp = compute_split(MOMENTS, meta)

    # whole = both halves
    assert sp.whole.poss_secs_us == 100.0 and sp.whole.poss_pct_us == 50.0
    assert sp.whole.passes_us == 7

    # first half = only H1 (60s, 3 touches, packing, shot; ends middle third)
    assert sp.first.poss_secs_us == 60.0 and sp.first.poss_pct_us == 60.0  # 60/100
    assert sp.first.passes_us == 3 and sp.first.packing_us == 1
    assert sp.first.att_third_us == 0
    assert sp.first.territory_us == Territory(50.0, 50.0, 0.0)

    # second half = only H2 (40s, 4 touches, box + attacking third)
    assert sp.second.poss_secs_us == 40.0 and sp.second.poss_pct_us == 40.0  # 40/100
    assert sp.second.passes_us == 4 and sp.second.box_us == 1
    assert sp.second.att_third_us == 1
    assert sp.second.territory_us == Territory(0.0, 0.0, 100.0)

    # halves sum to the whole for additive metrics
    assert sp.first.passes_us + sp.second.passes_us == sp.whole.passes_us
    assert round(sp.first.poss_secs_us + sp.second.poss_secs_us, 1) == sp.whole.poss_secs_us
