# Changelog

## 0.3.0

- Dark mode in the docs (follows the OS; header button switches system / light / dark).
- PyPI release workflow (`release.yml`, trusted publishing): push a `vX.Y.Z` tag to publish.
- README links are absolute so the PyPI page renders correctly.
- Documentation site (Zensical, GitHub Pages) with a walkthrough video and a 30-second animated preview in the README.
- `scripts/demo.py` patches prompts at `typer.prompt`/`typer.confirm` instead of Typer internals.

## 0.2.3

- `scripts/demo.py`: run the real CLI against made-up sample data, so you can try clawtop (and record demos) without a gateway.
- Status notes are labelled `vm:` / `gateway:`; the tree no longer prints `main main`.

## 0.2.2

- `sessions tree` now includes sessions that finished in the last 6h (`--within N`, 0 = open only), so subagents show under their parent instead of vanishing minutes after they end.
- `openclaw` is run from the home directory, so clawtop works even when your shell is in a deleted directory.

## 0.2.1

- Fix: archived sessions were listed as open (the gateway JSON has no archived flag); the flag is now read read-only from the agent database, so `prune` no longer re-archives them.

## 0.2.0

- `sessions tree`: sessions grouped by agent with subagents nested under the session that spawned them; finished parents are shown dimmed for context.
- `sessions list --titles`: show the session title (label). Archive and prune previews now show titles.

## 0.1.1

- Show reclaimable page cache in the gateway breakdown (cgroup memory includes it).
- Status layout fits 80 columns.

## 0.1.0

- Typer CLI: `status`, `watch`, `kill`, `history`, `sessions list|archive|prune`, `sampler install|uninstall`.
- Per-run-stack PSS memory, idle time from the claude transcript, orphan detection.
- Kills only gateway-signed processes, as whole stacks, with PID-reuse guard.
- Windows launcher that forwards to the WSL distro.
- Replaces the single-file `oc-mem` script.
