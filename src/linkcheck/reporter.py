"""Terminal, CSV and JSON reporting."""

from __future__ import annotations

import csv
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .checker import FAILURE_OUTCOMES, CheckResult

CSV_FIELDS = [
    "url",
    "final_url",
    "status_code",
    "outcome",
    "elapsed_ms",
    "redirect_count",
    "error",
]

# Characters that make spreadsheet programs treat a cell as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def visible(text: str) -> str:
    """Show invisible control, format and line-separator characters as escapes.

    A URL line can contain characters such as NUL or a zero-width space (that
    is why it was reported INVALID). Writing them raw would corrupt the
    terminal table or make spreadsheets cut the cell short.
    """
    out = []
    for ch in text:
        if ch != " " and unicodedata.category(ch) in {"Cc", "Cf", "Zl", "Zp", "Zs"}:
            code = ord(ch)
            out.append(f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}")
        else:
            out.append(ch)
    return "".join(out)


def display_url(url: str) -> str:
    """The form of a URL used in every report: credentials hidden, controls shown."""
    return visible(redact_url(url))


def redact_url(url: str) -> str:
    """Replace any ``user:password@`` part of a URL with ``***@``."""
    try:
        parts = urlsplit(url)
        if "@" not in parts.netloc:
            return url
        host = parts.netloc.rsplit("@", 1)[1]
        return urlunsplit(
            (parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment)
        )
    except Exception:
        return url


def csv_safe(value: object) -> object:
    """Prefix text that a spreadsheet would run as a formula with a quote."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_row(result: CheckResult) -> dict:
    row = result.to_dict()
    row["url"] = display_url(result.url)
    row["final_url"] = display_url(result.final_url)
    row["error"] = visible(result.error)
    return {key: csv_safe(value) for key, value in row.items()}


def write_csv(results: list[CheckResult], output: str) -> None:
    """Write results to a UTF-8 (with BOM) CSV file, overwriting it if present."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            writer.writerow(_csv_row(result))


def summarize(results: list[CheckResult]) -> dict[str, int]:
    """Count results per outcome, in a stable (alphabetical) order."""
    counts: dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    return dict(sorted(counts.items()))


def write_json(
    results: list[CheckResult], output: str, *, elapsed_s: float | None = None
) -> None:
    """Write results and a summary to a UTF-8 JSON file, overwriting it."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for result in results:
        row = result.to_dict()
        row["url"] = redact_url(result.url)
        row["final_url"] = redact_url(result.final_url)
        rows.append(row)
    document = {
        "tool": "linkcheck",
        "version": __version__,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "elapsed_seconds": None if elapsed_s is None else round(elapsed_s, 3),
        "summary": {
            "total": len(results),
            "problems": sum(r.outcome in FAILURE_OUTCOMES for r in results),
            "outcomes": summarize(results),
        },
        "results": rows,
    }
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(document, file, ensure_ascii=False, indent=2)
        file.write("\n")


def print_report(
    results: list[CheckResult],
    *,
    quiet: bool = False,
    elapsed_s: float | None = None,
) -> None:
    """Print a compact report and summary.

    With ``quiet`` the rows for OK results are left out (the summary still
    counts them).
    """
    print()
    print(f"{'RESULT':<14} {'HTTP':>5} {'TIME':>8} {'REDIR':>5}  URL")
    print("-" * 100)

    hidden = 0
    for result in results:
        if quiet and result.outcome == "OK":
            hidden += 1
            continue
        url = display_url(result.url)
        final_url = display_url(result.final_url)
        status = str(result.status_code) if result.status_code is not None else "-"
        elapsed = f"{result.elapsed_ms} ms"
        print(
            f"{result.outcome:<14} {status:>5} {elapsed:>8} "
            f"{result.redirect_count:>5}  {url}"
        )
        if result.error:
            print(f"    Detail: {visible(result.error)}")
        elif final_url and final_url != url:
            print(f"    Final URL: {final_url}")
    if hidden:
        print(f"({hidden} OK result(s) not shown because of --quiet)")

    counts = summarize(results)
    print("-" * 100)
    print(f"Total: {len(results)} URL(s)")
    for outcome, count in counts.items():
        print(f"  {outcome}: {count}")
    if counts.get("RESTRICTED"):
        print("Note: RESTRICTED results do not affect the exit code.")
    if elapsed_s is not None:
        print(f"Finished in {elapsed_s:.1f}s")
