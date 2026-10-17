"""Command-line interface for LinkCheck."""

import argparse
import sys
from pathlib import Path

from .checker import check_urls, load_urls
from .reporter import print_report, write_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkcheck",
        description="Check URLs for HTTP errors, redirects, and connection problems.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check URLs from a text file")
    check.add_argument("file", help="Text file containing one URL per line")
    check.add_argument(
        "--output", "-o", help="Optional CSV output path"
    )
    check.add_argument(
        "--timeout", type=float, default=10.0,
        help="Per-request timeout in seconds (default: 10)",
    )
    check.add_argument(
        "--workers", type=int, default=10,
        help="Maximum concurrent requests (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    input_path = Path(args.file)
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        urls = load_urls(str(input_path))
    except (OSError, UnicodeError) as exc:
        print(f"Error reading input file: {exc}", file=sys.stderr)
        return 2

    if not urls:
        print("No URLs found in the input file.")
        return 0

    print(f"LinkCheck: checking {len(urls)} URL(s)...")
    try:
        results = check_urls(
            urls, timeout=args.timeout, workers=args.workers
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print_report(results)

    if args.output:
        try:
            write_csv(results, args.output)
            print(f"\nCSV report saved to: {args.output}")
        except OSError as exc:
            print(f"Error writing CSV report: {exc}", file=sys.stderr)
            return 2

    failures = {"BROKEN", "SERVER_ERROR", "ERROR", "INVALID"}
    return 1 if any(result.outcome in failures for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
