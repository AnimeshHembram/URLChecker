# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/AnimeshHembram/LinkCheck/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AnimeshHembram/LinkCheck/releases/tag/v0.1.0
