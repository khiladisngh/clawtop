# Configuration

clawtop has no config file of its own. It reads OpenClaw's configuration, and these environment
variables adjust what it looks for.

| Variable | Default | Meaning |
|---|---|---|
| `CLAWTOP_UNIT` | `openclaw-gateway` | Name of the gateway's systemd **user** unit. Set it if you run a profile or a renamed unit |
| `CLAWTOP_WORKSPACES` | | `:`-separated directories whose subdirectories are agent workspaces, added to what the OpenClaw config declares |
| `CLAWTOP_LOG` | `<state dir>/logs/mem-samples.jsonl` | File the sampler writes and `history` reads. Rotated to `.1` at 20 MB |
| `CLAWTOP_WSL_DISTRO` | your default WSL distro | WSL distro used when you run clawtop from Windows |
| `CLAWTOP_WSL_USER` | the distro's default user | WSL user used when you run clawtop from Windows |

clawtop also honours OpenClaw's own `OPENCLAW_STATE_DIR` (default `~/.openclaw`) and
`OPENCLAW_CONFIG_PATH` (default `<state dir>/openclaw.json`).

## What it reads from OpenClaw

- **Agent workspaces**, from the config file: `agents.defaults.workspace` (a directory whose
  subdirectories are workspaces) and `agents.entries.<id>.workspace` (one agent's workspace). A run is
  attributed to an agent by its working directory. The file is only read. If it is JSON5 and cannot be
  parsed as JSON, clawtop falls back to a lenient scan for `workspace` values.
- **Sessions**, through `openclaw sessions --all-agents --limit all --json`. `openclaw` must be on `PATH`.
- **The archived flag**, read-only from `<state dir>/agents/*/agent/openclaw-agent.sqlite`
  (`session_nodes.archived_at`). If that layout changes, clawtop treats nothing as archived.

## Other assumptions

- The gateway is a systemd **user** unit. clawtop asks `systemctl --user show <unit>` for its main PID
  and cgroup (cgroup v2).
- Claude Code's transcripts, used for idle time, live under `~/.claude/projects/`. This is the only
  runtime-specific path; see [Concepts](../concepts.md#why-idle-can-be-).

If `clawtop status` shows no run stacks although runs are active, the usual causes are in
[Troubleshooting](../troubleshooting.md#no-run-stacks-are-listed).

## Forwarding from Windows

On Windows, `clawtop ARGS` runs
`wsl.exe [-d $CLAWTOP_WSL_DISTRO] [-u $CLAWTOP_WSL_USER] -e bash -lc 'exec clawtop "$@"' clawtop ARGS`
and returns its exit code; the options in brackets are included only when the variable is set.
clawtop must be installed inside the distro for that user.
