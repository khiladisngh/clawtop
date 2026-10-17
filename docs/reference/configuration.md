# Configuration

clawtop has no config file. These environment variables are the only settings.

| Variable | Default | Meaning |
|---|---|---|
| `CLAWTOP_LOG` | `~/.openclaw/logs/mem-samples.jsonl` | File the sampler writes and `history` reads. Rotated to `.1` at 20 MB. |
| `CLAWTOP_WSL_DISTRO` | `OpenClawGateway` | WSL distro used when you run clawtop from Windows |
| `CLAWTOP_WSL_USER` | `openclaw` | WSL user used when you run clawtop from Windows |

## Fixed assumptions

- The gateway is the systemd **user** unit `openclaw-gateway`. clawtop asks `systemctl --user show` for
  its main PID and cgroup.
- Agent workspaces live under `/opt/openclaw/workspaces/`.
- Claude transcripts live under `~/.claude/projects/`.
- Agent databases live under `~/.openclaw/agents/*/agent/openclaw-agent.sqlite` (read-only, for the
  archived flag only).
- `openclaw` must be on `PATH` for the `sessions` commands.

If your layout differs, `status` and `kill` will show no run stacks. Open an issue with your layout.

## Forwarding from Windows

On Windows, `clawtop ARGS` runs
`wsl.exe -d $CLAWTOP_WSL_DISTRO -u $CLAWTOP_WSL_USER -e bash -lc 'exec clawtop "$@"' clawtop ARGS`
and returns its exit code. clawtop must be installed inside the distro for that user.
