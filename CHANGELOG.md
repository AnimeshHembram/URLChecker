# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-18

### Added
- Read URLs from standard input with `linkcheck check -`.
- `--json PATH` writes a JSON report with a summary block.
- `--quiet` / `-q` lists only results that are not OK.
- A URL that appears several times is requested once; every line still gets
  its own result row.
- The summary ends with the total run time.
- `--retries N` (0-5) retries timeouts, connection errors and HTTP
  429/502/503/504 with a short back-off; the JSON report records `attempts`.
- A `Checked 3/40` progress counter on interactive terminals.

### Fixed
- Repository links now point to `AnimeshHembram/URLChecker`.
- Invisible control characters in URL lines (NUL, zero-width space, tabs) are
  shown as escapes such as `\x00` in the terminal and CSV instead of being
  written raw.
- Documented the Windows `--basetemp` workaround for pytest temp-folder
  permission errors; `.pytest-tmp/` is ignored by Git.

### Changed
- Ctrl+C is handled promptly on Windows while checks are running.
- CI uses `actions/checkout@v7` and `actions/setup-python@v7`.

## [0.1.0] - 2026-10-17

First public release.

### Added
- `linkcheck check FILE` with `--output`, `--timeout`, `--workers`; `--version`.
- Six outcomes: OK, RESTRICTED, BROKEN, SERVER_ERROR, ERROR, INVALID.
- URL validation before any request (scheme, host, port, IDNA, control characters).
- Redirect following (up to 10) with final URL and redirect count.
- CSV export (UTF-8 with BOM) with credential redaction and formula neutralisation.
- Documented exit codes: 0, 1, 2, 3 (internal error) and 130 (interrupted).
- Offline test suite with a network guard, coverage gate and GitHub Actions CI.
- MIT license, contributing guide, issue template and Dependabot configuration.

### Changed
- Responses are streamed and bodies are never downloaded.
- HTTP 401 is reported as RESTRICTED instead of BROKEN.
- A final 3xx without a usable `Location` header is reported as ERROR.

### Fixed
- One malformed URL line (for example a control character or invalid host name)
  no longer crashes the whole run.
- `--timeout nan` and `--timeout inf` are rejected instead of mislabelling or crashing.

[Unreleased]: https://github.com/AnimeshHembram/URLChecker/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/AnimeshHembram/URLChecker/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AnimeshHembram/URLChecker/releases/tag/v0.1.0
