from trace_grabber import found, state


def test_a_found_video_is_remembered_per_game(tmp_path):
    store = tmp_path / "found" / "demo.json"
    assert found.load(store) == {} and found.existing(store, "g-1") == []
    video = tmp_path / "elsewhere" / "game.mp4"
    video.parent.mkdir()
    video.write_bytes(b"x")
    found.remember(store, "g-1", [video])
    assert found.load(store) == {"g-1": [str(video)]}
    assert found.existing(store, "g-1") == [video] and found.existing(store, "g-2") == []


def test_a_found_video_that_cannot_be_reached_is_kept_but_not_offered(tmp_path):
    store = tmp_path / "found.json"
    video = tmp_path / "drive" / "game.mp4"
    found.remember(store, "g-1", [video])                 # the drive isn't connected
    assert found.existing(store, "g-1") == []
    video.parent.mkdir()
    video.write_bytes(b"x")                               # and now it is
    assert found.existing(store, "g-1") == [video]


def test_found_halves_come_after_a_whole_game(tmp_path):
    store = tmp_path / "found.json"
    names = ["g_half2.mp4", "g_half1.mp4", "g.mp4"]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    found.remember(store, "g-1", [tmp_path / name for name in names])
    assert [p.name for p in found.existing(store, "g-1")] == ["g.mp4", "g_half1.mp4", "g_half2.mp4"]


def test_forgetting_and_a_damaged_store(tmp_path):
    store = tmp_path / "found.json"
    found.remember(store, "g-1", ["/a.mp4"])
    found.remember(store, "g-2", ["/b.mp4"])
    found.forget(store, "g-1")
    found.forget(store, "never-there")
    assert found.load(store) == {"g-2": ["/b.mp4"]}
    store.write_text("{not json")
    assert found.load(store) == {}
    store.write_text('["a list"]')
    assert found.load(store) == {}
    store.write_text('{"g-1": "not a list", "g-2": ["/b.mp4", 7]}')
    assert found.load(store) == {"g-2": ["/b.mp4"]}


def test_a_game_can_be_un_saved(tmp_path):
    path = tmp_path / "state.json"
    state.unmark(path, "g-1")                             # nothing saved yet: no file is made
    assert not path.exists()
    state.mark_done(path, "g-1")
    state.mark_done(path, "g-2")
    state.unmark(path, "g-1")
    assert state.load_state(path) == {"g-2"}
