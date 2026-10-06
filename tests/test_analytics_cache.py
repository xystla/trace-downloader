from trace_grabber import analytics_cache as cache
from trace_grabber.analytics import GameMeta

META = GameMeta(game_id=7, date="2026-09-26", opponent="Rivals", our_side="home", match_secs=5400)
MOMENTS = [{"type": "touch_chain", "side": "home", "duration": 10}]


def test_saved_game_loads_back_identically(tmp_path):
    cache.save(tmp_path / "analytics" / "demo", META, MOMENTS)
    assert cache.load(tmp_path / "analytics" / "demo", 7) == (META, MOMENTS)


def test_cached_ids_lists_saved_games_only(tmp_path):
    assert cache.cached_ids(tmp_path / "nowhere") == set()
    cache.save(tmp_path, META, MOMENTS)
    (tmp_path / "notes.txt").write_text("not a game")
    assert cache.cached_ids(tmp_path) == {7}


def test_missing_or_damaged_game_loads_as_none(tmp_path):
    assert cache.load(tmp_path, 7) is None
    (tmp_path / "7.json").write_text("{not json")
    assert cache.load(tmp_path, 7) is None


def test_games_without_stats_are_remembered_for_a_day(tmp_path):
    assert cache.known_empty(tmp_path, now=1000) == set()
    cache.save_empty(tmp_path, {3, 4}, now=1000)
    cache.save_empty(tmp_path, {5}, now=2000)
    assert cache.known_empty(tmp_path, now=3000) == {3, 4, 5}
    assert cache.known_empty(tmp_path, now=1000 + cache.EMPTY_RECHECK_SECS + 1) == {5}
    assert cache.cached_ids(tmp_path) == set()


def test_viewing_stats_is_remembered_per_account(tmp_path):
    assert cache.was_viewed(tmp_path / "demo") is False
    cache.save(tmp_path / "demo", META, MOMENTS)          # saved by highlights, not a viewing
    assert cache.was_viewed(tmp_path / "demo") is False
    cache.mark_viewed(tmp_path / "demo")
    assert cache.was_viewed(tmp_path / "demo") is True
    assert cache.cached_ids(tmp_path / "demo") == {7}


def test_stats_are_kept_in_the_games_own_analytics_folder(tmp_path):
    import json
    game = tmp_path / "2026-09-26_vs-rivals"
    game.mkdir()
    assert cache.save_with_game(game, META, MOMENTS) is True
    saved = json.loads((game / "Analytics" / "stats.json").read_text())
    assert saved["meta"]["opponent"] == "Rivals" and saved["moments"] == MOMENTS
    assert set(saved["stats"]) == {"whole", "first", "second"}        # readable numbers, not just raw data
    assert saved["stats"]["whole"]["poss_secs_us"] == 10.0
    assert cache.load_file(game / "Analytics" / "stats.json") == (META, MOMENTS)


def test_no_game_folder_is_made_just_for_stats(tmp_path):
    assert cache.save_with_game(tmp_path / "2026-09-26_vs-rivals", META, MOMENTS) is False
    assert list(tmp_path.iterdir()) == []


def test_stats_in_game_folders_can_be_found_again(tmp_path):
    game = tmp_path / "2026-09-26_vs-rivals"
    game.mkdir()
    cache.save_with_game(game, META, MOMENTS)
    (tmp_path / "other-folder").mkdir()
    (tmp_path / "broken" / "Analytics").mkdir(parents=True)
    (tmp_path / "broken" / "Analytics" / "stats.json").write_text("{not json")
    assert cache.in_game_folders(tmp_path) == {7: game / "Analytics" / "stats.json"}
    assert cache.in_game_folders(tmp_path / "nowhere") == {}
    assert cache.load_file(tmp_path / "broken" / "Analytics" / "stats.json") is None
