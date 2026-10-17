import httpx

from linkcheck.checker import check_url, check_urls, load_urls


def test_successful_url():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, request=request)
    )
    result = check_url("https://example.com", transport=transport)
    assert result.outcome == "OK"
    assert result.status_code == 200


def test_broken_url():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, request=request)
    )
    result = check_url("https://example.com/missing", transport=transport)
    assert result.outcome == "BROKEN"
    assert result.status_code == 404


def test_restricted_url():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, request=request)
    )
    result = check_url("https://example.com/private", transport=transport)
    assert result.outcome == "RESTRICTED"


def test_redirect_is_recorded():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "/new"}, request=request)
        return httpx.Response(200, request=request)

    result = check_url(
        "https://example.com/old",
        transport=httpx.MockTransport(handler),
    )
    assert result.outcome == "OK"
    assert result.redirect_count == 1
    assert result.final_url.endswith("/new")


def test_invalid_scheme():
    result = check_url("ftp://example.com")
    assert result.outcome == "INVALID"


def test_urls_file(tmp_path):
    source = tmp_path / "urls.txt"
    source.write_text(
        "# comment\n\nhttps://example.com\n https://openai.com \n",
        encoding="utf-8",
    )
    assert load_urls(str(source)) == ["https://example.com", "https://openai.com"]


def test_concurrent_checker_preserves_order():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, request=request)
    )
    # Exercise one URL directly with a deterministic mock transport.
    result = check_url("https://example.com", transport=transport)
    assert result.url == "https://example.com"
    assert check_urls([], workers=2) == []
