"""URL validation rules V1-V6: INVALID results are produced without any request."""

import pytest

from linkcheck.checker import check_url, validate_url

SPACE = "Invalid URL: contains spaces or control characters"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://exa mple.com/", SPACE),
        ("https://b.test/ #note", SPACE),
        ("http://exa\x00mple.com/", SPACE),
        ("http://example.com/\x7f", SPACE),
        ("https://example.com/page​", SPACE),
        ("https://example.com/ x", SPACE),
        ("http://[::1", "Invalid URL: malformed (Invalid IPv6 URL)"),
        ("//example.com/path", "Invalid URL: missing scheme"),
        ("example.com", "Invalid URL: missing scheme"),
        (
            "ftp://x",
            "Invalid URL: unsupported scheme 'ftp' (only http and https are checked)",
        ),
        (
            "mailto:a@b.test",
            "Invalid URL: unsupported scheme 'mailto' "
            "(only http and https are checked)",
        ),
        ("http://", "Invalid URL: missing host"),
        ("https:///path", "Invalid URL: missing host"),
        ("http://example.com:99999/", "Invalid URL: invalid port"),
        ("http://example.com:0/", "Invalid URL: invalid port"),
        ("http://example.com:abc/", "Invalid URL: invalid port"),
    ],
)
def test_invalid_urls_exact_message(url, expected):
    result = check_url(url)
    assert result.outcome == "INVALID"
    assert result.error == expected
    assert (result.final_url, result.status_code, result.redirect_count) == (
        "",
        None,
        0,
    )
    assert result.elapsed_ms == 0


@pytest.mark.parametrize(
    "url, detail",
    [
        ("http://ü" + "a" * 70 + ".com/", "Invalid IDNA hostname"),
        ("http://a..b/", "label empty or too long"),
        ("http://" + "a" * 64 + ".com/", "label empty or too long"),
        ("http://" + "a." * 130 + "com/", "host name too long"),
        ("http://xn--a.com/", "invalid punycode label"),
    ],
)
def test_invalid_host_v6(url, detail):
    result = check_url(url)
    assert result.outcome == "INVALID"
    assert result.error.startswith("Invalid URL: invalid host or characters (")
    assert detail in result.error


@pytest.mark.parametrize(
    "url",
    [
        "HTTP://example.com/",
        "https://example.com/page#fragment",
        "https://b.test/#note",
        "https://user:secret@example.com/",
        "http://127.0.0.1:8080/x",
        "http://[::1]:8080/",
        "https://bücher.example/",
        "https://example.com./",
    ],
)
def test_valid_urls_pass_validation(url):
    assert validate_url(url) is None


def test_validation_failure_is_contained(monkeypatch):
    def broken(url):
        raise RuntimeError("bug")

    monkeypatch.setattr("linkcheck.checker.validate_url", broken)
    result = check_url("https://example.com/")
    assert result.outcome == "INVALID"
    assert result.error == "Invalid URL: malformed (RuntimeError)"
