"""A tiny local web server that lets the app's page play downloaded videos.

The page can't open files on disk directly, and a video player needs to ask for
arbitrary parts of the file to scrub, so each video is given a private address
on this computer only (127.0.0.1) and served with byte-range support. Only files
the app has registered are reachable, each behind an unguessable token.
"""
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

_CHUNK = 256 * 1024


class MediaServer:
    def __init__(self):
        self._tokens: dict[str, Path] = {}
        self._by_path: dict[Path, str] = {}
        self._server = None
        self._lock = threading.Lock()

    def _start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):       # keep the console quiet
                pass

            def do_HEAD(self):
                self._serve(body=False)

            def do_GET(self):
                self._serve(body=True)

            def _serve(self, body):
                parts = self.path.split("?")[0].strip("/").split("/")
                path = owner._tokens.get(unquote(parts[0])) if len(parts) == 2 else None
                if path is None or not path.is_file():
                    self.send_error(404)
                    return
                size = path.stat().st_size
                start, end = 0, size - 1
                rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
                if rng and (rng.group(1) or rng.group(2)):
                    if rng.group(1):
                        start = int(rng.group(1))
                        end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                    else:                        # "bytes=-N": the last N bytes
                        start = max(0, size - int(rng.group(2)))
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                if not body:
                    return
                try:
                    with open(path, "rb") as f:
                        f.seek(start)
                        left = end - start + 1
                        while left > 0:
                            chunk = f.read(min(_CHUNK, left))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            left -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass                         # the player stopped or jumped elsewhere

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass                             # players drop connections all the time when scrubbing

        self._server = Server(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def url_for(self, path) -> str:
        """A local address the page can play this file from."""
        path = Path(path)
        with self._lock:
            if self._server is None:
                self._start()
            token = self._by_path.get(path)
            if token is None:
                token = secrets.token_urlsafe(16)
                self._by_path[path] = token
                self._tokens[token] = path
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/{token}/{quote(path.name)}"

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
