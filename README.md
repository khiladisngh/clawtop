# clawtop

[![ci](https://github.com/khiladisngh/clawtop/actions/workflows/ci.yml/badge.svg)](https://github.com/khiladisngh/clawtop/actions/workflows/ci.yml)
[![docs](https://github.com/khiladisngh/clawtop/actions/workflows/docs.yml/badge.svg)](https://khiladisngh.github.io/clawtop/)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/khiladisngh/clawtop/blob/main/LICENSE)
![python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

**htop for [OpenClaw](https://openclaw.ai).** See where your gateway's memory goes, per agent run; stop
the runaway ones safely; keep your sessions tidy.

<p align="center">
  <a href="https://khiladisngh.github.io/clawtop/getting-started/walkthrough/">
    <img src="https://raw.githubusercontent.com/khiladisngh/clawtop/main/docs/assets/walkthrough/preview.gif"
         alt="Animated preview: clawtop status, the interactive kill picker, and the session tree"
         width="760">
  </a>
  <br>
  <sub>30-second preview. <a href="https://khiladisngh.github.io/clawtop/getting-started/walkthrough/">Watch the full 1:43 walkthrough</a>
  (sample data, simulated kills)</sub>
</p>

**Documentation: <https://khiladisngh.github.io/clawtop/>**

## Why

Every OpenClaw agent run backed by the `claude` CLI starts a private process stack: `claude` plus its MCP
servers (`rea mcp`, `npx @notionhq/notion-mcp-server`, ...). Each stack is roughly 0.5 to 0.7 GB. A burst
of runs, or a few that hang on a tool call, can push the gateway past the VM's RAM; the event loop then
stalls in swap and restarts fail. clawtop makes that visible and fixable in one command.

- **Memory per run**, measured so the numbers add up to the gateway's cgroup total.
- **Real idleness**, taken from each run's own transcript, so a busy long-lived run is not flagged and a
  stuck one is.
- **Safe kills.** Only processes the gateway spawned can be selected, whole stacks die together (SIGTERM,
  then SIGKILL), and PID reuse is guarded.
- **Sessions** through the supported `openclaw sessions` CLI: list, tree (subagents under their parent,
  with titles), archive, prune.
- **History**: a per-minute sampler and `clawtop history` to see what a spike looked like.
- **Works from Windows**: it forwards into your WSL distro.

## Install

On the Linux or WSL machine that runs the gateway (needs `uv` and Python 3.11+):

```sh
uv tool install git+https://github.com/khiladisngh/clawtop
clawtop
clawtop sampler install     # optional: per-minute memory history via a systemd user timer
```

On a Windows host, install it there too; every command is forwarded into WSL
(`CLAWTOP_WSL_DISTRO`, default `OpenClawGateway`; `CLAWTOP_WSL_USER`, default `openclaw`).
See [Install](https://khiladisngh.github.io/clawtop/getting-started/install/).

## Usage

| Command | What it does |
|---|---|
| `clawtop` / `status` | VM and gateway memory plus every agent run stack. `--json` for scripts. |
| `clawtop watch` | Live view, refreshed every few seconds. |
| `clawtop kill` | Interactive picker: choose rows by number, `stale` or `all`. |
| `clawtop kill PID...` | Kill specific stacks by leader PID. |
| `clawtop kill --idle 30` | Kill runs with no transcript activity for 30 minutes. |
| `clawtop kill --older-than 120` | Kill runs older than 2 hours. |
| `clawtop kill --orphans` | Kill gateway-spawned stacks whose parent is gone. |
| `clawtop history --last 6h` | Memory sparkline, the peak, and the stacks alive at the peak. |
| `clawtop sessions list [--titles]` | Open sessions, longest idle first. |
| `clawtop sessions tree` | Sessions per agent, subagents nested under their parent. |
| `clawtop sessions archive KEY...` | Archive specific sessions. |
| `clawtop sessions prune` | Archive open **subagent** sessions idle for 6h (`--idle-hours`, `--kind`, `--agent`). |
| `clawtop sampler install\|uninstall` | Manage the per-minute sampler timer. |

`kill` and `sessions archive|prune` ask for confirmation; `--yes` skips it and `--dry-run` previews.
`prune` only touches subagent sessions unless you pass `--kind`, because channel and main sessions hold
conversation context. Full options: [CLI reference](https://khiladisngh.github.io/clawtop/reference/cli/).

## Try it without a gateway

`scripts/demo.py` runs the real CLI against made-up sample data (the video above uses it); `kill` and
`archive` are simulated:

```sh
git clone https://github.com/khiladisngh/clawtop && cd clawtop && uv sync
uv run python scripts/demo.py sessions tree
CLAWTOP_DEMO_ANSWERS="stale;y" uv run python scripts/demo.py kill
```

## Keep the gateway from running out of memory

clawtop shows problems; systemd limits and a concurrency cap stop them taking the VM down. See
[Harden the gateway](https://khiladisngh.github.io/clawtop/guides/harden-the-gateway/).

## Limits

- Linux only (reads `/proc` and cgroup v2); on Windows it needs WSL.
- It looks for the systemd **user** unit `openclaw-gateway`.
- A run stack cannot be mapped to an OpenClaw session key (the gateway does not expose it), so clawtop
  shows the agent and the CLI session id instead of guessing. See
  [Concepts](https://khiladisngh.github.io/clawtop/concepts/).
- Processes are recognised by signature (workspaces under `/opt/openclaw/workspaces/`, or the gateway's
  temporary MCP config); other agent backends show up only as gateway "other".

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest --cov
uv run zensical serve     # docs at http://localhost:8000
```

The `/proc` parser tests build a fake `/proc` tree and need Linux; they are skipped on Windows and run in
CI. See [CONTRIBUTING.md](https://github.com/khiladisngh/clawtop/blob/main/CONTRIBUTING.md).

## License

MIT
