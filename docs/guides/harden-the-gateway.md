# Harden the gateway

clawtop shows the problem. These settings stop it taking the whole VM down. They are what the author
runs on a 16 GB WSL VM; adjust the numbers to yours (`memory=` in `.wslconfig`).

## 1. Size the VM

In `%UserProfile%\.wslconfig` on Windows:

```ini
[wsl2]
memory=16GB
swap=4GB
processors=4
```

Apply it with `wsl --shutdown` (stop the gateway first: `openclaw gateway stop`).

## 2. Limit the gateway's cgroup

Create `~/.config/systemd/user/openclaw-gateway.service.d/memory-limits.conf`:

```ini
[Service]
KillMode=control-group
MemoryHigh=11G
MemoryMax=13G
MemorySwapMax=3G
OOMPolicy=continue
```

then `systemctl --user daemon-reload` and restart the gateway.

| Setting | Why |
|---|---|
| `KillMode=control-group` | A stop or restart kills every child. The default left agent and MCP processes alive after a failed shutdown, which starved the next start. |
| `MemoryHigh=11G` | Soft limit. Above it the gateway slows down while the kernel drops cache and moves idle memory to swap. Swap climbing means you are at this limit. |
| `MemoryMax=13G` | Hard limit; the kernel kills a process in the cgroup above it. Leaves headroom for the rest of the VM. |
| `MemorySwapMax=3G` | Caps how much swap the gateway can use. |
| `OOMPolicy=continue` | An OOM kill of one child does not stop the whole gateway unit. |

## 3. Cap concurrency

Each concurrent agent run costs roughly 0.5 to 0.7 GB. A budget of about 6 GB for runs allows about 8
at once. Set the limits to fit:

```sh
openclaw config set agents.defaults.maxConcurrent 8 --strict-json
openclaw config set agents.defaults.subagents.maxConcurrent 4 --strict-json
```

The gateway applies this without a restart. Runs beyond the cap wait in a queue, so bursts get slower
instead of heavier.

## 4. Sample and watch

```sh
clawtop sampler install
clawtop top
```

## What swap is, briefly

Swap is memory kept on disk. When RAM runs short, the kernel moves idle pages there. That is fine in
small amounts. Disk is thousands of times slower than RAM, so a process that needs swapped-out pages
spends its time waiting. That is what froze the gateway's event loop when it used about 3.8 GB of swap in
an 8 GB VM.
