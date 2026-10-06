from trace_grabber import radar


def tracking(frames, athletes):
    return {"setup": {"athletes": athletes}, "frm": [{"t": i * 500, "a": a} for i, a in enumerate(frames)]}


def who(team, pos=""):
    return {"team": team, "pos": pos, "jersey": "9"}


US = {"1": who("us"), "2": who("us"), "7": who("them"), "50": who("us"), "60": who("us", "goalie")}
CORNER = radar.COLS - 1      # the grid column at the right-hand end


def spot(x, y):
    return {"l": [x, y], "h": [0, 0]}


def test_counts_only_our_outfield_players_into_the_grid():
    # "50" never leaves the left goal: that is our goalkeeper, whatever Trace labels them.
    data = tracking([{"1": spot(990, 10), "7": spot(500, 500), "99": spot(500, 500), "50": spot(20, 500)},
                     {"1": spot(300, 10), "2": spot(990, 10), "50": spot(30, 520)},
                     {"1": spot(990, 10), "50": spot(25, 480)}], US)
    heat = radar.heat(data, "us")
    assert heat["samples"] == 4 and heat["players"] == 2
    assert heat["grid"][0][CORNER] == 3
    assert sum(map(sum, heat["grid"])) == 4


def test_a_player_labelled_goalkeeper_who_roams_is_counted_as_an_outfield_player():
    data = tracking([{"60": spot(200, 500)}, {"60": spot(700, 500)}], US)
    assert radar.heat(data, "us")["samples"] == 2


def test_a_half_defending_the_right_end_is_turned_to_attack_right():
    # Our goalkeeper stands at the right end, so our team attacks left in this half.
    data = tracking([{"50": spot(980, 500), "1": spot(5, 0)}, {"50": spot(970, 520), "1": spot(400, 0)},
                     {"50": spot(985, 510), "1": spot(700, 0)}], US)
    heat = radar.heat(data, "us")
    assert heat["samples"] == 3 and heat["grid"][radar.ROWS - 1][CORNER] == 1


def test_the_other_teams_goalkeeper_also_tells_the_direction():
    data = tracking([{"7": spot(20, 500), "1": spot(5, 0)}, {"7": spot(25, 500), "1": spot(500, 0)}], US)
    # They defend the left end, so we attack left: the picture is turned round.
    assert radar.heat(data, "us")["grid"][radar.ROWS - 1][CORNER] == 1


def test_without_a_goalkeeper_the_side_comes_from_where_each_team_stands():
    athletes = {"1": who("us"), "7": who("them")}
    frames = [{"1": spot(800, 500), "7": spot(200, 500)}, {"1": spot(600, 500), "7": spot(400, 500)}] * 2
    heat = radar.heat(tracking(frames, athletes), "us")       # we sit to the right: attacking left
    assert sum(sum(row[:radar.COLS // 2]) for row in heat["grid"]) == 4


def test_positions_off_the_field_and_empty_frames_are_tolerated():
    data = tracking([[], {"1": spot(-20, 1075)}, {"1": {"h": [1, 2]}}, {"1": spot(500, 500)}], US)
    heat = radar.heat(data, "us")
    assert heat["samples"] == 2 and heat["grid"][radar.ROWS - 1][0] == 1


def test_no_tracked_players_of_ours_gives_nothing():
    assert radar.heat(tracking([{"7": spot(1, 1)}], US), "us") is None
    assert radar.heat({}, "us") is None


def half(*spots):
    return radar.heat(tracking([{"1": s} for s in spots] + [{"2": spot(500, 500)}], US), "us")


def test_build_adds_the_halves_into_a_whole_game():
    first = half(spot(990, 10), spot(400, 400))
    second = half(spot(990, 10), spot(10, 990))
    built = radar.build({1: first, 2: second})
    assert built["cols"] == radar.COLS and built["rows"] == radar.ROWS
    assert built["whole"]["samples"] == 6 and built["whole"]["players"] == 2
    assert built["whole"]["grid"][0][CORNER] == 2
    assert built["first"] == first and built["second"] == second
    assert radar.build({1: None, 2: None}) is None
    assert radar.build({1: first})["second"] is None


def test_saved_heat_map_is_read_back_and_copied_into_the_game_folder(tmp_path):
    built = radar.build({1: half(spot(5, 5), spot(600, 300))})
    game_root = tmp_path / "videos" / "2026-10-03_vs-Rovers"
    game_root.mkdir(parents=True)
    radar.save(tmp_path / "cache", 77, built, game_root=game_root)
    assert radar.load(tmp_path / "cache", 77) == built
    assert (game_root / "Analytics" / "heatmap.json").exists()
    assert radar.load(tmp_path / "empty", 77, game_root=game_root) == built      # portable: the folder alone is enough
    assert radar.load(tmp_path / "empty", 78) is None


def test_a_game_without_a_folder_is_only_cached(tmp_path):
    built = radar.build({1: half(spot(5, 5), spot(600, 300))})
    radar.save(tmp_path / "cache", 77, built, game_root=tmp_path / "not-downloaded")
    assert not (tmp_path / "not-downloaded").exists()


def test_radar_file_sits_beside_the_half_video():
    master = "https://go.traceup.com/us-west-2/soccer/api/teams/t/games/t-5/gamevideo2.hls/game_video.m3u8"
    assert radar.radar_url(master, 2) == "https://go.traceup.com/us-west-2/soccer/api/teams/t/games/t-5/radar2_dynamic.json"
