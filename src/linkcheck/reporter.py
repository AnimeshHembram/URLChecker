"""Terminal and CSV reporting."""

import csv
from pathlib import Path

from .checker import CheckResult


def write_csv(results: list[CheckResult], output: str) -> None:
    """Write results to a CSV file."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "url", "final_url", "status_code", "outcome",
        "elapsed_ms", "redirect_count", "error",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_dict())


def print_report(results: list[CheckResult]) -> None:
    """Print a compact report and summary."""
    print()
    print(f"{'RESULT':<14} {'HTTP':>5} {'TIME':>8} {'REDIR':>5}  URL")
    print("-" * 100)

    for result in results:
        status = str(result.status_code) if result.status_code is not None else "-"
        elapsed = f"{result.elapsed_ms} ms"
        print(
            f"{result.outcome:<14} {status:>5} {elapsed:>8} "
            f"{result.redirect_count:>5}  {result.url}"
        )
        if result.error:
            print(f"    Detail: {result.error}")
        elif result.final_url and result.final_url != result.url:
            print(f"    Final URL: {result.final_url}")

    counts: dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1

    print("-" * 100)
    print(f"Total: {len(results)} URL(s)")
    for outcome, count in sorted(counts.items()):
        print(f"  {outcome}: {count}")
