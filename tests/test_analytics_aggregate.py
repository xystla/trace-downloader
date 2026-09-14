from trace_grabber.analytics import aggregate, SeasonStats, GameStats, Territory

def _gs(poss_secs, pu, terr, match_secs, seq):
    return GameStats(game_id=0, date="", opponent="", poss_secs_us=poss_secs,
                     poss_pct_us=None, passes_us=pu, shots_us=1, shots_them=0,
                     box_us=1, att_third_us=1, packing_us=1, territory_us=terr,
                     sequences_us=seq, match_secs_us=match_secs)

def test_aggregate_two_games():
    a = _gs(600.0, 10, Territory(20.0, 30.0, 50.0), 3000, 5)
    b = _gs(300.0, 6, Territory(40.0, 30.0, 30.0), 3000, 2)
    s = aggregate([a, b])
    assert s.games == 2
    assert s.passes_us == 16
    assert s.sequences_us == 7
    assert s.shots_us == 2 and s.box_us == 2 and s.att_third_us == 2 and s.packing_us == 2
    assert s.poss_secs_us == 900.0                     # sum of ball-control secs
    assert s.poss_pct_us == 15.0                       # 900s of 6000s total match
    # duration-weighted territory: def (20*600+40*300)/900=26.7, mid 30, off 43.3
    assert s.territory == Territory(26.7, 30.0, 43.3)

def test_aggregate_pct_none_without_match_length():
    a = _gs(600.0, 10, Territory(20.0, 30.0, 50.0), 0, 5)
    s = aggregate([a])
    assert s.poss_pct_us is None

def test_aggregate_empty():
    s = aggregate([])
    assert s == SeasonStats(0, 0.0, None, 0, 0, 0, 0, 0, 0, Territory(0.0, 0.0, 0.0), 0)
