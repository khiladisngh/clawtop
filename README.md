# clawtop

**htop for [OpenClaw](https://openclaw.ai).** See where your gateway's memory is going, per agent
run, kill the runaway ones, and keep your open sessions tidy.

```text
╭─ gateway pid 999  up 21m ─────────────────────────────────────────────────────╮
│                                                                               │
│  VM       ██████░░░░░░░░░░░░░░░░░░  27%  4.3G / 15.6G   swap 0M   pressure 0.0%│
│  Gateway  ████████░░░░░░░░░░░░░░░░  41%  4.5G / 11.0G high, 13.0G max         │
│           main 1.9G · run stacks 2.1G · other 0.5G                            │
│                                                                               │
│  Agent run stacks (3)                                                         │
│     PID  AGENT  SESSION   IDLE   AGE   CTX    MEM  PARTS        FLAG         │
│    1860  maya   3e6eaad5    2m    8m  1.0M  808M  notion,rea                  │
│    2707  atlas  5c897a63   54m   58m  0.4M  412M  notion,rea    STALE         │
│    3419  forge  1985e588    4m    9m  2.1M  143M  notion,rea                  │
│                                                                               │
│  clawtop kill   [1 stale: clawtop kill --idle 30]                             │
╰───────────────────────────────────────────────────────────────────────────────╯
```

## Why

Every OpenClaw agent run backed by the `claude` CLI spawns a private process stack: `claude`
itself plus its MCP servers (`rea mcp`, `npx @notionhq/notion-mcp-server`, ...). Each stack is
roughly 0.5 to 0.7 GB. A burst of runs, or a handful that hang on a tool call, can push the
gateway past the VM's RAM; the event loop then stalls in swap and restarts fail. `clawtop` makes
that visible and fixable in one command.

- **Per-run memory** in PSS, so numbers add up to the gateway cgroup total.
- **Real idleness**: taken from the claude transcript's last write, not the process age, so a
  long-lived but busy run is not flagged and a stuck one is.
- **Safe kills**: only gateway-spawned processes can be selected (your own `claude`/`npx` are
  never touched), whole stacks die together (SIGTERM, then SIGKILL), and PID reuse is guarded.
- **Session hygiene** through the supported `openclaw sessions` CLI: list, archive, prune.
- **History**: a per-minute sampler and `clawtop history` to see what a spike looked like.
- **Runs from Windows too**: it forwards into your WSL distro automatically.

## Install

Inside the Linux/WSL environment that runs the gateway (needs `uv` and Python 3.11+):

```sh
uv tool install git+https://github.com/khiladisngh/clawtop
clawtop sampler install     # optional: per-minute memory history via a systemd user timer
```

On a Windows host, install it there as well; it then forwards every command into WSL:

```powershell
uv tool install git+https://github.com/khiladisngh/clawtop
$env:CLAWTOP_WSL_DISTRO = "OpenClawGateway"   # defaults shown
$env:CLAWTOP_WSL_USER   = "openclaw"
clawtop
```

## Usage

| Command | What it does |
|---|---|
| `clawtop` / `clawtop status` | VM and gateway memory plus every agent run stack. `--json` for scripts. |
| `clawtop watch` | Live view, refreshed every few seconds (`-i 1` for faster). |
| `clawtop kill` | Interactive picker: choose rows by number, `stale`, or `all`. |
| `clawtop kill PID...` | Kill specific stacks by leader PID. |
| `clawtop kill --idle 30` | Kill runs with no transcript activity for 30 minutes. |
| `clawtop kill --older-than 120` | Kill runs older than 2 hours. |
| `clawtop kill --orphans` | Kill gateway-signed stacks whose parent process is gone. |
| `clawtop history --last 6h` | Sparkline of gateway memory, the peak, and which stacks were alive then. |
| `clawtop sessions list` | Open sessions, longest idle first. `--all`, `--agent`, `--kind`, `--idle-min`. |
| `clawtop sessions archive KEY...` | Archive specific sessions. |
| `clawtop sessions prune` | Archive open **subagent** sessions idle for 6h (`--idle-hours`, `--kind`, `--agent`). |
| `clawtop sampler install\|uninstall` | Manage the per-minute sampler timer. |

`kill` and `sessions archive/prune` ask for confirmation; use `--yes` to skip it and `--dry-run`
to preview. `sessions prune` only touches subagent sessions unless you pass `--kind`, because
channel and main sessions hold conversation context.

### Mapping a run stack to a session

The gateway does not expose which OpenClaw session key a `claude` process belongs to, so
`clawtop` shows the agent and the CLI session id instead of guessing. Use `CTX` (transcript size)
and `IDLE` to decide; `clawtop sessions list` gives the gateway's view separately.

## Recommended gateway hardening

`clawtop` shows problems; these systemd settings (`~/.config/systemd/user/openclaw-gateway.service.d/memory-limits.conf`)
keep them from taking the VM down:

```ini
[Service]
KillMode=control-group   # a stop/restart also kills claude/MCP children
MemoryHigh=11G           # throttle + reclaim first
MemoryMax=13G            # hard backstop
MemorySwapMax=3G
OOMPolicy=continue       # an OOM kill of one child must not stop the whole gateway
```

Pick values for your VM (`memory=` in `.wslconfig`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLAWTOP_LOG` | `~/.openclaw/logs/mem-samples.jsonl` | Where the sampler writes and `history` reads. Rotates at 20 MB. |
| `CLAWTOP_WSL_DISTRO` | `OpenClawGateway` | WSL distro used when run from Windows. |
| `CLAWTOP_WSL_USER` | `openclaw` | WSL user used when run from Windows. |

## Limits

- Linux only (reads `/proc` and cgroup v2); on Windows it needs WSL.
- It looks for the systemd **user** unit `openclaw-gateway`.
- Process discovery is by signature (claude/MCP processes under `/opt/openclaw/workspaces/` or
  launched with `/tmp/openclaw-cli-mcp-*`); other agent backends are shown only as gateway "other".

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest --cov
```

The `/proc` parser tests build a fake `/proc` tree and need Linux; on Windows they are skipped
and CI runs them. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
