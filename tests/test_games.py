from pathlib import Path
from trace_grabber.games import parse_games, team_paths, Game


def test_team_paths_uses_current_url_when_page_has_no_links():
    # The user is standing on their team page, which doesn't link to itself.
    url = "https://go.traceup.com/traceid/team/hjmwnzo2"
    assert team_paths(url, "<html>no team links here</html>") == ["/traceid/team/hjmwnzo2"]


def test_team_paths_current_url_first_then_links_deduped():
    url = "https://go.traceup.com/traceid/team/aaa111"
    html = 'x <a href="/traceid/team/aaa111">me</a> <a href="/traceid/team/bbb222">o</a>'
    assert team_paths(url, html) == ["/traceid/team/aaa111", "/traceid/team/bbb222"]


def test_team_paths_no_url_falls_back_to_links():
    html = '<a href="/traceid/team/ccc333">t</a>'
    assert team_paths("https://traceup.com/", html) == ["/traceid/team/ccc333"]

FIXTURE = Path(__file__).parent / "fixtures" / "games_sample.html"

def test_parses_all_cards():
    games = parse_games(FIXTURE.read_text())
    assert len(games) == 3
    assert all(isinstance(g, Game) for g in games)

def test_first_card_fields():
    g = parse_games(FIXTURE.read_text())[0]
    assert g.id == "demoteam1-1001"
    assert g.team_id == "demoteam1"
    assert g.date == "2026-05-28"
    assert g.opponent == "Rovers"

def test_opponent_parsed_for_each():
    opps = [g.opponent for g in parse_games(FIXTURE.read_text())]
    assert opps == ["Rovers", "United", "Athletic"]

def test_full_month_name_dates():
    # Trace shows full month names; "June" must not crash (only "May" is 3 letters).
    from trace_grabber.games import _iso_date
    assert _iso_date("June 4, 2026 @ 7:30 pm") == "2026-06-04"
    assert _iso_date("August 12, 2026") == "2026-08-12"
    assert _iso_date("May 28, 2026") == "2026-05-28"

def test_no_duplicate_ids():
    games = parse_games(FIXTURE.read_text())
    assert len(games) == len({g.id for g in games})


def test_card_attributes_and_classes_can_be_reordered():
    text = FIXTURE.read_text().replace('<a class="GameLink GameCard" href="#game-link">',
        "<a href='#game-link' class='extra GameCard GameLink'>")
    text = text.replace('class="two-lines label text-bold"', "class='text-bold label two-lines'")
    text = text.replace('Demo FC vs. Rovers', 'Demo FC vs. <span>Rovers</span>')
    games = parse_games(text)
    assert len(games) == 3
    assert games[0].opponent == 'Rovers'
    assert games[1].opponent == 'United'


def test_unrelated_posters_are_not_games():
    assert parse_games('<img src="/teams/demo/games/demo-123/poster.jpg">') == []


def test_api_fallback_filters_access_and_sorts_newest(monkeypatch):
    from trace_grabber import games, analytics
    monkeypatch.setattr(analytics, 'team_numeric_id', lambda *args: 5)
    monkeypatch.setattr(analytics, 'user_token', lambda *args: {'token': 'fake'})
    def row(number, date, allowed=True, status='ready'):
        return {'game_id': number, 'full_date': date, 'status': status,
                'access': {'allowed': allowed},
                'home_team': {'team_id': 5, 'title': 'Our team'},
                'away_team': {'team_id': 8, 'title': 'Rivals'}}
    monkeypatch.setattr(analytics, 'fetch_team_games', lambda *args: {
        1: row(1, '2026-01-01'), 2: row(2, '2026-09-22'),
        3: row(3, '2026-09-23', allowed=False),
        4: row(4, '2026-09-24', status='processing')})
    result = games._list_api_games(object(), 'https://go.traceup.com/traceid/team/demo', 60)
    assert [g.id for g in result] == ['demo-2', 'demo-1']
    assert result[0].opponent == 'Rivals'


def test_page_failure_uses_authenticated_api(monkeypatch):
    from types import SimpleNamespace
    from trace_grabber import games
    def fail(*args):
        raise RuntimeError('no cards')
    monkeypatch.setattr(games, '_list_page_games', fail)
    request = object()
    def fallback(req, url, limit):
        assert req is request
        return ['recovered']
    monkeypatch.setattr(games, '_list_api_games', fallback)
    assert games.list_games(SimpleNamespace(context=SimpleNamespace(request=request)), 'team') == ['recovered']


def test_both_listing_failures_are_reported(monkeypatch):
    import pytest
    from types import SimpleNamespace
    from trace_grabber import games
    def fail_page(*args):
        raise RuntimeError('page timed out')
    def fail_api(*args):
        raise RuntimeError('API unavailable')
    monkeypatch.setattr(games, '_list_page_games', fail_page)
    monkeypatch.setattr(games, '_list_api_games', fail_api)
    with pytest.raises(RuntimeError, match='page timed out.*API unavailable'):
        games.list_games(SimpleNamespace(context=SimpleNamespace(request=None)), 'team')
