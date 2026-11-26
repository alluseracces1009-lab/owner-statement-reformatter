"""Tests for the anonymous usage counter: python -m pytest -q test_usage.py"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import usage


class _Recorder(BaseHTTPRequestHandler):
    hits = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Recorder.hits.append({"path": self.path, "body": json.loads(body),
                               "apikey": self.headers.get("apikey"), "prefer": self.headers.get("Prefer")})
        self.send_response(201); self.end_headers()

    def log_message(self, *a):  # keep test output quiet
        pass


def test_posts_only_the_event_name():
    srv = HTTPServer(("127.0.0.1", 0), _Recorder); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status = usage.track("generate_ok", sync=True, config=(f"http://127.0.0.1:{srv.server_port}", "test-key"))
        assert status == 201
        hit = _Recorder.hits[-1]
        assert hit["path"] == "/rest/v1/usage_events"
        assert hit["body"] == {"event": "generate_ok"}          # nothing else is sent
        assert hit["apikey"] == "test-key" and hit["prefer"] == "return=minimal"
    finally:
        srv.shutdown()


def test_unknown_event_is_ignored():
    assert usage.track("anything_else", sync=True, config=("http://127.0.0.1:9", "k")) is None


def test_no_config_is_a_no_op():
    assert usage.track("visit", sync=True) is None   # no Streamlit secrets in tests


def test_unreachable_server_never_raises():
    assert usage.track("visit", sync=True, config=("http://127.0.0.1:9", "k")) is None
