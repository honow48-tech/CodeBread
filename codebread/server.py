"""Tiny local web server (stdlib only) that serves the UI + graph JSON."""
from __future__ import annotations

import json
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

MIME = {".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon"}


def _free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 30)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def serve(graph: Dict, port: int = 8137, open_browser: bool = True) -> None:
    data_bytes = json.dumps(graph, ensure_ascii=False).encode("utf-8")

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
            rel = os.path.normpath(rel).replace("\\", "/")
            if rel.startswith("..") or rel.startswith("/"):
                self.send_error(403)
                return
            full = os.path.join(WEB_DIR, rel)
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

    port = _free_port(port)
    if not port:
        print("[codebread] No free port found near 8137 — aborting serve.")
        return
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"[codebread] Serving at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[codebread] Stopped.")
    finally:
        server.server_close()
