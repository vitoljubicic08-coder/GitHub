"""Local monitoring dashboard (http://127.0.0.1:8765 by default). Standard library only.

GET  /             the dashboard page (auto-refresh every 2 s)
GET  /api/status   live status published by the running bot (or, with no bot running, the database)
POST /api/kill     emergency stop: requires the token in <state_dir>/dashboard_token.txt
POST /api/disarm   stop taking new entries (same token)
It binds to localhost only by default; nothing is reachable from other computers unless you change it.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).with_name("index.html")


def token_for(state_dir: str | Path) -> str:
    p = Path(state_dir) / "dashboard_token.txt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_urlsafe(16))
    return p.read_text().strip()


def make_handler(get_status, on_kill, on_disarm, token: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the console quiet
            return

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._send(200, json.dumps(get_status(), default=str).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            if body.get("token") != token:
                self._send(403, b'{"ok": false, "error": "wrong token"}', "application/json")
                return
            if self.path == "/api/kill":
                on_kill(body.get("reason") or "dashboard kill button")
            elif self.path == "/api/disarm":
                on_disarm()
            else:
                self._send(404, b"not found", "text/plain")
                return
            self._send(200, b'{"ok": true}', "application/json")
    return H


def serve(host: str, port: int, get_status, on_kill, on_disarm, token: str) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(get_status, on_kill, on_disarm, token))
    threading.Thread(target=srv.serve_forever, daemon=True, name="dashboard").start()
    return srv
