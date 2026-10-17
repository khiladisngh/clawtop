# CLI reference

Run `clawtop COMMAND --help` for the same information in your terminal. `-h` is accepted wherever
`--help` is.

## `clawtop`

With no command, prints the status overview. `--version` prints the version.

## `clawtop status`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | Machine-readable output |
| `--stale-min N` | 30 | Minutes without activity before a run is flagged `STALE` |

## `clawtop watch`

| Option | Default | Meaning |
|---|---|---|
| `-i`, `--interval SEC` | 3 | Seconds between refreshes (minimum 0.5) |
| `--stale-min N` | 30 | As above |

## `clawtop kill [PID...]`

With no selector and a terminal, opens the interactive picker.

| Option | Default | Meaning |
|---|---|---|
| `PID...` | | Run-stack leader PIDs from `status` |
| `--idle MIN` | | Stacks with no transcript activity for MIN minutes. Skips runs whose runtime has no activity source (`IDLE` is `-`) and says how many |
| `--older-than MIN` | | Stacks older than MIN minutes (works for every runtime) |
| `--orphans` | off | Gateway-signed stacks whose parent is gone |
| `-y`, `--yes` | off | Skip confirmation |
| `--dry-run` | off | Show the selection and stop |
| `--grace SEC` | 5 | Seconds between SIGTERM and SIGKILL |
| `--stale-min N` | 30 | Threshold used by the picker's `stale` answer |

Without a selector and without a terminal it exits with an error. Exit code 1 if you decline, if a PID is
not a stack leader, or if a process survived.

## `clawtop history`

| Option | Default | Meaning |
|---|---|---|
| `-l`, `--last WINDOW` | `6h` | A number plus `m`, `h` or `d` |
| `--log PATH` | `$CLAWTOP_LOG` or the default | Samples file |

## `clawtop sessions list`

| Option | Meaning |
|---|---|
| `-a`, `--all` | Include finished and archived sessions |
| `--agent ID` | Only this agent (repeatable) |
| `--kind KIND` | Only this kind (repeatable): `subagent`, `cron`, `discord`, `main`, `node` |
| `--idle-min MIN` | Only sessions idle at least this long |
| `-t`, `--titles` | Add the title column |


The table has a `RUNTIME` column with OpenClaw's runtime id for the session (`claude-cli`, `codex`,
`openclaw`, ...), or `-` if OpenClaw does not report one. `--json` is not offered; use
`openclaw sessions --json` for raw data.

## `clawtop sessions tree`

Takes `--all`, `--agent`, `--kind` and `--idle-min` like `list`, plus:

| Option | Default | Meaning |
|---|---|---|
| `--within HOURS` | 6 | Also show finished sessions active in the last HOURS (0 = open only) |

## `clawtop sessions archive KEY...`

| Option | Meaning |
|---|---|
| `-y`, `--yes` | Skip confirmation |
| `--dry-run` | Preview only |

## `clawtop sessions prune`

| Option | Default | Meaning |
|---|---|---|
| `--idle-hours H` | 6 | Archive open sessions idle at least this long |
| `--kind KIND` | `subagent` | Kinds to prune (repeatable) |
| `--agent ID` | all | Limit to these agents |
| `-y`, `--yes` | off | Skip confirmation |
| `--dry-run` | off | Preview only |

## `clawtop sampler install | uninstall`

Installs or removes the systemd user timer `clawtop-sample.timer`. (`clawtop sample` is a hidden command
the timer runs; it appends one sample.)

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Declined confirmation, invalid selection, a failed `openclaw` call, or survivors after `kill` |
| 2 | Usage error (bad option) |
