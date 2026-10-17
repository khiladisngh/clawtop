# Interactive view: `clawtop top`

A live, keyboard-driven screen in the spirit of htop and bottom: the gateway's memory, every agent run,
your sessions and the memory history, all in one terminal.

```sh
clawtop top               # refresh every 2 seconds
clawtop top -i 5          # every 5 seconds
```

![clawtop top: a tour of the Runs, Sessions and History tabs](../assets/tui/top.gif)

!!! note
    `top` needs a real terminal. In scripts and pipes use [`clawtop status --json`](watch-memory.md).
    On Windows it forwards into WSL like every other command.

## The screen

**Top bar.** Gateway PID and uptime, how many runs and how much memory they hold, the refresh interval,
the current sort and filter, and how many rows are marked.

**Memory.** Bars for the VM, the gateway cgroup (against its `MemoryHigh` limit) and swap, then the
split between main process, run stacks, other helpers and reclaimable page cache.

**Graph.** The gateway's memory over the last 10 minutes, newest on the right. It is scaled from zero up
to the limit, so a steady line looks steady and a climb towards the dotted limit line is obvious. It
starts from the sampler log if you have installed [the sampler](memory-history.md), so it is not empty at
startup.

**Tabs.** Switch with `1`, `2`, `3`, or click a tab.

### Runs

One row per agent run, with the same columns as `clawtop status` (see [Concepts](../concepts.md)).
Below the table, a **process tree** shows the highlighted run and every helper it started, with each
process's memory.

![The Runs tab with the kill confirmation](../assets/tui/top-kill.png)

| Key | Action |
|---|---|
| `↑` `↓`, `j` `k` | Move |
| `space` | Mark or unmark the row (and move down) |
| `A` | Mark every `STALE` or `ORPHAN` run; press again to clear |
| `x`, `F9` | Kill the marked runs, or the highlighted one if none are marked. Asks first |
| `s` | Next sort key: memory, idle, age, PID, agent, runtime |
| `i` | Reverse the sort. Clicking a column header also sorts by it |
| `/` | Filter. Type words; a run must match all of them (runtime, agent, PID, helper names). `Enter` keeps the filter, `Esc` clears it |

The cursor follows the run, not the row number, so it stays on the same run when a refresh reorders the
table. Runs with unknown idle time sort last when sorting by idle.

Killing works exactly as in [Stop runaway runs](stop-runaway-runs.md): the confirmation lists every run
that will be stopped and the memory it frees, and it only ever acts on processes the gateway started.

### Sessions

![The Sessions tab](../assets/tui/top-sessions.png)

The same tree as [`clawtop sessions tree`](manage-sessions.md): one group per agent, subagents nested
under the session that spawned them, with titles. It loads from `openclaw` when you open the tab (a few
seconds on a busy gateway) and on `r`.

| Key | Action |
|---|---|
| `↑` `↓`, `j` `k` | Move |
| `Enter`, `Space` | Expand or collapse the highlighted group |
| `a` | Archive the highlighted session (asks first). Finished sessions are left alone |
| `w` | Cycle how many hours of finished sessions to show: open only, 6 h, 24 h |
| `r` | Reload |

### History

The [memory history](memory-history.md) chart for the last 1 h, 6 h, 24 h or 7 d (`h` cycles), with
the runs that were alive at the peak. It needs the sampler; without it the tab says so.

## Everywhere

| Key | Action |
|---|---|
| `p` | Pause or resume refreshing (the title bar shows `PAUSED`) |
| `r` | Refresh now |
| `+` `-` | Refresh faster or slower (0.5 s to 30 s) |
| `?` | Show the key list |
| `q` | Quit |
| `Ctrl+P` | Textual's command palette (themes and other app-wide commands) |

The footer lists only the keys that apply to the tab you are on.

## Try it without a gateway

`scripts/demo.py top` runs this exact screen on made-up data, with kills and archives simulated:

```sh
uv run python scripts/demo.py top
```

See [Try it without a gateway](../getting-started/try-without-a-gateway.md).

## Notes

- **Colour.** If `NO_COLOR` is set in your environment the screen is monochrome by design.
- **Refresh cost.** Each refresh reads `/proc` for your user's processes, a few milliseconds. Session
  data is only loaded while you are on the Sessions tab.
- **Unknown runtimes.** A run whose runtime has no activity source shows `-` for idle time and is never
  flagged `STALE`; use the age and memory columns to decide.
