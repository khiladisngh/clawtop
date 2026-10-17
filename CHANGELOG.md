# Changelog

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
