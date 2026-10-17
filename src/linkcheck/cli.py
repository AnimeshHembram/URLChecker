"""Command-line interface for LinkCheck."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import httpx

from . import __version__
from .checker import (
    FAILURE_OUTCOMES,
    TIMEOUT_MESSAGE,
    WORKERS_MESSAGE,
    check_urls,
    load_urls,
    validate_timeout,
    validate_workers,
)
from .reporter import print_report, write_csv

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3
EXIT_INTERRUPTED = 130


def _timeout_arg(value: str) -> float:
    try:
        return validate_timeout(float(value))
    except ValueError:
        raise argparse.ArgumentTypeError(TIMEOUT_MESSAGE) from None


def _workers_arg(value: str) -> int:
    try:
        return validate_workers(int(value))
    except ValueError:
        raise argparse.ArgumentTypeError(WORKERS_MESSAGE) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkcheck",
        description="Check URLs for HTTP errors, redirects, and connection problems.",
        epilog=(
            "Exit codes: 0 = all OK or RESTRICTED, 1 = problems found, "
            "2 = usage/input/output error, 3 = internal error, 130 = interrupted."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"linkcheck {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="Check URLs from a text file",
        description=(
            "Check every URL line in FILE. Blank lines and lines starting "
            "with # are ignored."
        ),
    )
    check.add_argument("file", help="Text file containing one URL per line")
    check.add_argument(
        "--output", "-o", help="Write a CSV report to this path (overwritten)"
    )
    check.add_argument(
        "--timeout",
        type=_timeout_arg,
        default=10.0,
        metavar="SECONDS",
        help=(
            "Maximum wait for each network step (connecting, sending, waiting "
            "for the response), 0 < SECONDS <= 600 (default: 10)"
        ),
    )
    check.add_argument(
        "--workers",
        type=_workers_arg,
        default=10,
        metavar="N",
        help="Number of URLs checked at the same time, 1-50 (default: 10)",
    )
    return parser


def _make_console_safe() -> None:
    """Never crash because the console cannot display a character."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except Exception:  # pragma: no cover - exotic stream objects
                pass


def _run(argv: list[str] | None, transport: httpx.BaseTransport | None) -> int:
    args = build_parser().parse_args(argv)

    input_path = Path(args.file)
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return EXIT_USAGE

    try:
        urls = load_urls(str(input_path))
    except (OSError, UnicodeError) as exc:
        print(f"Error reading input file: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if not urls:
        print("No URLs found in the input file.")
        return EXIT_OK

    print(f"LinkCheck: checking {len(urls)} URL(s)...")
    results = check_urls(
        urls, timeout=args.timeout, workers=args.workers, transport=transport
    )
    print_report(results)

    if args.output:
        try:
            write_csv(results, args.output)
        except OSError as exc:
            print(f"Error writing CSV report: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"\nCSV report saved to: {args.output}")

    if any(result.outcome in FAILURE_OUTCOMES for result in results):
        return EXIT_PROBLEMS
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Run the CLI and return its exit code.

    ``transport`` is for tests only: it replaces the network layer.
    """
    _make_console_safe()
    try:
        return _run(argv, transport)
    except KeyboardInterrupt:
        print("Interrupted. No report was written.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:
        print(
            f"linkcheck: internal error: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        print(
            "This is a bug. Set LINKCHECK_DEBUG=1 to see the full traceback.",
            file=sys.stderr,
        )
        if os.environ.get("LINKCHECK_DEBUG") == "1":
            traceback.print_exc()
        return EXIT_INTERNAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
