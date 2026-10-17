"""Shared test fixtures: block external network access during tests."""

import ipaddress
import socket

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
