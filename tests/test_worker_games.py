from types import SimpleNamespace


def test_one_failed_team_does_not_hide_other_teams(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, 'data_dir', lambda: tmp_path)
    from gui import worker
    from trace_grabber.games import Game
    instance = worker.Worker.__new__(worker.Worker)
    account = SimpleNamespace(team_urls=['old', 'current', 'duplicate'], label='My team',
                              state_path=lambda root: tmp_path / 'state.json')
    instance._accounts = SimpleNamespace(active=account)
    instance._page = object()
    game = Game('demo-1', 'demo', '2026-09-22', 'Rivals', 'Demo vs. Rivals')
    def listing(page, url):
        if url == 'old':
            raise RuntimeError('Old team is unavailable')
        return [game]
    monkeypatch.setattr(worker, 'list_games', listing)
    result, done = instance._list_games()
    assert result == [game]
    assert done == set()
    assert instance._games_errors == ['Old team is unavailable']
    account.team_urls = ['current']
    instance._list_games()
    assert instance._games_errors == []
