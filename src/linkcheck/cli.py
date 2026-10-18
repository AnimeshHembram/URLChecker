"""Command-line interface for LinkCheck."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from time import perf_counter

import httpx

from . import __version__
from .checker import (
    FAILURE_OUTCOMES,
    RETRIES_MESSAGE,
    TIMEOUT_MESSAGE,
    WORKERS_MESSAGE,
    check_urls,
    load_urls,
    parse_url_lines,
    validate_retries,
    validate_timeout,
    validate_workers,
)
from .reporter import print_report, write_csv, write_json

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3
EXIT_INTERRUPTED = 130

STDIN = "-"


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


def _retries_arg(value: str) -> int:
    try:
        return validate_retries(int(value))
    except ValueError:
        raise argparse.ArgumentTypeError(RETRIES_MESSAGE) from None


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
            "Check every URL line in FILE (use - to read from standard input). "
            "Blank lines and lines starting with # are ignored."
        ),
    )
    check.add_argument(
        "file", help="Text file with one URL per line, or - for standard input"
    )
    check.add_argument(
        "--output",
        "-o",
        metavar="CSV",
        help="Write a CSV report to this path (overwritten)",
    )
    check.add_argument(
        "--json",
        metavar="PATH",
        help="Write a JSON report to this path (overwritten)",
    )
    check.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only list results that are not OK (the summary still counts all)",
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
    check.add_argument(
        "--retries",
        type=_retries_arg,
        default=0,
        metavar="N",
        help=(
            "Retry timeouts, connection errors and HTTP 429/502/503/504 up to "
            "N times with a short back-off, 0-5 (default: 0)"
        ),
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


class _Progress:
    """Show "Checked 3/40" on stderr while running, only in an interactive console."""

    def __init__(self, stream) -> None:
        self.stream = stream
        self.enabled = bool(getattr(stream, "isatty", lambda: False)())
        self.shown = False

    def __call__(self, done: int, total: int) -> None:
        if self.enabled and total > 1:
            self.stream.write(f"\rChecked {done}/{total}")
            self.stream.flush()
            self.shown = True

    def clear(self) -> None:
        if self.shown:
            self.stream.write("\r" + " " * 30 + "\r")
            self.stream.flush()


def _read_urls(source: str) -> list[str] | None:
    """Return the URL lines, or ``None`` after printing an input error."""
    if source == STDIN:
        try:
            return parse_url_lines(sys.stdin)
        except UnicodeError as exc:
            print(f"Error reading standard input: {exc}", file=sys.stderr)
            return None

    input_path = Path(source)
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return None
    try:
        return load_urls(str(input_path))
    except (OSError, UnicodeError) as exc:
        print(f"Error reading input file: {exc}", file=sys.stderr)
        return None


def _run(argv: list[str] | None, transport: httpx.BaseTransport | None) -> int:
    args = build_parser().parse_args(argv)

    urls = _read_urls(args.file)
    if urls is None:
        return EXIT_USAGE
    if not urls:
        print("No URLs found in the input.")
        return EXIT_OK

    unique = len(set(urls))
    extra = f" ({unique} unique)" if unique != len(urls) else ""
    print(f"LinkCheck: checking {len(urls)} URL(s){extra}...")
    progress = _Progress(sys.stderr)
    started = perf_counter()
    try:
        results = check_urls(
            urls,
            timeout=args.timeout,
            workers=args.workers,
            transport=transport,
            retries=args.retries,
            on_progress=progress,
        )
    finally:
        progress.clear()
    elapsed_s = perf_counter() - started
    print_report(results, quiet=args.quiet, elapsed_s=elapsed_s)

    writers = [
        ("CSV", args.output, lambda path: write_csv(results, path)),
        (
            "JSON",
            args.json,
            lambda path: write_json(results, path, elapsed_s=elapsed_s),
        ),
    ]
    for label, path, write in writers:
        if not path:
            continue
        try:
            write(path)
        except OSError as exc:
            print(f"Error writing {label} report: {exc}", file=sys.stderr)
            return EXIT_USAGE
        print(f"{label} report saved to: {path}")

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
