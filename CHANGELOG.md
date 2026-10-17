# Changelog

## 0.3.0

- **Runtime-independent.** Run stacks are no longer found by looking for `claude`. A run is the top
  process in the gateway's tree that is not OpenClaw's own code and works in an agent workspace (read from
  the OpenClaw config); it is labelled by its executable. Works for any CLI backend or ACP harness that
  runs as a process. Verified on Claude CLI only.
- New `RUNTIME` column in `status`, `watch` and `kill`; `sessions list` shows OpenClaw's runtime id.
- Idle time is `-` for runtimes with no activity source (only Claude Code's transcript is supported); it
  is never guessed from age. `STALE` and `kill --idle` only use known idle times, and `kill --idle` says
  how many runs it skipped.
- Helper processes are named by what they run (`docs-mcp`, `search-mcp`), not by a fixed list.
- A hand-started CLI is recognised as not gateway-owned by its environment (OpenClaw's gateway markers),
  not by its name.
- Honours `OPENCLAW_STATE_DIR` / `OPENCLAW_CONFIG_PATH`; new `CLAWTOP_UNIT` and `CLAWTOP_WORKSPACES`.
- The Windows launcher uses your default WSL distro and user unless `CLAWTOP_WSL_DISTRO` /
  `CLAWTOP_WSL_USER` are set (the old defaults were specific to one machine).
- Status says when the runtime runs inside the gateway (no per-run process) or no workspaces were found.
- Dark mode in the docs (follows the OS; header button switches system / light / dark).
- PyPI release workflow (`release.yml`, trusted publishing): push a `vX.Y.Z` tag to publish.
- Fix: docs admonitions (`!!! note`) rendered as literal text because the markdown extension list replaced Zensical's defaults; CI now fails if that happens.
- `Documentation` project URL.
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
