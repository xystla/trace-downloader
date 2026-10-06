import base64
from types import SimpleNamespace


class _Request:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def get(self, url, **kwargs):
        self.calls.append(url)
        return SimpleNamespace(ok=self.ok, body=lambda: b"jpeg-bytes")


def _worker(monkeypatch, tmp_path, request):
    from trace_grabber import paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    from gui import worker
    monkeypatch.setattr(worker, "DATA", tmp_path)
    instance = worker.Worker.__new__(worker.Worker)
    account = SimpleNamespace(id="demo", thumbs_dir=lambda root: tmp_path / "thumbs" / "demo",
                              output_dir=lambda base: tmp_path / "videos")
    instance._accounts = SimpleNamespace(active=account)
    instance._cfg = SimpleNamespace(output_dir=tmp_path / "videos")
    instance._ctx = SimpleNamespace(request=request)
    instance._thumb_prefix = {}
    return instance


EXPECTED = "data:image/jpeg;base64," + base64.b64encode(b"jpeg-bytes").decode("ascii")


def test_thumbnail_is_fetched_once_then_read_from_disk(monkeypatch, tmp_path):
    request = _Request()
    instance = _worker(monkeypatch, tmp_path, request)
    assert instance._get_thumb("demo", "demo-7") == EXPECTED
    assert (tmp_path / "thumbs" / "demo" / "demo-7.jpg").read_bytes() == b"jpeg-bytes"
    fetched = len(request.calls)
    assert instance._get_thumb("demo", "demo-7") == EXPECTED
    assert len(request.calls) == fetched                     # no second trip to Trace


def test_saved_thumbnail_survives_a_restart(monkeypatch, tmp_path):
    _worker(monkeypatch, tmp_path, _Request())._get_thumb("demo", "demo-7")
    offline = _Request(ok=False)
    fresh = _worker(monkeypatch, tmp_path, offline)           # a new app session, Trace unreachable
    assert fresh._get_thumb("demo", "demo-7") == EXPECTED
    assert offline.calls == []


def test_a_thumbnail_that_fails_to_load_is_not_saved(monkeypatch, tmp_path):
    instance = _worker(monkeypatch, tmp_path, _Request(ok=False))
    assert instance._get_thumb("demo", "demo-7") is None
    assert not (tmp_path / "thumbs" / "demo" / "demo-7.jpg").exists()


GAME = ("demo", "demo-7", "2026-06-04", "Rovers")


def test_thumbnail_travels_with_a_downloaded_games_folder(monkeypatch, tmp_path):
    game = tmp_path / "videos" / "2026-06-04_vs-rovers"
    (game / "Full Game").mkdir(parents=True)
    instance = _worker(monkeypatch, tmp_path, _Request())
    assert instance._get_thumb(*GAME) == EXPECTED
    assert (game / "Thumbnail" / "thumbnail.jpg").read_bytes() == b"jpeg-bytes"


def test_thumbnail_in_the_game_folder_is_enough_on_its_own(monkeypatch, tmp_path):
    # e.g. the videos folder was copied to another computer: no app data, no Trace.
    thumb = tmp_path / "videos" / "2026-06-04_vs-rovers" / "Thumbnail" / "thumbnail.jpg"
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"jpeg-bytes")
    offline = _Request(ok=False)
    assert _worker(monkeypatch, tmp_path, offline)._get_thumb(*GAME) == EXPECTED
    assert offline.calls == []


def test_no_folder_is_made_for_a_game_that_was_never_downloaded(monkeypatch, tmp_path):
    instance = _worker(monkeypatch, tmp_path, _Request())
    assert instance._get_thumb(*GAME) == EXPECTED
    assert not (tmp_path / "videos").exists()
    assert (tmp_path / "thumbs" / "demo" / "demo-7.jpg").exists()      # kept in the app's own data


def test_thumbnail_is_copied_into_the_folder_once_the_game_is_downloaded(monkeypatch, tmp_path):
    instance = _worker(monkeypatch, tmp_path, _Request())
    instance._get_thumb(*GAME)                                         # before download: app data only
    game = tmp_path / "videos" / "2026-06-04_vs-rovers"
    (game / "Full Game").mkdir(parents=True)
    offline = _Request(ok=False)
    instance._ctx = SimpleNamespace(request=offline)
    assert instance._get_thumb(*GAME) == EXPECTED
    assert (game / "Thumbnail" / "thumbnail.jpg").read_bytes() == b"jpeg-bytes" and offline.calls == []


def test_fetching_a_thumbnail_keeps_windows_awake(monkeypatch, tmp_path):
    from trace_grabber import platform_tasks as pt
    calls = []
    monkeypatch.setattr(pt.sys, "platform", "win32")
    monkeypatch.setattr(pt, "_set_execution_state", calls.append)
    instance = _worker(monkeypatch, tmp_path, _Request())
    during = []
    real_get = instance._ctx.request.get
    def get(url, **kwargs):
        during.append(list(calls))
        return real_get(url, **kwargs)
    instance._ctx.request.get = get
    assert instance._get_thumb("demo", "demo-7") == EXPECTED
    assert during[0] == [pt.ES_CONTINUOUS | pt.ES_SYSTEM_REQUIRED] and calls[-1] == pt.ES_CONTINUOUS
