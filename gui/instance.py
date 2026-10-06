"""One copy of the app at a time.

With automatic downloads on, TraceDown keeps running after its window is closed.
Opening it again must bring that window back, not start a second copy (two
copies would fight over the same Trace login). The running copy listens on a
port only this computer can reach; a new launch finds it through a small file,
proves it is TraceDown with a shared token, and asks it to show itself.
"""
import json
import secrets
import socket
import threading
from pathlib import Path


class Instance:
    def __init__(self, data_dir):
        self._file = Path(data_dir) / "instance.json"
        self._server = None

    def ask_running_copy_to_show(self) -> bool:
        """True if another copy is running and has been told to show its window."""
        try:
            info = json.loads(self._file.read_text(encoding="utf-8"))
            with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=1.5) as s:
                s.sendall((str(info["token"]) + "\n").encode())
                s.settimeout(1.5)
                return s.recv(16).startswith(b"ok")
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def listen(self, on_show) -> None:
        """Become the running copy: call on_show() whenever another launch asks."""
        token = secrets.token_urlsafe(16)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        self._server = server
        self._file.write_text(json.dumps({"port": server.getsockname()[1], "token": token}),
                              encoding="utf-8")

        def serve():
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return                      # stopped
                with conn:
                    try:
                        conn.settimeout(1.5)
                        if conn.recv(128).decode(errors="replace").strip() == token:
                            conn.sendall(b"ok\n")
                            on_show()
                    except OSError:
                        pass

        threading.Thread(target=serve, daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
            self._file.unlink(missing_ok=True)
