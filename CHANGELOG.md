# Changelog

## 0.1.0

- Typer CLI: `status`, `watch`, `kill`, `history`, `sessions list|archive|prune`, `sampler install|uninstall`.
- Per-run-stack PSS memory, idle time from the claude transcript, orphan detection.
- Kills only gateway-signed processes, as whole stacks, with PID-reuse guard.
- Windows launcher that forwards to the WSL distro.
- Replaces the single-file `oc-mem` script.
