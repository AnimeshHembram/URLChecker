# Contributing to LinkCheck

Thanks for your interest! Bug reports, ideas and pull requests are welcome.

## Reporting a bug

Open an [issue](https://github.com/AnimeshHembram/LinkCheck/issues) and include:

- the command you ran and the output (remove any private URLs or tokens),
- `linkcheck --version`, your operating system and Python version,
- what you expected to happen.

## Making a change

1. Fork the repository and create a branch.
2. Set up a development environment:

   ```bash
   python -m venv .venv
   # Windows: .\.venv\Scripts\Activate.ps1   macOS/Linux: source .venv/bin/activate
   python -m pip install -e ".[dev]"
   ```

3. Make your change and add tests for it in `tests/`.
4. Make sure everything passes:

   ```bash
   python -m ruff check .
   python -m ruff format --check .
   python -m pytest --cov=linkcheck --cov-branch --cov-fail-under=90
   ```

5. Add a line to the "Unreleased" section of `CHANGELOG.md` and open a pull request.

## Ground rules

- Tests must not contact the internet. Use `httpx.MockTransport` or the
  `local_server` fixture in `tests/conftest.py`.
- Keep files UTF-8 without a byte-order mark, with LF line endings
  (`.gitattributes` enforces this).
- Keep the scope focused: LinkCheck checks a list of URLs. Crawling, a GUI and
  monitoring are out of scope for now.

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
