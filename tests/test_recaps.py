from pathlib import Path

from trace_grabber import recaps
from trace_grabber.recaps import Player

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXTINF:2.000000,
https://go.traceup.com/x/global_id_home_10_period_h2_interval_0/video_3000k002.ts
#EXT-X-DISCONTINUITY
#EXTINF:2.000000,
https://go.traceup.com/x/global_id_home_10_period_h2_interval_1/video_3000k002.ts
"""


def _member(number, user_id, name="", dummy=False, in_game=True, is_player=True):
    return {"jersey_number": number, "user_id": user_id, "is_player": is_player,
            "game_player_id": 99 if in_game else None,
            "user": {"user_id": user_id, "name": name, "is_dummy": dummy}}


def test_players_are_the_games_roster_in_shirt_number_order():
    members = [_member("10", 3, "Player", dummy=True), _member("7", 2, "Sage S."),
               _member("", 5, "Player 9.", dummy=True), _member("2", 1, "Ana R."),
               _member("4", 6, "Coach", is_player=False), _member("8", 7, "Not Playing", in_game=False)]
    assert recaps.players_from(members) == [
        Player(1, "2", "Ana R."), Player(2, "7", "Sage S."), Player(3, "10", ""), Player(5, "", "")]


def test_recap_request_names_the_player_and_game():
    url = recaps.recap_url(14312997, 14349837, "2026-10-06")
    assert url.startswith("https://go.traceup.com/recaps/v5?")
    assert "players=14312997" in url and "game_ids=14349837" in url and "date_from=2026-10-06" in url


def test_best_stream_is_the_highest_quality():
    streams = [{"level": "1000k", "data": "a"}, {"level": "3000k", "data": "b"}, {"level": "2000k", "data": "c"}]
    assert recaps.best_stream({"hls": {"streams": streams}}) == "b"
    assert recaps.best_stream({"hls": {"streams": []}}) is None
    assert recaps.best_stream({}) is None


def test_segment_urls_come_from_the_playlist_in_order():
    assert recaps.segment_urls(PLAYLIST) == [
        "https://go.traceup.com/x/global_id_home_10_period_h2_interval_0/video_3000k002.ts",
        "https://go.traceup.com/x/global_id_home_10_period_h2_interval_1/video_3000k002.ts"]


def test_recap_file_is_named_for_the_player():
    assert recaps.recap_name(Player(1, "7", "Sage S.")) == "player-07-sage-s.mp4"
    assert recaps.recap_name(Player(3, "10", "")) == "player-10.mp4"
    assert recaps.recap_name(Player(5, "", "")) == "player-5.mp4"


def test_recap_download_joins_its_segments(tmp_path, monkeypatch):
    from trace_grabber import segments
    calls = []
    monkeypatch.setattr(segments, "download", lambda urls, dest, **kw: calls.append((urls, dest, kw)))
    urls = recaps.segment_urls(PLAYLIST)
    recaps.download(urls, tmp_path / "player-10.mp4", progress_cb="cb", on_proc="hook")
    assert calls == [(urls, tmp_path / "player-10.mp4",
                      {"total_secs": 4, "progress_cb": "cb", "on_proc": "hook"})]


def test_traces_placeholder_names_are_not_shown_as_player_names():
    members = [_member("2", 1, "Dummy Tracer 1756142087-5306-ybol6sz6"), _member("3", 2, "dummy tracer 17"),
               _member("4", 4, "dummy-tracer-1756142087-6827-clslyknf"), _member("9", 3, "Tracey Dummett")]
    assert recaps.players_from(members) == [Player(1, "2", ""), Player(2, "3", ""), Player(4, "4", ""),
                                            Player(3, "9", "Tracey Dummett")]
    assert recaps.recap_name(recaps.players_from(members)[0]) == "player-02.mp4"
