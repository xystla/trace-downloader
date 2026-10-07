import threading
from types import SimpleNamespace


def _record_execution_state(monkeypatch):
    from trace_grabber import platform_tasks as pt
    calls = []
    monkeypatch.setattr(pt.sys, "platform", "win32")
    monkeypatch.setattr(pt, "_set_execution_state", calls.append)
    return pt, calls


def _account(tmp_path):
    return SimpleNamespace(id="demo", output_dir=lambda base: tmp_path,
                           state_path=lambda root: tmp_path / "state.json")


def test_gui_download_keeps_windows_awake_only_while_downloading(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    pt, calls = _record_execution_state(monkeypatch)
    instance = worker.Worker.__new__(worker.Worker)
    instance._accounts = SimpleNamespace(active=_account(tmp_path))
    instance._ctx = object()
    instance._cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False)
    instance._cancel = threading.Event()
    monkeypatch.setattr(worker, "cookie_headers", lambda ctx: {})
    during = []
    def resolve(team_id, game_id):
        during.append(list(calls))
        return []
    instance._resolve_masters = resolve
    assert calls == []
    instance._download_game("demo-1", "demo", "2026-09-22", "Rivals", lambda *a: None)
    assert during == [[pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED]]
    assert calls[-1] == pt.ES_CONTINUOUS


def test_scheduled_download_keeps_windows_awake_only_while_downloading(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from trace_grabber import main
    pt, calls = _record_execution_state(monkeypatch)
    during = []
    def resolve(request, page, athlete_getter, team_id, game_id):
        during.append(list(calls))
        return []
    monkeypatch.setattr(main.streams, "resolve_masters", resolve)
    game = SimpleNamespace(id="demo-1", team_id="demo", date="2026-09-22", opponent="Rivals")
    cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False)
    main._download_game(SimpleNamespace(request=None), None, None, {}, cfg, _account(tmp_path), game)
    assert during == [[pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED]]
    assert calls[-1] == pt.ES_CONTINUOUS


class _Request:
    def get(self, url, **kwargs):
        return SimpleNamespace(text=lambda: "")


def _stats_calls(monkeypatch, fail=False):
    from trace_grabber import analytics_sync
    calls = []
    def moments_for(request, acct, data_dir, num, videos_dir=None):
        calls.append(num)
        if fail:
            raise RuntimeError("trace is down")
    monkeypatch.setattr(analytics_sync, "moments_for", moments_for)
    return calls


def _gui_worker(monkeypatch, tmp_path, masters):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", tmp_path)
    instance = worker.Worker.__new__(worker.Worker)
    instance._accounts = SimpleNamespace(active=_account(tmp_path))
    instance._ctx = SimpleNamespace(request=_Request())
    instance._cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False, quality="highest")
    instance._cancel = threading.Event()
    instance._resolve_masters = lambda team_id, game_id: masters
    monkeypatch.setattr(worker, "cookie_headers", lambda ctx: {})
    monkeypatch.setattr(worker.quality, "pick_variant", lambda text, url, quality: ("variant", 0))
    monkeypatch.setattr(worker.segments, "parse", lambda text, url: [(2.0, "https://t/a.ts")])
    def fetch(parts, dest, headers, quality, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"video")
    monkeypatch.setattr(worker.pieces, "fetch", fetch)
    return instance


def test_downloading_a_game_in_the_app_also_saves_its_stats(monkeypatch, tmp_path):
    calls = _stats_calls(monkeypatch)
    instance = _gui_worker(monkeypatch, tmp_path, ["half1", "half2"])
    assert instance._download_game("demo-7", "demo", "2026-09-22", "Rivals", lambda *a: None) == 2
    assert calls == [7]


def test_game_video_is_saved_into_the_games_full_game_folder(monkeypatch, tmp_path):
    _stats_calls(monkeypatch)
    instance = _gui_worker(monkeypatch, tmp_path, ["half1", "half2"])
    from gui import worker
    saved = []
    def fetch(parts, dest, headers, quality, **kwargs):
        saved.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"video")
    monkeypatch.setattr(worker.pieces, "fetch", fetch)
    instance._download_game("demo-7", "demo", "2026-09-22", "Rivals", lambda *a: None)
    full = tmp_path / "2026-09-22_vs-rivals" / "Full Game"
    assert saved == [full / "2026-09-22_vs-rivals_half1.mp4", full / "2026-09-22_vs-rivals_half2.mp4"]


