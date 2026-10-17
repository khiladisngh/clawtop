# Stop runaway runs

`clawtop kill` stops whole **run stacks**: the `claude` process and all its MCP helpers together.

## Pick interactively

```sh
clawtop kill
```

It lists the runs with numbers. Answer with row numbers (`1 3`), `stale`, or `all`. Press Enter to
cancel. It then shows what will be killed and how much memory that frees, and asks for confirmation.

## Pick by rule

```sh
clawtop kill 4102 2211          # specific stacks, by the PID in the table
clawtop kill --idle 30          # no transcript activity for 30 minutes
clawtop kill --older-than 120   # runs older than 2 hours
clawtop kill --orphans          # gateway-spawned stacks whose parent is gone
```

Options combine: a stack matching any selector is included.

| Option | Effect |
|---|---|
| `--dry-run` | Show the selection and stop |
| `--yes`, `-y` | Skip the confirmation |
| `--grace SECONDS` | Wait this long after SIGTERM before SIGKILL (default 5) |

The exit code is non-zero if any process survived.

## What makes it safe

- **Only gateway-spawned processes can be selected.** A process counts only if it runs in a gateway
  workspace directory, or was started with the gateway's temporary MCP config. Your own `claude` or `npx`
  sessions are never listed. See [what counts as a gateway run](../concepts.md#what-counts-as-a-gateway-run).
- **Whole stacks die together:** SIGTERM first, then SIGKILL for survivors. No half-dead MCP helpers are
  left holding memory.
- **PID reuse is guarded.** The command line of every process is re-checked just before it is signalled.
  If the PID now belongs to a different program, it is skipped.

## What happens to the session

Killing a stack stops the process. The gateway will see the run end; clawtop does not edit the session
itself. To close sessions afterwards, use [`sessions prune`](manage-sessions.md).

!!! warning
    You cannot tell from the table which Discord channel or cron job a run belongs to. clawtop shows the
    agent and the CLI session id. Use `IDLE` and `CTX` (transcript size) to decide. Runs that are working
    right now show a small `IDLE`.
