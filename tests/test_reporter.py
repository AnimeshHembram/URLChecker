import csv

from linkcheck.checker import CheckResult
from linkcheck.reporter import write_csv


def test_csv_report(tmp_path):
    output = tmp_path / "reports" / "results.csv"
    results = [
        CheckResult(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            outcome="OK",
            elapsed_ms=42,
            redirect_count=0,
        )
    ]

    write_csv(results, str(output))

    with output.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["outcome"] == "OK"
    assert rows[0]["status_code"] == "200"
