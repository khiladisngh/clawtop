# Watch memory

## One-off overview

```sh
clawtop status
```

(Plain `clawtop` prints the same thing when its output is not a terminal, for example in a pipe.) The panel has three parts:

- **Bars.** `VM` is the whole WSL/Linux machine. `Gateway` is the gateway's cgroup measured against its
  `MemoryHigh` limit, or against the VM when no limit is set.
- **Notes.** Swap used and memory pressure; the gateway main process, the run stacks and other helpers;
  reclaimable page cache and the hard `MemoryMax` limit.
- **Run table.** One row per agent run; see [Concepts](../concepts.md) for what each column means.

!!! tip "Why the gateway bar is higher than the process sizes add up to"
    The cgroup counts **page cache** (files the kernel keeps in RAM, such as the SQLite databases). The
    notes line shows it as reclaimable. The kernel drops cache first when memory gets tight.

## Live view

```sh
clawtop
```

An interactive dashboard with a memory graph, sorting, filtering, marking, kill and a session tree. See
[The interactive screen](interactive-top.md).

## For scripts

```sh
clawtop status --json
```

prints one JSON object: memory figures, the cgroup limits, and a `stacks` array with each run's PID,
agent, memory, age, idle time and member PIDs.

## When to act

| You see | Meaning | Do |
|---|---|---|
| Gateway bar near 100% of `high` | The kernel starts throttling and moving idle memory to swap | [Stop runaway runs](stop-runaway-runs.md) |
| `STALE` rows | Runs idle for 30+ minutes still hold 0.5 GB each | `clawtop kill --idle 30` |
| Swap climbing, pressure above a few percent | The gateway is running out of real RAM | Free memory now, then [harden the gateway](harden-the-gateway.md) |
