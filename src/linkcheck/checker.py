"""HTTP URL checking engine."""

from __future__ import annotations

import ipaddress
import math
import socket
import ssl
import time
import unicodedata
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, replace
from time import perf_counter
from urllib.parse import urlsplit

import httpx

from . import __version__

MAX_REDIRECTS = 10
MAX_TIMEOUT = 600.0
MAX_WORKERS = 50
USER_AGENT = f"LinkCheck/{__version__} (+URL health checker)"

OUTCOMES = ("OK", "RESTRICTED", "BROKEN", "SERVER_ERROR", "ERROR", "INVALID")
FAILURE_OUTCOMES = frozenset({"BROKEN", "SERVER_ERROR", "ERROR", "INVALID"})
RESTRICTED_STATUSES = frozenset({401, 403, 429})

TIMEOUT_MESSAGE = (
    "--timeout must be a finite number of seconds greater than 0 and at most 600"
)
WORKERS_MESSAGE = "--workers must be a whole number from 1 to 50"
MAX_RETRIES = 5
RETRIES_MESSAGE = "--retries must be a whole number from 0 to 5"
# Final statuses that usually mean "try again later".
RETRY_STATUSES = frozenset({429, 502, 503, 504})

# Unicode categories rejected anywhere in a URL: control, format (e.g. zero-width
# space) and separator characters.
_REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})
_MAX_ERROR_DETAIL = 200


@dataclass
class CheckResult:
    """The outcome of checking one URL line."""

    url: str
    final_url: str
    status_code: int | None
    outcome: str
    elapsed_ms: int
    redirect_count: int
    error: str = ""
    attempts: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


def validate_timeout(timeout: float) -> float:
    """Return ``timeout`` if it is finite and within (0, 600], else raise."""
    if not (math.isfinite(timeout) and 0 < timeout <= MAX_TIMEOUT):
        raise ValueError(TIMEOUT_MESSAGE)
    return timeout


def validate_workers(workers: int) -> int:
    """Return ``workers`` if it is within [1, 50], else raise."""
    if not (1 <= workers <= MAX_WORKERS):
        raise ValueError(WORKERS_MESSAGE)
    return workers


def validate_retries(retries: int) -> int:
    """Return ``retries`` if it is within [0, 5], else raise."""
    if not (0 <= retries <= MAX_RETRIES):
        raise ValueError(RETRIES_MESSAGE)
    return retries


def _short(exc: BaseException) -> str:
    return str(exc)[:_MAX_ERROR_DETAIL]


def _invalid_ascii_hostname(host: str) -> str | None:
    """Check DNS label rules for plain ASCII host names (not IP addresses)."""
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    name = host[:-1] if host.endswith(".") else host
    if len(name) > 253:
        return "host name too long"
    if any(not 1 <= len(label) <= 63 for label in name.split(".")):
        return "label empty or too long"
    if "xn--" in name.lower():
        try:
            name.encode("ascii").decode("idna")
        except UnicodeError:
            return "invalid punycode label"
    return None


def validate_url(url: str) -> str | None:
    """Return an ``Invalid URL: ...`` message, or ``None`` if the URL is checkable.

    Rules are applied in order (V1-V6 in the specification); the first failure
    wins. No network request is made.
    """
    # V1: whitespace, control, format and separator characters.
    if any(
        ch.isspace() or unicodedata.category(ch) in _REJECTED_CATEGORIES for ch in url
    ):
        return "Invalid URL: contains spaces or control characters"

    # V2: structurally malformed.
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        return f"Invalid URL: malformed ({_short(exc)})"

    # V3: scheme.
    if not parts.scheme:
        return "Invalid URL: missing scheme"
    if parts.scheme.lower() not in {"http", "https"}:
        return (
            f"Invalid URL: unsupported scheme '{parts.scheme}' "
            "(only http and https are checked)"
        )

    # V4: host.
    host = parts.hostname
    if not host:
        return "Invalid URL: missing host"

    # V5: port.
    try:
        port = parts.port
    except ValueError:
        return "Invalid URL: invalid port"
    if port == 0:
        return "Invalid URL: invalid port"

    # V6: host and characters as httpx understands them.
    try:
        httpx.URL(url)
    except (httpx.InvalidURL, ValueError) as exc:
        return f"Invalid URL: invalid host or characters ({_short(exc)})"
    if host.isascii():
        problem = _invalid_ascii_hostname(host)
        if problem:
            return f"Invalid URL: invalid host or characters ({problem})"
    return None


