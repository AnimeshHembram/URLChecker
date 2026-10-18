"""HTTP behaviour of check_url / check_urls, using mocked or loopback servers."""

import socket
import ssl
import time

import httpx
import pytest

from linkcheck import checker
from linkcheck.checker import (
    MAX_REDIRECTS,
    USER_AGENT,
    check_url,
    check_urls,
    classify_status,
    load_urls,
    parse_url_lines,
)


def respond(status, headers=None):
    return httpx.MockTransport(
        lambda request: httpx.Response(status, headers=headers, request=request)
    )


def raising(exc_factory):
    def handler(request):
        raise exc_factory(request)

    return httpx.MockTransport(handler)


# --- status classification -------------------------------------------------


@pytest.mark.parametrize(
    "status, outcome",
    [
        (200, "OK"),
        (204, "OK"),
        (401, "RESTRICTED"),
        (403, "RESTRICTED"),
        (429, "RESTRICTED"),
        (404, "BROKEN"),
        (410, "BROKEN"),
        (500, "SERVER_ERROR"),
        (503, "SERVER_ERROR"),
    ],
)
def test_status_outcomes(status, outcome):
    result = check_url("https://example.com/x", transport=respond(status))
    assert result.outcome == outcome
    assert result.status_code == status
    assert result.error == ""
    assert result.final_url == "https://example.com/x"
    assert result.redirect_count == 0


def test_redirect_without_location_is_error():
    result = check_url("https://example.com/x", transport=respond(302))
    assert result.outcome == "ERROR"
    assert result.status_code == 302
    assert result.error == "Redirect (HTTP 302) without a usable Location header"


@pytest.mark.parametrize("status", [199, 600])
def test_unexpected_status(status):
    assert classify_status(status) == ("ERROR", f"Unexpected HTTP status {status}")


def test_user_agent_is_sent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, request=request)

    check_url("https://example.com/", transport=httpx.MockTransport(handler))
    assert seen["ua"] == USER_AGENT


# --- redirects -------------------------------------------------------------


def test_two_hop_redirect():
    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(301, headers={"Location": "/b"}, request=request)
        if request.url.path == "/b":
            return httpx.Response(302, headers={"Location": "/c"}, request=request)
        return httpx.Response(200, request=request)

    result = check_url("https://example.com/a", transport=httpx.MockTransport(handler))
    assert result.outcome == "OK"
    assert result.redirect_count == 2
    assert result.final_url == "https://example.com/c"


def test_redirect_loop():
    transport = respond(302, headers={"Location": "/loop"})
    result = check_url("https://example.com/loop", transport=transport)
    assert result.outcome == "ERROR"
    assert result.error == "Too many redirects (limit is 10)"
    assert result.redirect_count == MAX_REDIRECTS
    assert result.final_url == "https://example.com/loop"
    assert result.status_code is None


def test_redirect_to_unsupported_scheme(local_server):
    result = check_url(local_server["url"] + "/to-ftp", timeout=5)
    assert result.outcome == "ERROR"
    assert result.error == "Redirected to an unsupported URL scheme"


# --- request failures ------------------------------------------------------


@pytest.mark.parametrize(
    "exc_type, phase",
    [
        (httpx.ConnectTimeout, "connecting"),
        (httpx.ReadTimeout, "waiting for response"),
        (httpx.WriteTimeout, "sending request"),
        (httpx.PoolTimeout, "waiting for connection"),
        (httpx.TimeoutException, "request"),
    ],
)
def test_timeouts(exc_type, phase):
    transport = raising(lambda request: exc_type("slow", request=request))
    result = check_url("https://example.com/", timeout=2.5, transport=transport)
    assert result.outcome == "ERROR"
    assert result.error == f"Timed out after 2.5s ({phase})"


def _connect_error(cause):
    def factory(request):
        try:
            raise cause
        except Exception as inner:
            raise httpx.ConnectError("failed", request=request) from inner

    return factory


@pytest.mark.parametrize(
    "cause, message",
    [
        (
            ssl.SSLCertVerificationError("bad cert"),
            "TLS certificate verification failed",
        ),
        (ssl.SSLError("handshake"), "TLS/SSL error"),
        (socket.gaierror(11001, "getaddrinfo failed"), "DNS lookup failed"),
        (ConnectionRefusedError(10061, "refused"), "Connection failed"),
    ],
)
def test_connect_error_causes(cause, message):
    transport = raising(_connect_error(cause))
    result = check_url("https://example.com/", transport=transport)
    assert result.outcome == "ERROR"
    assert result.error == message


def test_connect_error_without_cause():
    transport = raising(lambda request: httpx.ConnectError("x", request=request))
    assert (
        check_url("https://e.test/", transport=transport).error == "Connection failed"
    )


def test_other_request_error():
    transport = raising(lambda request: httpx.RemoteProtocolError("x", request=request))
    result = check_url("https://example.com/", transport=transport)
    assert result.error == "Request failed: RemoteProtocolError"


def test_value_error_during_request():
    transport = raising(lambda request: UnicodeError("bad label"))
    result = check_url("https://example.com/", transport=transport)
    assert result.outcome == "ERROR"
    assert result.error == "Request failed: UnicodeError: bad label"


