"""Command-line behaviour and exit codes."""

import io
import json
import subprocess
import sys

import httpx
import pytest

from linkcheck import __version__, cli


def transport_for(statuses):
    """Answer each URL path with the given status (default 200)."""

    def handler(request):
        return httpx.Response(statuses.get(request.url.path, 200), request=request)

    return httpx.MockTransport(handler)


@pytest.fixture
def url_file(tmp_path):
    def make(*lines, raw=None):
        path = tmp_path / "urls.txt"
        if raw is not None:
            path.write_bytes(raw)
        else:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    return make


def run(argv, statuses=None, **kwargs):
    return cli.main(argv, transport=transport_for(statuses or {}), **kwargs)


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"linkcheck {__version__}"


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "check" in out and "Exit codes" in out


def test_no_arguments():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "601", "abc"])
def test_bad_timeout(url_file, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", url_file("https://a.test/"), "--timeout", value])
    assert exc.value.code == 2
    assert "--timeout must be a finite number" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "51", "x", "2.5"])
def test_bad_workers(url_file, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", url_file("https://a.test/"), "--workers", value])
    assert exc.value.code == 2
    assert "--workers must be a whole number from 1 to 50" in capsys.readouterr().err


@pytest.mark.parametrize(
    "option, value",
    [
        ("--timeout", "600"),
        ("--timeout", "0.5"),
        ("--workers", "1"),
        ("--workers", "50"),
    ],
)
def test_boundary_values_accepted(url_file, option, value):
    assert run(["check", url_file("https://a.test/"), option, value]) == 0


def test_all_ok_exit_0(url_file, capsys):
    assert run(["check", url_file("https://a.test/x", "https://a.test/y")]) == 0
    assert "Total: 2 URL(s)" in capsys.readouterr().out


def test_restricted_only_exit_0(url_file, capsys):
    code = run(["check", url_file("https://a.test/", "https://a.test/r")], {"/r": 403})
    assert code == 0
    assert "RESTRICTED results do not affect the exit code" in capsys.readouterr().out


@pytest.mark.parametrize("status", [404, 500])
def test_problem_status_exit_1(url_file, status):
    assert run(["check", url_file("https://a.test/bad")], {"/bad": status}) == 1


def test_invalid_exit_1(url_file):
    assert run(["check", url_file("https://a.test/", "ftp://x")]) == 1


def test_missing_file(tmp_path, capsys):
    assert run(["check", str(tmp_path / "nope.txt")]) == 2
    assert "input file not found" in capsys.readouterr().err


def test_directory_as_input(tmp_path):
    assert run(["check", str(tmp_path)]) == 2


def test_invalid_utf8(url_file, capsys):
    assert run(["check", url_file(raw=b"\xff\xfehttps://a.test/\n")]) == 2
    assert "Error reading input file" in capsys.readouterr().err


def test_empty_file(url_file, capsys):
    assert run(["check", url_file("# only a comment", "")]) == 0
    assert "No URLs found in the input." in capsys.readouterr().out


def test_csv_to_nested_folder(url_file, tmp_path, capsys):
    output = tmp_path / "a" / "b" / "report.csv"
    assert run(["check", url_file("https://a.test/"), "-o", str(output)]) == 0
    assert output.is_file()
    assert f"CSV report saved to: {output}" in capsys.readouterr().out


def test_csv_to_directory(url_file, tmp_path, capsys):
    target = tmp_path / "dir"
    target.mkdir()
    assert run(["check", url_file("https://a.test/"), "--output", str(target)]) == 2
    captured = capsys.readouterr()
    assert "Total: 1 URL(s)" in captured.out  # report printed first
    assert "Error writing CSV report" in captured.err


def test_malformed_lines_never_crash(url_file, tmp_path, capsys):
    output = tmp_path / "bad.csv"
    path = url_file(
        "ftp://x",
        "http://exa\x00mple.com/",
        "http://ü" + "a" * 70 + ".com/",
        "http://example.com:99999/",
        "http://example.com/page​",
    )
    assert run(["check", path, "-o", str(output)]) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    rows = output.read_text(encoding="utf-8-sig").splitlines()[1:]
    assert len(rows) == 5
    assert all(",INVALID," in row for row in rows)


def test_ac24_rows(url_file, tmp_path, capsys):
    raw = (
        b"\xef\xbb\xbf# header\n\nhttps://a.test/\n   \n   # indented comment\n"
        b"https://a.test/\nftp://x\nhttps://b.test/ #note\n"
    )
    output = tmp_path / "ac24.csv"
    assert run(["check", url_file(raw=raw), "-o", str(output)]) == 1
    assert "Total: 4 URL(s)" in capsys.readouterr().out
    lines = output.read_text(encoding="utf-8-sig").splitlines()[1:]
    assert [line.split(",")[0] for line in lines] == [
        "https://a.test/",
        "https://a.test/",
        "ftp://x",
        "https://b.test/ #note",
    ]
    assert [line.split(",")[3] for line in lines] == ["OK", "OK", "INVALID", "INVALID"]
    assert "unsupported scheme 'ftp'" in lines[2]
    assert "contains spaces or control characters" in lines[3]


def test_internal_error(url_file, monkeypatch, capsys):
    def broken(results, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "print_report", broken)
    monkeypatch.delenv("LINKCHECK_DEBUG", raising=False)
    assert run(["check", url_file("https://a.test/")]) == 3
    err = capsys.readouterr().err
    assert "linkcheck: internal error: RuntimeError: kaboom" in err
    assert "LINKCHECK_DEBUG=1" in err
    assert "Traceback" not in err


def test_internal_error_debug_traceback(url_file, monkeypatch, capsys):
    def broken(results, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "print_report", broken)
    monkeypatch.setenv("LINKCHECK_DEBUG", "1")
    assert run(["check", url_file("https://a.test/")]) == 3
    assert "Traceback" in capsys.readouterr().err


def test_interrupt(url_file, tmp_path, monkeypatch, capsys):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "check_urls", interrupted)
    output = tmp_path / "never.csv"
    assert run(["check", url_file("https://a.test/"), "-o", str(output)]) == 130
    assert "Interrupted. No report was written." in capsys.readouterr().err
    assert not output.exists()