def test_scheduled_download_uses_the_same_folders(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from trace_grabber import main
    monkeypatch.setattr(main, "DATA", tmp_path)
    _stats_calls(monkeypatch)
    saved = []
    monkeypatch.setattr(main.streams, "resolve_masters", lambda *args: ["half1"])
    monkeypatch.setattr(main.quality, "pick_from_master", lambda text, url, quality: "variant")
    monkeypatch.setattr(main, "download", lambda url, dest, *args, **kwargs: saved.append(dest))
    game = SimpleNamespace(id="demo-7", team_id="demo", date="2026-09-22", opponent="Rivals")
    cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False, quality="highest")
    main._download_game(SimpleNamespace(request=_Request()), None, None, {}, cfg, _account(tmp_path), game)
    assert saved == [tmp_path / "2026-09-22_vs-rivals" / "Full Game" / "2026-09-22_vs-rivals_half1.mp4"]


def test_a_stats_failure_does_not_fail_the_download(monkeypatch, tmp_path):
    _stats_calls(monkeypatch, fail=True)
    instance = _gui_worker(monkeypatch, tmp_path, ["half1", "half2"])
    assert instance._download_game("demo-7", "demo", "2026-09-22", "Rivals", lambda *a: None) == 2


def test_no_stats_are_fetched_when_nothing_was_downloaded(monkeypatch, tmp_path):
    calls = _stats_calls(monkeypatch)
    instance = _gui_worker(monkeypatch, tmp_path, [])
    instance._download_game("demo-7", "demo", "2026-09-22", "Rivals", lambda *a: None)
    assert calls == []


def test_scheduled_download_also_saves_the_games_stats(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from trace_grabber import main
    monkeypatch.setattr(main, "DATA", tmp_path)
    calls = _stats_calls(monkeypatch)
    monkeypatch.setattr(main.streams, "resolve_masters", lambda *args: ["half1", "half2"])
    monkeypatch.setattr(main.quality, "pick_from_master", lambda text, url, quality: "variant")
    monkeypatch.setattr(main, "download", lambda *args, **kwargs: None)
    game = SimpleNamespace(id="demo-7", team_id="demo", date="2026-09-22", opponent="Rivals")
    cfg = SimpleNamespace(output_dir=tmp_path, combine_halves=False, quality="highest")
    ctx = SimpleNamespace(request=_Request())
    assert main._download_game(ctx, None, None, {}, cfg, _account(tmp_path), game) == 2
    assert calls == [7]


def _awake_during(monkeypatch):
    """Record the stay-awake calls; returns (platform_tasks, calls)."""
    return _record_execution_state(monkeypatch)


def test_loading_stats_keeps_windows_awake(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    pt, calls = _awake_during(monkeypatch)
    instance = worker.Worker.__new__(worker.Worker)
    instance._accounts = SimpleNamespace(active=None)
    instance._compute_analytics()
    instance._save_stats()
    held, released = pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED, pt.ES_CONTINUOUS
    assert calls == [held, released, held, released]


def test_scheduled_stats_save_keeps_windows_awake(monkeypatch, tmp_path):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from trace_grabber import analytics_sync, main
    pt, calls = _awake_during(monkeypatch)
    during = []
    monkeypatch.setattr(analytics_sync, "save_recent", lambda *a, **k: during.append(list(calls)))
    main._save_stats(SimpleNamespace(request=None), SimpleNamespace(label="Demo"), tmp_path)
    assert during == [[pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED]] and calls[-1] == pt.ES_CONTINUOUS


def test_downloading_an_update_keeps_windows_awake(monkeypatch, tmp_path):
    from gui import app
    from trace_grabber import updates
    pt, calls = _awake_during(monkeypatch)
    api = app.Api()
    api._emit = lambda *a: None
    api._update = updates.Release("9.9.9", [], "https://gh/x.zip", 10, None, "x.zip")
    during = []
    monkeypatch.setattr(app.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(app.updates, "download", lambda *a, **k: during.append(list(calls)) or tmp_path / "x.zip")
    monkeypatch.setattr(app.updates, "start_install", lambda path: True)
    monkeypatch.setattr(api, "_quit_soon", lambda: None)
    assert api.install_update() == {"ok": True, "restarting": True}
    assert during == [[pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED]] and calls[-1] == pt.ES_CONTINUOUS
