# Install

clawtop needs `uv` and Python 3.11 or newer. It reads `/proc` and cgroup v2, so it runs on Linux; on
Windows it forwards to WSL.

## On the machine that runs the gateway (Linux or WSL)

```sh
uv tool install clawtop
clawtop --version
clawtop        # one-shot overview
clawtop top    # the interactive screen
```

Or with pipx (`pipx install clawtop`) or pip (`pip install clawtop`) if you prefer. The package is on
[PyPI](https://pypi.org/project/clawtop/).

Optional: record a memory sample every minute, so `clawtop history` has data.

```sh
clawtop sampler install
```

This installs a systemd **user** timer (`clawtop-sample.timer`). See
[Keep a memory history](../guides/memory-history.md).

## On a Windows host

Install it on Windows too. Every command is forwarded into your WSL distro, so `clawtop` works from
PowerShell exactly as it does inside Linux:

```powershell
uv tool install clawtop
clawtop
```

It uses your default WSL distro and that distro's default user. If the gateway lives in another distro,
set `CLAWTOP_WSL_DISTRO` and `CLAWTOP_WSL_USER`; see [Configuration](../reference/configuration.md).

!!! note
    The forwarded command runs `clawtop` inside WSL, so clawtop must be installed there as well.

## Update

```sh
uv tool upgrade clawtop
```

## Requirements it checks at runtime

- The gateway runs as the systemd user unit `openclaw-gateway`.
- `openclaw` is on `PATH` (used for the `sessions` commands).
- Agent run processes are started by the gateway in an agent workspace listed in your OpenClaw config
  (see [how they are recognised](../concepts.md#what-counts-as-a-gateway-run)). Runtimes that run inside
  the gateway process have no process of their own, so there is nothing per run to list for them.