def classify_status(status: int) -> tuple[str, str]:
    """Map the final HTTP status code to ``(outcome, error)``."""
    if 200 <= status < 300:
        return "OK", ""
    if status in RESTRICTED_STATUSES:
        return "RESTRICTED", ""
    if 400 <= status < 500:
        return "BROKEN", ""
    if 500 <= status < 600:
        return "SERVER_ERROR", ""
    if 300 <= status < 400:
        return "ERROR", f"Redirect (HTTP {status}) without a usable Location header"
    return "ERROR", f"Unexpected HTTP status {status}"


def _timeout_phase(exc: httpx.TimeoutException) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "connecting"
    if isinstance(exc, httpx.ReadTimeout):
        return "waiting for response"
    if isinstance(exc, httpx.WriteTimeout):
        return "sending request"
    if isinstance(exc, httpx.PoolTimeout):
        return "waiting for connection"
    return "request"


def _connect_error_message(exc: BaseException) -> str:
    """Describe a connection failure by walking its exception chain."""
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(10):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return "TLS certificate verification failed"
        if isinstance(current, ssl.SSLError):
            return "TLS/SSL error"
        if isinstance(current, socket.gaierror):
            return "DNS lookup failed"
        current = current.__cause__ or current.__context__
    return "Connection failed"


def _elapsed_ms(started: float | None) -> int:
    return 0 if started is None else round((perf_counter() - started) * 1000)


def check_url(
    url: str,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> CheckResult:
    """Check one HTTP/HTTPS URL and return a structured result.

    Never raises an ``Exception``: every failure becomes an ``INVALID`` or
    ``ERROR`` result. The response body is never downloaded.
    """
    url = url.strip()
    try:
        problem = validate_url(url)
    except Exception as exc:  # defensive: validation must never abort a run
        problem = f"Invalid URL: malformed ({type(exc).__name__})"
    if problem:
        return CheckResult(url, "", None, "INVALID", 0, 0, problem)

    started: float | None = None
    final_url = ""
    redirect_count = 0
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        ) as client:
            started = perf_counter()
            # Stream so only the status line and headers are read; leaving the
            # block closes the response without downloading the body.
            with client.stream("GET", url) as response:
                status = response.status_code
                final_url = str(response.url)
                redirect_count = len(response.history)
        outcome, error = classify_status(status)
        return CheckResult(
            url, final_url, status, outcome, _elapsed_ms(started), redirect_count, error
        )
    except httpx.TooManyRedirects as exc:
        try:
            final_url = str(exc.request.url)
        except RuntimeError:  # pragma: no cover - httpx always attaches it
            final_url = ""
        error = f"Too many redirects (limit is {MAX_REDIRECTS})"
        redirect_count = MAX_REDIRECTS
    except httpx.UnsupportedProtocol:
        error = "Redirected to an unsupported URL scheme"
        final_url, redirect_count = "", 0
    except httpx.TimeoutException as exc:
        error = f"Timed out after {timeout:g}s ({_timeout_phase(exc)})"
        final_url, redirect_count = "", 0
    except httpx.ConnectError as exc:
        error = _connect_error_message(exc)
        final_url, redirect_count = "", 0
    except httpx.RequestError as exc:
        error = f"Request failed: {type(exc).__name__}"
        final_url, redirect_count = "", 0
    except (httpx.InvalidURL, ValueError) as exc:
        error = f"Request failed: {type(exc).__name__}: {_short(exc)}"
        final_url, redirect_count = "", 0
    except Exception as exc:  # never let one URL abort the batch
        error = f"Unexpected error: {type(exc).__name__}: {_short(exc)}"
        final_url, redirect_count = "", 0

    return CheckResult(
        url, final_url, None, "ERROR", _elapsed_ms(started), redirect_count, error
    )


