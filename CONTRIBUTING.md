# Contributing

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest --cov
```

- Layout: `procs.py` (discovery and kill), `sessions.py` (`openclaw sessions` wrapper),
  `history.py`, `ui.py` (pure Rich renderers), `cli.py` (Typer), `tui/` (the Textual app: `model.py` is pure and
  tested without a terminal, `app.py` is the widgets and keys). Keep logic out of `cli.py`.
- Tests that touch the process table build a fake `/proc` (see `tests/conftest.py`), so no real
  gateway is needed. They require Linux; macOS/Windows skip or fail on `os.getuid`/`/proc`.
- A change that alters what can be killed must keep the invariant: never signal a process that
  lacks a gateway signature, and re-check the cmdline right before signalling.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:` ...). Update `CHANGELOG.md`.
- Docs live in `docs/` (Zensical, `zensical.toml`): `uv run zensical serve` to preview, `uv run zensical build` must pass (it is strict, so broken links fail). The walkthrough video is described in `docs/getting-started/walkthrough.md`.

## Releasing to PyPI

Publishing uses PyPI trusted publishing (OIDC), so no token is stored anywhere.

One-time setup (owner):

1. On <https://pypi.org/manage/account/publishing/> add a **pending publisher**: project `clawtop`,
   owner `khiladisngh`, repository `clawtop`, workflow `release.yml`, environment `pypi`.
2. The `pypi` environment already exists in the GitHub repository (Settings, Environments); add a
   required reviewer there if you want a manual approval gate before each upload.

Each release:

1. Bump `version` in `pyproject.toml`, run `uv lock`, and move the `CHANGELOG.md` entries under the new
   version. Merge to `main` with CI green.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. The workflow checks the tag equals the package version,
   builds, runs `twine check --strict`, and uploads. PyPI versions cannot be replaced, so a bad upload
   means a new version number.
3. Verify with `uv tool install clawtop==X.Y.Z` in a clean environment.