def test_console_cannot_encode_unicode(url_file, monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stream)
    assert run(["check", url_file("https://bücher.test/")]) == 0
    stream.flush()
    assert b"b?cher" in stream.buffer.getvalue()


def test_python_dash_m_version():
    completed = subprocess.run(
        [sys.executable, "-m", "linkcheck", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == f"linkcheck {__version__}"


# --- round 2: stdin, JSON, quiet, duplicates -------------------------------


def test_read_from_stdin(monkeypatch, capsys):
    stdin = io.StringIO("\ufeff# list\nhttps://a.test/x\n\nhttps://a.test/bad\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert run(["check", "-"], {"/bad": 404}) == 1
    out = capsys.readouterr().out
    assert "checking 2 URL(s)..." in out
    assert "BROKEN" in out


def test_stdin_decode_error(monkeypatch, capsys):
    stdin = io.TextIOWrapper(io.BytesIO(b"\xff\xfe\x00bad"), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert run(["check", "-"]) == 2
    assert "Error reading standard input" in capsys.readouterr().err


def test_empty_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert run(["check", "-"]) == 0
    assert "No URLs found in the input." in capsys.readouterr().out


def test_json_report(url_file, tmp_path, capsys):
    output = tmp_path / "out" / "report.json"
    path = url_file("https://u:pw@a.test/ok", "https://a.test/gone", "ftp://x")
    assert run(["check", path, "--json", str(output)], {"/gone": 404}) == 1
    assert f"JSON report saved to: {output}" in capsys.readouterr().out
    raw = output.read_text(encoding="utf-8")
    assert not raw.startswith("\ufeff")
    data = json.loads(raw)
    assert data["tool"] == "linkcheck"
    assert data["version"] == __version__
    assert data["generated_at"].endswith("+00:00")
    assert isinstance(data["elapsed_seconds"], float)
    assert data["summary"] == {
        "total": 3,
        "problems": 2,
        "outcomes": {"BROKEN": 1, "INVALID": 1, "OK": 1},
    }
    assert [r["outcome"] for r in data["results"]] == ["OK", "BROKEN", "INVALID"]
    assert data["results"][0]["url"] == "https://***@a.test/ok"
    assert "pw" not in raw
    assert data["results"][2]["status_code"] is None


def test_csv_and_json_together(url_file, tmp_path):
    csv_path, json_path = tmp_path / "r.csv", tmp_path / "r.json"
    path = url_file("https://a.test/")
    assert run(["check", path, "-o", str(csv_path), "--json", str(json_path)]) == 0
    assert csv_path.is_file() and json_path.is_file()


def test_json_to_directory(url_file, tmp_path, capsys):
    target = tmp_path / "dir"
    target.mkdir()
    assert run(["check", url_file("https://a.test/"), "--json", str(target)]) == 2
    assert "Error writing JSON report" in capsys.readouterr().err


def test_quiet_hides_ok_rows(url_file, capsys):
    path = url_file("https://a.test/fine", "https://a.test/gone")
    assert run(["check", path, "--quiet"], {"/gone": 404}) == 1
    out = capsys.readouterr().out
    assert "https://a.test/fine" not in out
    assert "https://a.test/gone" in out
    assert "(1 OK result(s) not shown because of --quiet)" in out
    assert "  OK: 1" in out


def test_duplicates_checked_once(url_file, capsys):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, request=request)

    path = url_file("https://a.test/x", "https://a.test/y", "https://a.test/x")
    code = cli.main(["check", path], transport=httpx.MockTransport(handler))
    assert code == 0
    assert sorted(calls) == ["https://a.test/x", "https://a.test/y"]
    out = capsys.readouterr().out
    assert "checking 3 URL(s) (2 unique)..." in out
    assert "Total: 3 URL(s)" in out


def test_finished_line(url_file, capsys):
    assert run(["check", url_file("https://a.test/")]) == 0
    assert "Finished in " in capsys.readouterr().out


# --- round 3: retries and progress -----------------------------------------


@pytest.mark.parametrize("value", ["-1", "6", "x"])
def test_bad_retries(url_file, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", url_file("https://a.test/"), "--retries", value])
    assert exc.value.code == 2
    assert "--retries must be a whole number from 0 to 5" in capsys.readouterr().err


def test_retries_option(url_file, monkeypatch):
    from linkcheck import checker

    monkeypatch.setattr(checker, "_sleep", lambda seconds: None)
    seen = []

    def handler(request):
        seen.append(1)
        status = 503 if len(seen) == 1 else 200
        return httpx.Response(status, request=request)

    path = url_file("https://a.test/")
    code = cli.main(
        ["check", path, "--retries", "2"], transport=httpx.MockTransport(handler)
    )
    assert code == 0
    assert len(seen) == 2


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def test_progress_shown_on_tty(url_file, monkeypatch):
    stream = FakeTTY()
    monkeypatch.setattr(sys, "stderr", stream)
    assert run(["check", url_file("https://a.test/1", "https://a.test/2")]) == 0
    text = stream.getvalue()
    assert "\rChecked 2/2" in text
    assert text.endswith("\r")


def test_no_progress_for_single_url_or_pipe(url_file, monkeypatch, capsys):
    stream = FakeTTY()
    monkeypatch.setattr(sys, "stderr", stream)
    assert run(["check", url_file("https://a.test/1")]) == 0
    assert stream.getvalue() == ""


def test_attempts_in_json_not_csv(url_file, tmp_path):
    csv_path, json_path = tmp_path / "r.csv", tmp_path / "r.json"
    path = url_file("https://a.test/")
    assert run(["check", path, "-o", str(csv_path), "--json", str(json_path)]) == 0
    header = csv_path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "attempts" not in header
    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["results"][0]["attempts"] == 1
    )


def test_stdin_is_read_as_utf8(monkeypatch, capsys):
    # Simulate a Windows pipe: UTF-8 bytes behind a cp1252 text wrapper.
    raw = io.BytesIO("\ufeffhttps://b\u00fccher.test/\n".encode())
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(raw, encoding="cp1252"))
    assert run(["check", "-"]) == 0
    out = capsys.readouterr().out
    assert "https://b\u00fccher.test/" in out
    assert "\u00c3" not in out


class FakeTTYIn(io.StringIO):
    def isatty(self):
        return True


def test_stdin_tty_hint(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", FakeTTYIn("https://a.test/\n"))
    assert run(["check", "-"]) == 0
    assert "Reading URLs from standard input" in capsys.readouterr().err
