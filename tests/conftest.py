"""Shared test fixtures: block external network access during tests."""

import http.server
import ipaddress
import socket
import threading
import time

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _is_loopback(address) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host == "localhost"
    return True  # Unix sockets and other non-IP families are local


def _guarded_connect(self, address):
    if not _is_loopback(address):
        raise OSError(f"external network disabled in tests: {address!r}")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if not _is_loopback(address):
        raise OSError(f"external network disabled in tests: {address!r}")
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Fail any attempt to connect to a non-loopback address."""
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - name required by BaseHTTPRequestHandler
        state = self.server.state
        if self.path == "/ok":
            return self._send(200, b"ok")
        if self.path == "/redirect":
            return self._send(302, headers=[("Location", "/ok")])
        if self.path == "/to-ftp":
            return self._send(302, headers=[("Location", "ftp://example.test/x")])
        if self.path == "/slow-headers":
            time.sleep(2)
            return self._send(200, b"late")
        if self.path == "/trickle":
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            try:
                for _ in range(10):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.5)
            except OSError:
                pass
            return None
        if self.path == "/big":
            total = 50 * 1024 * 1024
            chunk = b"0" * 65536
            self.send_response(200)
            self.send_header("Content-Length", str(total))
            self.end_headers()
            sent = 0
            try:
                while sent < total:
                    self.wfile.write(chunk)
                    sent += len(chunk)
            except OSError:
                pass
            state["big_sent"] = sent
            state["big_done"].set()
            return None
        return self._send(404)


@pytest.fixture(scope="session")
def local_server():
    """A threaded HTTP server on 127.0.0.1 for real-socket behaviour tests."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.state = {"big_sent": None, "big_done": threading.Event()}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield {"url": f"http://{host}:{port}", "state": server.state}
    server.shutdown()
    server.server_close()
