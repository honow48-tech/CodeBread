"""Tiny local web server (stdlib only) that serves the UI + graph JSON."""
from __future__ import annotations

import json
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WEB_ROOT = os.path.realpath(WEB_DIR)

MIME = {".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon"}


def safe_web_path(rel: str) -> Optional[str]:
    """Resolve a request path against WEB_DIR and return it only if the
    *resolved* result is still inside WEB_DIR, else None.

    String-prefix checks on `rel` alone aren't enough: on Windows,
    os.path.join(WEB_DIR, "C:/some/file") silently discards WEB_DIR because
    the second argument is drive-absolute, which would otherwise let a
    request read any file on disk. Kept as a standalone function so the
    traversal guard has a direct regression test, not just cli/browser use.
    """
    full = os.path.realpath(os.path.join(WEB_DIR, rel))
    try:
        inside = os.path.commonpath([full, WEB_ROOT]) == WEB_ROOT
    except ValueError:
        inside = False  # e.g. different drives on Windows
    return full if inside else None


def _free_port(preferred: int) -> Optional[int]:
    """Find a bindable port near `preferred`, or None if none was free.
    `preferred == 0` means "let the OS pick" and always succeeds — must
    return that as a distinct value from "no port found", since 0 is a
    falsy int and `if not port:` would otherwise treat a successful
    OS-assigned bind as failure."""
    for port in [preferred] + list(range(preferred + 1, preferred + 30)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def _make_handler(data_bytes: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._file("index.html")
            elif path == "/data.json":
                self._bytes(data_bytes, "application/json; charset=utf-8")
            else:
                self._file(path.lstrip("/"))

        def _file(self, rel: str):
            full = safe_web_path(rel)
            if full is None:
                self.send_error(403)
                return
            if not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            ext = os.path.splitext(full)[1].lower()
            self._bytes(body, MIME.get(ext, "application/octet-stream"))

        def _bytes(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # keep the console clean
            pass

    return Handler


def build_server(graph: Dict, port: int = 8137) -> Optional[ThreadingHTTPServer]:
    """Bind a ready-to-serve ThreadingHTTPServer, or None if no port was
    free. Split out from `serve()` so tests (and other embedders) can start
    and cleanly `.shutdown()` a server instead of blocking forever."""
    data_bytes = json.dumps(graph, ensure_ascii=False).encode("utf-8")
    bound_port = _free_port(port)
    if bound_port is None:
        return None
    return ThreadingHTTPServer(("127.0.0.1", bound_port), _make_handler(data_bytes))


def serve(graph: Dict, port: int = 8137, open_browser: bool = True) -> None:
    server = build_server(graph, port)
    if server is None:
        print("[codebread] No free port found near 8137 — aborting serve.")
        return
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"[codebread] Serving at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[codebread] Stopped.")
    finally:
        server.server_close()
