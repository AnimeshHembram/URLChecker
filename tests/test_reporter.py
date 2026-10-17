"""CSV and terminal reporting."""

import csv

import pytest

from linkcheck.checker import CheckResult
from linkcheck.reporter import CSV_FIELDS, csv_safe, print_report, redact_url, write_csv


def result(url="https://example.com", outcome="OK", **kwargs):
    defaults = {
        "final_url": url,
        "status_code": 200,
        "elapsed_ms": 42,
        "redirect_count": 0,
        "error": "",
    }
    defaults.update(kwargs)
    return CheckResult(url=url, outcome=outcome, **defaults)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_csv_header_bom_order_and_empty_status(tmp_path):
    output = tmp_path / "new" / "nested" / "results.csv"
    rows = [
        result("https://a.test/"),
        result("ftp://x", "INVALID", final_url="", status_code=None, error="bad"),
    ]
    write_csv(rows, str(output))
    raw = output.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw[3:].split(b"\r\n")[0].decode() == ",".join(CSV_FIELDS)
    data = read_csv(output)
    assert [r["url"] for r in data] == ["https://a.test/", "ftp://x"]
    assert data[0]["status_code"] == "200"
    assert data[1]["status_code"] == ""


def test_csv_overwrites_existing_file(tmp_path):
    output = tmp_path / "out.csv"
    output.write_text("old content\n" * 10, encoding="utf-8")
    write_csv([result()], str(output))
    assert len(read_csv(output)) == 1


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_formula_neutralised(prefix):
    assert csv_safe(prefix + "SUM(A1)") == "'" + prefix + "SUM(A1)"


def test_csv_safe_leaves_other_values():
    assert csv_safe("https://a.test/") == "https://a.test/"
    assert csv_safe(200) == 200
    assert csv_safe(None) is None


def test_csv_formula_row(tmp_path):
    output = tmp_path / "out.csv"
    text = '=HYPERLINK("http://x")'
    write_csv([result(text, "INVALID", final_url="", status_code=None)], str(output))
    assert read_csv(output)[0]["url"] == "'" + text


def test_redaction_in_csv(tmp_path):
    output = tmp_path / "out.csv"
    url = "https://user:secret@host.test/x"
    write_csv([result(url, final_url=url)], str(output))
    raw = output.read_text(encoding="utf-8-sig")
    assert "secret" not in raw and "user:" not in raw
    assert read_csv(output)[0]["url"] == "https://***@host.test/x"
    assert read_csv(output)[0]["final_url"] == "https://***@host.test/x"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://user:pw@host.test/p?q=1#f", "https://***@host.test/p?q=1#f"),
        ("https://user@host.test:8080/", "https://***@host.test:8080/"),
        ("https://host.test/a@b", "https://host.test/a@b"),
        ("", ""),
        ("http://[::1", "http://[::1"),
    ],
)
def test_redact_url(url, expected):
    assert redact_url(url) == expected


def test_print_report(capsys):
    rows = [
        result("https://a.test/", final_url="https://a.test/final", redirect_count=1),
        result("https://user:pw@b.test/", "RESTRICTED", status_code=403),
        result(
            "ftp://x", "INVALID", final_url="", status_code=None, error="bad scheme"
        ),
    ]
    print_report(rows)
    out = capsys.readouterr().out
    assert "Final URL: https://a.test/final" in out
    assert "Detail: bad scheme" in out
    assert "https://***@b.test/" in out and "pw" not in out
    assert "Total: 3 URL(s)" in out
    assert "  RESTRICTED: 1" in out
    assert "Note: RESTRICTED results do not affect the exit code." in out


def test_print_report_without_restricted(capsys):
    print_report([result()])
    assert "Note: RESTRICTED" not in capsys.readouterr().out
