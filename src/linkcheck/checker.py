"""HTTP URL checking engine."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from time import perf_counter
from urllib.parse import urlparse

import httpx


@dataclass
class CheckResult:
    url: str
    final_url: str
    status_code: int | None
    outcome: str
    elapsed_ms: int
    redirect_count: int
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_url(
    url: str,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> CheckResult:
    """Check one HTTP/HTTPS URL and return a structured result."""
    url = url.strip()
    started = perf_counter()

    try:
        parsed = urlparse(url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or any(char.isspace() for char in url)
        ):
            raise ValueError("Expected a valid HTTP or HTTPS URL")

        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=10,
            headers={"User-Agent": "LinkCheck/0.1.0 (URL health checker)"},
            transport=transport,
        ) as client:
            response = client.get(url)

        status = response.status_code
        if 200 <= status < 400:
            outcome = "OK"
        elif status in {403, 429}:
            outcome = "RESTRICTED"
        elif 400 <= status < 500:
            outcome = "BROKEN"
        else:
            outcome = "SERVER_ERROR"

        return CheckResult(
            url=url,
            final_url=str(response.url),
            status_code=status,
            outcome=outcome,
            elapsed_ms=round((perf_counter() - started) * 1000),
            redirect_count=len(response.history),
        )

    except ValueError as exc:
        message = str(exc)
        return CheckResult(
            url=url,
            final_url="",
            status_code=None,
            outcome="INVALID",
            elapsed_ms=round((perf_counter() - started) * 1000),
            redirect_count=0,
            error=message,
        )
    except httpx.TooManyRedirects:
        message = "Too many redirects"
    except httpx.TimeoutException:
        message = f"Request timed out after {timeout:g}s"
    except httpx.ConnectError:
        message = "Connection failed (DNS, TLS, or network error)"
    except httpx.RequestError as exc:
        message = f"Request failed: {type(exc).__name__}"

    return CheckResult(
        url=url,
        final_url="",
        status_code=None,
        outcome="ERROR",
        elapsed_ms=round((perf_counter() - started) * 1000),
        redirect_count=0,
        error=message,
    )


def load_urls(path: str) -> list[str]:
    """Read URLs from a UTF-8 text file; ignore blanks and comments."""
    with open(path, encoding="utf-8-sig") as file:
        return [
            line.strip()
            for line in file
            if line.strip() and not line.lstrip().startswith("#")
        ]


def check_urls(
    urls: list[str],
    timeout: float = 10.0,
    workers: int = 10,
) -> list[CheckResult]:
    """Check multiple URLs concurrently, preserving input order."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if timeout <= 0:
        raise ValueError("timeout must be greater than 0")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(check_url, url, timeout) for url in urls]
        return [future.result() for future in futures]
