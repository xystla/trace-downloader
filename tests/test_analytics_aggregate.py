from trace_grabber.analytics import aggregate, SeasonStats, GameStats, Territory

def _gs(poss_secs, pu, terr):
    return GameStats(game_id=0, date="", opponent="", poss_secs_us=poss_secs,
                     passes_us=pu, shots_us=1, shots_them=0,
                     box_us=1, att_third_us=1, packing_us=1, territory_us=terr)

def test_aggregate_two_games():
    a = _gs(600.0, 10, Territory(20.0, 30.0, 50.0))
    b = _gs(300.0, 6, Territory(40.0, 30.0, 30.0))
    s = aggregate([a, b])
    assert s.games == 2
    assert s.passes_us == 16
    assert s.shots_us == 2 and s.box_us == 2 and s.att_third_us == 2 and s.packing_us == 2
    assert s.poss_secs_us == 900.0                     # sum of ball-control secs
    assert s.territory == Territory(30.0, 30.0, 40.0)  # mean per third

def test_aggregate_empty():
    s = aggregate([])
    assert s == SeasonStats(0, 0.0, 0, 0, 0, 0, 0, 0, Territory(0.0, 0.0, 0.0))
