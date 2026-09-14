from trace_grabber.analytics import aggregate, SeasonStats, GameStats, Territory

def _gs(poss, pu, pt, terr):
    return GameStats(game_id=0, date="", opponent="", poss_pct_us=poss,
                     passes_us=pu, passes_them=pt, shots_us=1, shots_them=0,
                     box_us=1, att_third_us=1, packing_us=1, territory_us=terr)

def test_aggregate_two_games():
    a = _gs(60.0, 10, 5, Territory(20.0, 30.0, 50.0))
    b = _gs(40.0, 6, 9, Territory(40.0, 30.0, 30.0))
    s = aggregate([a, b])
    assert s.games == 2
    assert s.passes_us == 16 and s.passes_them == 14
    assert s.shots_us == 2 and s.box_us == 2 and s.att_third_us == 2 and s.packing_us == 2
    assert s.poss_pct_us == 50.0                       # mean(60,40)
    assert s.territory == Territory(30.0, 30.0, 40.0)  # mean per third

def test_aggregate_empty():
    s = aggregate([])
    assert s == SeasonStats(0, 0.0, 0, 0, 0, 0, 0, 0, 0, Territory(0.0, 0.0, 0.0))
