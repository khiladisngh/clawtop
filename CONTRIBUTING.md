# Contributing

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest --cov
```

- Layout: `procs.py` (discovery and kill), `sessions.py` (`openclaw sessions` wrapper),
  `history.py`, `ui.py` (pure Rich renderers), `cli.py` (Typer). Keep logic out of `cli.py`.
- Tests that touch the process table build a fake `/proc` (see `tests/conftest.py`), so no real
  gateway is needed. They require Linux; macOS/Windows skip or fail on `os.getuid`/`/proc`.
- A change that alters what can be killed must keep the invariant: never signal a process that
  lacks a gateway signature, and re-check the cmdline right before signalling.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:` ...). Update `CHANGELOG.md`.
- Docs live in `docs/` (Zensical, `zensical.toml`): `uv run zensical serve` to preview, `uv run zensical build` must pass (it is strict, so broken links fail). The walkthrough video is described in `docs/getting-started/walkthrough.md`.
