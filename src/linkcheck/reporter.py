"""Terminal and CSV reporting."""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .checker import CheckResult

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
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(_csv_row(result))


def print_report(results: list[CheckResult]) -> None:
    """Print a compact report and summary."""
    print()
    print(f"{'RESULT':<14} {'HTTP':>5} {'TIME':>8} {'REDIR':>5}  URL")
    print("-" * 100)

    for result in results:
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

    counts: dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1

    print("-" * 100)
    print(f"Total: {len(results)} URL(s)")
    for outcome, count in sorted(counts.items()):
        print(f"  {outcome}: {count}")
    if counts.get("RESTRICTED"):
        print("Note: RESTRICTED results do not affect the exit code.")
