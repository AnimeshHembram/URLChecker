# LinkCheck CLI

A free, local-first command-line tool that checks supplied HTTP/HTTPS URLs,
records HTTP status and redirects, and exports results to CSV.

## Requirements

- Python 3.12 or newer
- Internet access for live URL checks

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Usage

```powershell
linkcheck check examples/urls.txt
linkcheck check examples/urls.txt --output reports/results.csv
linkcheck check examples/urls.txt --timeout 10 --workers 5
python -m linkcheck --help
```

You can also use `python -m linkcheck check examples/urls.txt`.

## Outcomes

- `OK`: HTTP 2xx or 3xx response
- `RESTRICTED`: HTTP 403 or 429; the URL may be valid but access is restricted
- `BROKEN`: HTTP 4xx other than 403 and 429
- `SERVER_ERROR`: HTTP 5xx
- `ERROR`: timeout or connection/request failure
- `INVALID`: malformed URL or unsupported scheme

A non-zero exit code indicates a failed check or a CLI/input error.
403 and 429 responses are reported separately because they do not prove a URL is broken.

## Tests

```powershell
python -m pytest -q
```

Tests use mocked HTTP responses and do not require live websites.

## Limitations

This version checks URLs supplied in a text file; it does not crawl websites.
Some servers block automated requests, so results are not definitive proof that a page
is unavailable in a normal browser. Use this tool only on URLs you are authorized to check.

## License

MIT
