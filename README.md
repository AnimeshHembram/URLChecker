# LinkCheck CLI

[![CI](https://github.com/AnimeshHembram/URLChecker/actions/workflows/ci.yml/badge.svg)](https://github.com/AnimeshHembram/URLChecker/actions/workflows/ci.yml)
![Python 3.12 | 3.13](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A free, local-first command-line tool that checks a list of HTTP/HTTPS URLs,
follows redirects, explains what went wrong with each link, and exports the
results to a CSV file you can open in Excel or Google Sheets, or to JSON for
scripts and dashboards.

It checks only the URLs you give it. It does not crawl websites. The repository
is called **URLChecker**; the command it installs is `linkcheck`.

Example output (timings will differ):

```text
$ linkcheck check urls.txt -o report.csv
LinkCheck: checking 4 URL(s)...

RESULT          HTTP     TIME REDIR  URL
----------------------------------------------------------------------------------------------------
OK               200    312 ms     0  https://example.com
OK               200    205 ms     0  https://www.python.org
BROKEN           404    640 ms     0  https://httpbin.org/status/404
OK               200    910 ms     2  https://httpbin.org/redirect/2
    Final URL: https://httpbin.org/get
----------------------------------------------------------------------------------------------------
Total: 4 URL(s)
  BROKEN: 1
  OK: 3
Finished in 2.4s
CSV report saved to: report.csv
```

## Requirements

- Python 3.12 or newer (tested on 3.12 and 3.13)
- Internet access for real checks

## Installation

Clone the repository, create a virtual environment and install LinkCheck into it.

```bash
git clone https://github.com/AnimeshHembram/URLChecker.git
cd URLChecker
```

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

If PowerShell refuses to run `Activate.ps1` because of its execution policy,
skip activation and call the tools directly, for example
`.\.venv\Scripts\linkcheck.exe --version`.

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For development (tests, coverage, linting) install the extras instead:
`python -m pip install -e ".[dev]"`.

## Quick start

Create a text file with one URL per line:

```text
# Lines starting with # are comments; blank lines are ignored.
https://example.com
https://www.python.org/downloads/
https://example.com/a-page-that-moved
```

Then run:

```bash
linkcheck check urls.txt                     # print a report
linkcheck check urls.txt -o reports/out.csv  # also save a CSV
linkcheck check urls.txt --json reports/out.json   # machine-readable report
linkcheck check urls.txt --quiet             # list only links that need attention
linkcheck check urls.txt --retries 2         # retry timeouts and 429/5xx answers
linkcheck check urls.txt --timeout 5 --workers 4
Get-Content urls.txt | linkcheck check -      # read from standard input (PowerShell)
cat urls.txt | linkcheck check -              # read from standard input (macOS/Linux)
linkcheck --version
python -m linkcheck check urls.txt           # same thing, without the launcher
```

Every non-blank line that does not start with `#` is one URL line and produces
exactly one result, in the same order as the file. A URL that appears several
times is requested only once, and each of its lines gets the same result. There are no inline comments: `https://example.com/ #note` is reported as
`INVALID` because it contains a space. A `#` with no space before it is a normal
URL fragment (`https://example.com/#section`).

The file (or piped input) must be UTF-8; a byte-order mark is fine. In the old
Windows PowerShell 5.1, piping non-English URLs needs
`$OutputEncoding = [Text.UTF8Encoding]::new()` first; PowerShell 7 already sends
UTF-8.

Two example lists are included. Both contact real third-party sites:

- [`examples/urls.txt`](examples/urls.txt): a quick four-URL smoke test.
- [`examples/edge-cases.txt`](examples/edge-cases.txt): about 30 real URLs, at
  least one for every outcome (redirects, 404/410, 401/403/429, 5xx, expired and
  self-signed TLS certificates, DNS failure, redirect loop, timeout, invalid
  lines), each labelled with the expected result. Run it with
  `linkcheck check examples/edge-cases.txt --timeout 5`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `FILE` | | Text file with one URL per line, or `-` to read from standard input. |
| `-o`, `--output PATH` | none | Also write a CSV report to `PATH`. Missing folders are created. An existing file is **overwritten without asking**. |
| `--json PATH` | none | Also write a JSON report (results plus a summary) to `PATH`. Overwritten without asking. |
| `-q`, `--quiet` | off | List only results that are not `OK`. The summary still counts everything. |
| `--retries N` | `0` | Retry timeouts, connection errors and HTTP 429/502/503/504 answers up to `N` times (0-5), waiting 0.5 s, 1 s, 2 s, 4 s, 4 s between attempts. Other results are never retried. |
| `--timeout SECONDS` | `10` | Maximum wait for **each network step**: connecting, sending the request, and waiting for the server to start answering. Must be greater than 0 and at most 600. It is not a cap on the total time per URL; a URL that redirects makes one request per hop, so it can take longer than `SECONDS` overall. |
| `--workers N` | `10` | How many URLs are checked at the same time, from 1 to 50. |
| `--version` | | Print the version and exit. |

While a list of several URLs is being checked in an interactive terminal, a
`Checked 12/40` counter is shown on the error stream. It is not shown when the
output is redirected to a file or pipe.

## Outcomes

| Outcome | When |
|---|---|
| `OK` | The final response (after following up to 10 redirects) is 2xx. |
| `RESTRICTED` | The final response is **401, 403 or 429**. The page probably exists but needs a login, blocks automated requests, or is rate limiting. |
| `BROKEN` | The final response is any other 4xx, such as 404 or 410. |
| `SERVER_ERROR` | The final response is 5xx. |
| `ERROR` | The check could not finish: timeout, DNS lookup failure, TLS/certificate problem, refused connection, proxy failure, more than 10 redirects, a redirect to a non-HTTP address, a redirect without a usable `Location` header, or an unexpected status code. The `error` column says which. |
| `INVALID` | The line is not a checkable URL, so no request was made: unsupported or missing scheme (only `http` and `https`), missing host, invalid port, invalid host name, or spaces/control characters. |

LinkCheck reads only the status line and headers. It never downloads page
bodies, so links to large files are checked quickly.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Finished; every result is `OK` or `RESTRICTED` (or the file had no URL lines). |
| `1` | Finished; at least one result is `BROKEN`, `SERVER_ERROR`, `ERROR` or `INVALID`. |
| `2` | Usage, input or output problem: bad option, input missing or not UTF-8, or a report could not be written. |
| `3` | Internal error in LinkCheck (a bug). Set the environment variable `LINKCHECK_DEBUG=1` to print the full traceback, and please report it. |
| `130` | Interrupted with Ctrl+C. No report is written. |

`RESTRICTED` results never change the exit code, because a 401/403/429 does not
prove that a link is broken.

## CSV report

The CSV has one row per URL line, in input order, and these columns:

| Column | Meaning |
|---|---|
| `url` | The URL as written in your file |
| `final_url` | Where the URL ended up after redirects (empty if no response) |
| `status_code` | Final HTTP status code (empty if no response) |
| `outcome` | One of the six outcomes above |
| `elapsed_ms` | Time from sending the request to receiving the final response headers, in milliseconds |
| `redirect_count` | Number of redirects followed |
| `error` | Explanation for `ERROR` and `INVALID` results |

The file is UTF-8 with a byte-order mark so that Excel shows non-English
characters correctly. For safety:

- Passwords and user names written inside URLs (`https://user:password@host/`)
  are replaced with `***` in the terminal output, the CSV and the JSON.
- Invisible characters in a URL line (for example a NUL byte or a zero-width
  space, which make the line `INVALID`) are shown as escapes such as `\x00` or
  `\u200b` instead of being written raw.
- Any cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets
  a leading `'` so spreadsheet programs do not run it as a formula.

## JSON report

`--json PATH` writes UTF-8 JSON (no byte-order mark) like this:

```json
{
  "tool": "linkcheck",
  "version": "0.2.1",
  "generated_at": "2026-10-18T15:30:00+00:00",
  "elapsed_seconds": 2.412,
  "summary": {"total": 4, "problems": 1, "outcomes": {"BROKEN": 1, "OK": 3}},
  "results": [
    {
      "url": "https://httpbin.org/redirect/2",
      "final_url": "https://httpbin.org/get",
      "status_code": 200,
      "outcome": "OK",
      "elapsed_ms": 910,
      "redirect_count": 2,
      "error": "",
      "attempts": 1
    }
  ]
}
```

`results` has the same fields as the CSV plus `attempts` (how many requests were
made, counting retries). Credentials in URLs are redacted; `problems` counts the
results that make the exit code 1.

## Privacy and responsible use

- LinkCheck runs on your computer. The only network traffic is one GET request
  per URL (plus redirects), sent with the User-Agent
  `LinkCheck/<version> (+URL health checker)`.
- Nothing is uploaded or stored anywhere except the reports you ask for.
- Query strings are **not** redacted. Remove tokens from URLs before sharing
  reports.
- Check only URLs you are allowed to check, and keep `--workers` modest when
  many URLs point at the same site.

## Limitations

- No crawling, sitemap parsing or link extraction from pages.
- Page content is not inspected, so a page that says "not found" but returns
  HTTP 200 (a "soft 404") is reported as `OK`. For example, PyPI answers unknown
  project pages with 200.
- Some servers block automated requests, which can show up as `RESTRICTED` or
  `ERROR` even though the page works in a browser.
- Retries are off by default (`--retries`), and there is no per-site rate
  limiting; `elapsed_ms` describes the last attempt only.
- `--timeout` limits each network step, not the total time per URL.
- After Ctrl+C the program stops waiting immediately, but requests already in
  progress may keep it running for up to `--timeout` seconds before it exits.
- Response bodies of intermediate redirects may be read by the HTTP library
  (they are normally tiny).

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest                                                # offline tests
python -m pytest --cov=linkcheck --cov-branch --cov-report=term-missing --cov-fail-under=90
python -m ruff check .
python -m ruff format .
```

On Windows, if pytest reports `WinError 5` for its temporary folders, add
`--basetemp=.pytest-tmp`.

The tests never contact the internet. HTTP is simulated with `httpx.MockTransport`
and a small local server on `127.0.0.1`, and a guard in `tests/conftest.py` makes
any other connection fail.

Project layout:

```text
src/linkcheck/checker.py   validation, HTTP checks, classification
src/linkcheck/reporter.py  terminal table, CSV and JSON export
src/linkcheck/cli.py       command-line interface and exit codes
tests/                     offline test suite
```

See [CHANGELOG.md](CHANGELOG.md) for release notes and
[CONTRIBUTING.md](CONTRIBUTING.md) if you would like to help.

## License

MIT. See [LICENSE](LICENSE).
