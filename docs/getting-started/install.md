# Install

clawtop needs `uv` and Python 3.11 or newer. It reads `/proc` and cgroup v2, so it runs on Linux; on
Windows it forwards to WSL.

## On the machine that runs the gateway (Linux or WSL)

```sh
uv tool install git+https://github.com/khiladisngh/clawtop
clawtop --version
clawtop
```

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
uv tool install git+https://github.com/khiladisngh/clawtop
clawtop
```

Defaults assume the distro is `OpenClawGateway` and the user is `openclaw`. Change them with
`CLAWTOP_WSL_DISTRO` and `CLAWTOP_WSL_USER`; see [Configuration](../reference/configuration.md).

!!! note
    The forwarded command runs `clawtop` inside WSL, so clawtop must be installed there as well.

## Update

```sh
uv tool install --force git+https://github.com/khiladisngh/clawtop
```

## Requirements it checks at runtime

- The gateway runs as the systemd user unit `openclaw-gateway`.
- `openclaw` is on `PATH` (used for the `sessions` commands).
- Agent run processes are launched by the gateway (see [how they are recognised](../concepts.md#what-counts-as-a-gateway-run)).
