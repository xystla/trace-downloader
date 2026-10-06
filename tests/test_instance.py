import threading

from gui.instance import Instance


def test_a_second_launch_wakes_the_running_app_instead_of_starting_another(tmp_path):
    shown = threading.Event()
    first = Instance(tmp_path)
    assert first.ask_running_copy_to_show() is False          # nothing running yet
    first.listen(shown.set)
    second = Instance(tmp_path)
    assert second.ask_running_copy_to_show() is True
    assert shown.wait(2)
    first.stop()


def test_a_leftover_file_from_a_crashed_run_does_not_block_starting(tmp_path):
    (tmp_path / "instance.json").write_text('{"port": 9, "token": "old"}')
    assert Instance(tmp_path).ask_running_copy_to_show() is False
    (tmp_path / "instance.json").write_text("{not json")
    assert Instance(tmp_path).ask_running_copy_to_show() is False


def test_only_this_app_can_wake_the_window(tmp_path):
    import json, socket
    shown = threading.Event()
    first = Instance(tmp_path)
    first.listen(shown.set)
    port = json.loads((tmp_path / "instance.json").read_text())["port"]
    with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
        s.sendall(b"wrong-token\n")
        s.settimeout(2)
        try:
            s.recv(16)
        except OSError:
            pass
    assert not shown.wait(0.3)
    first.stop()