def test_unexpected_exception_is_contained():
    transport = raising(lambda request: RuntimeError("boom"))
    result = check_url("https://example.com/", transport=transport)
    assert result.outcome == "ERROR"
    assert result.error == "Unexpected error: RuntimeError: boom"


def test_real_connection_refused(local_server):
    # Bind and close a socket to get a loopback port with nothing listening.
    # Windows retries a refused connection for about 2 seconds before giving
    # up, so the timeout must be comfortably longer than that.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    result = check_url(f"http://127.0.0.1:{port}/", timeout=10)
    assert result.outcome == "ERROR"
    assert result.error == "Connection failed"


# --- loopback timing and body behaviour -------------------------------------


def test_slow_headers_time_out(local_server):
    started = time.perf_counter()
    result = check_url(local_server["url"] + "/slow-headers", timeout=0.5)
    assert time.perf_counter() - started < 1.5
    assert result.outcome == "ERROR"
    assert result.error.startswith("Timed out after 0.5s")


def test_trickled_body_is_not_read(local_server):
    started = time.perf_counter()
    result = check_url(local_server["url"] + "/trickle", timeout=0.5)
    assert time.perf_counter() - started < 1.5
    assert result.outcome == "OK"


def test_large_body_is_not_downloaded(local_server):
    state = local_server["state"]
    result = check_url(local_server["url"] + "/big", timeout=5)
    assert result.outcome == "OK"
    assert state["big_done"].wait(10)
    assert state["big_sent"] < 50 * 1024 * 1024


def test_loopback_redirect(local_server):
    result = check_url(local_server["url"] + "/redirect", timeout=5)
    assert result.outcome == "OK"
    assert result.redirect_count == 1
    assert result.final_url.endswith("/ok")


# --- batches -------------------------------------------------------------


def test_order_preserved_and_parallel():
    def handler(request):
        if request.url.path == "/slow":
            time.sleep(0.3)
        return httpx.Response(200, request=request)

    urls = ["https://e.test/slow", "https://e.test/a", "https://e.test/b"]
    started = time.perf_counter()
    results = check_urls(urls, workers=3, transport=httpx.MockTransport(handler))
    assert time.perf_counter() - started < 0.6
    assert [r.url for r in results] == urls


def test_one_failing_url_does_not_abort_batch():
    def handler(request):
        if request.url.path == "/bad":
            raise RuntimeError("boom")
        return httpx.Response(200, request=request)

    urls = ["https://e.test/a", "https://e.test/bad", "https://e.test/c"]
    results = check_urls(urls, transport=httpx.MockTransport(handler))
    assert [r.outcome for r in results] == ["OK", "ERROR", "OK"]
    assert results[1].error == "Unexpected error: RuntimeError: boom"


def test_check_urls_defends_against_raising_check(monkeypatch):
    real = checker.check_url

    def flaky(url, timeout, transport):
        if "bad" in url:
            raise RuntimeError("escaped")
        return real(url, timeout, transport)

    monkeypatch.setattr(checker, "check_url", flaky)
    results = check_urls(
        ["https://e.test/a", " https://e.test/bad "], transport=respond(200)
    )
    assert [r.outcome for r in results] == ["OK", "ERROR"]
    assert results[1].url == "https://e.test/bad"
    assert results[1].error == "Unexpected error: RuntimeError: escaped"


def test_interrupt_propagates_from_batch(monkeypatch):
    def interrupted(url, timeout, transport):
        raise KeyboardInterrupt

    monkeypatch.setattr(checker, "check_url", interrupted)
    with pytest.raises(KeyboardInterrupt):
        check_urls(["https://e.test/a"], transport=respond(200))


def test_empty_batch():
    assert check_urls([]) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"workers": 0},
        {"workers": 51},
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"timeout": 601},
    ],
)
def test_check_urls_rejects_bad_settings(kwargs):
    with pytest.raises(ValueError):
        check_urls(["https://e.test/"], **kwargs)


# --- input files -----------------------------------------------------------


def test_load_urls_ac24(tmp_path):
    source = tmp_path / "urls.txt"
    source.write_bytes(
        b"\xef\xbb\xbf# header\n"
        b"\n"
        b"https://a.test/\n"
        b"   \n"
        b"   # indented comment\n"
        b"https://a.test/\n"
        b"ftp://x\n"
        b"https://b.test/ #note\n"
    )
    assert load_urls(str(source)) == [
        "https://a.test/",
        "https://a.test/",
        "ftp://x",
        "https://b.test/ #note",
    ]


def test_load_urls_strips_whitespace_and_crlf(tmp_path):
    source = tmp_path / "urls.txt"
    source.write_bytes(b"  https://a.test/  \r\n\t# tab comment\r\n")
    assert load_urls(str(source)) == ["https://a.test/"]


def test_parse_url_lines_bom_only_on_first_line():
    assert parse_url_lines(["\ufeffhttps://a.test/", "\ufeffhttps://b.test/"]) == [
        "https://a.test/",
        "\ufeffhttps://b.test/",
    ]


def test_duplicate_results_are_independent_copies():
    results = check_urls(
        ["https://a.test/", " https://a.test/ "], transport=respond(200)
    )
    assert [r.url for r in results] == ["https://a.test/", "https://a.test/"]
    assert results[0] == results[1]
    assert results[0] is not results[1]