def parse_url_lines(lines: Iterable[str]) -> list[str]:
    """Return the URL lines from ``lines``, in order.

    A URL line is any line that is not blank and does not start with ``#``
    once surrounding whitespace (and a leading byte-order mark) is removed.
    There are no inline comments.
    """
    urls = []
    for number, line in enumerate(lines):
        stripped = (line.lstrip("\ufeff") if number == 0 else line).strip()
        if stripped and not stripped.startswith("#"):
            urls.append(stripped)
    return urls


def load_urls(path: str) -> list[str]:
    """Read URL lines from a UTF-8 text file (a leading BOM is allowed)."""
    with open(path, encoding="utf-8-sig") as file:
        return parse_url_lines(file)


def _unexpected(url: str, exc: BaseException) -> CheckResult:
    return CheckResult(
        url.strip(),
        "",
        None,
        "ERROR",
        0,
        0,
        f"Unexpected error: {type(exc).__name__}: {_short(exc)}",
    )


def is_retryable(result: CheckResult) -> bool:
    """True for failures that are often temporary (timeouts, resets, 429/5xx)."""
    if result.status_code in RETRY_STATUSES:
        return True
    if result.outcome != "ERROR" or result.status_code is not None:
        return False
    error = result.error
    if error.startswith(("Timed out", "Connection failed")):
        return True
    # "Request failed: ReadError" style transport errors, but not ones that
    # carry a message about the URL itself.
    return error.startswith("Request failed: ") and error.count(":") == 1


def retry_delay(attempt: int) -> float:
    """Seconds to wait before retry number ``attempt`` (1-based): 0.5, 1, 2, 4, 4."""
    return min(0.5 * 2 ** (attempt - 1), 4.0)


_sleep = time.sleep  # replaced in tests


def check_url_with_retries(
    url: str,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
    retries: int = 0,
) -> CheckResult:
    """Like :func:`check_url`, retrying temporary failures up to ``retries`` times."""
    result = check_url(url, timeout, transport)
    attempts = 1
    while attempts <= retries and is_retryable(result):
        _sleep(retry_delay(attempts))
        result = check_url(url, timeout, transport)
        attempts += 1
    return replace(result, attempts=attempts)


ProgressCallback = Callable[[int, int], None]


def check_urls(
    urls: list[str],
    timeout: float = 10.0,
    workers: int = 10,
    transport: httpx.BaseTransport | None = None,
    retries: int = 0,
    on_progress: ProgressCallback | None = None,
) -> list[CheckResult]:
    """Check URLs concurrently and return exactly one result per URL, in order.

    A URL that appears more than once is only requested once; every occurrence
    gets its own copy of the result. ``on_progress(done, total)`` is called in
    the calling thread each time a unique URL finishes.
    """
    validate_workers(workers)
    validate_timeout(timeout)
    validate_retries(retries)
    if not urls:
        return []

    unique = list(dict.fromkeys(url.strip() for url in urls))
    pool = ThreadPoolExecutor(max_workers=min(workers, len(unique)))
    try:
        futures = {
            pool.submit(check_url_with_retries, url, timeout, transport, retries): url
            for url in unique
        }
        checked: dict[str, CheckResult] = {}
        pending = set(futures)
        while pending:
            # A short timeout keeps Ctrl+C responsive on Windows, where a
            # blocking wait cannot be interrupted.
            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            for future in done:
                url = futures[future]
                try:
                    checked[url] = future.result()
                except Exception as exc:  # defence in depth
                    checked[url] = _unexpected(url, exc)
                if on_progress is not None:
                    on_progress(len(checked), len(unique))
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return [replace(checked[url.strip()]) for url in urls]
