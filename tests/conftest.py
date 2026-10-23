import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "skills" / "kaloboost" / "scripts")
)


class MockBoost(BaseHTTPRequestHandler):
    """Scriptable Kaloboost mock.

    server.responses[path] is a dict body (200), a (status, body[, headers]) tuple,
    a list of those (served in order, last one repeats), or a callable(query, body).
    """

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        if self.headers.get("Content-Type", "").startswith("multipart/"):
            self._respond(raw)  # uploads: tests inspect the raw bytes
        else:
            self._respond(json.loads(raw) if raw else None)

    do_PATCH = do_POST

    def do_GET(self):
        self._respond(None)

    def _respond(self, body):
        headers = {k.lower(): v for k, v in self.headers.items()}
        path, _, qs = self.path.partition("?")
        query = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}
        self.server.requests.append((self.command, path, query, headers, body))
        spec = self.server.responses.get(path, {"data": [], "page": {"next_cursor": None, "has_more": False}})
        if isinstance(spec, list):
            spec = spec.pop(0) if len(spec) > 1 else spec[0]
        if callable(spec):
            spec = spec(query, body)
        status, payload, extra = 200, spec, {}
        if isinstance(spec, tuple):
            status, payload = spec[0], spec[1]
            extra = spec[2] if len(spec) > 2 else {}
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), MockBoost)
    server.responses = {}
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield server
    server.shutdown()


@pytest.fixture
def env(monkeypatch, mock_server, tmp_path):
    monkeypatch.setenv("KALODATA_API_KEY", "test-key")
    monkeypatch.setenv("KALOBOOST_BASE_URL", f"http://127.0.0.1:{mock_server.server_address[1]}")
    monkeypatch.setenv("KALODATA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KALOBOOST_NO_UPDATE_CHECK", "1")
    monkeypatch.delenv("KALOBOOST_SHOP", raising=False)
    monkeypatch.setattr("kaloboost.api.time.sleep", lambda s: None)
    return mock_server


def err(status, code, field=None, reason=None, message="boom", details=None):
    if details is None:
        details = [{"field": field, "reason": reason}] if field else []
    return (status, {"error": {"code": code, "message": message, "details": details}, "request_id": "req_test"})


def page(data, cursor=None, has_more=None):
    return {
        "data": data,
        "page": {"next_cursor": cursor, "has_more": bool(cursor) if has_more is None else has_more},
        "request_id": "req_ok",
    }
