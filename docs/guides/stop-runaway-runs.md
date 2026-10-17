# Stop runaway runs

`clawtop kill` stops whole **run stacks**: an agent run's process and everything it started (MCP servers,
helpers), together.

## Pick interactively

```sh
clawtop kill
```

It lists the runs with numbers. Answer with row numbers (`1 3`), `stale`, or `all`. Press Enter to
cancel. It then shows what will be killed and how much memory that frees, and asks for confirmation.

## Pick by rule

```sh
clawtop kill 4102 2211          # specific stacks, by the PID in the table
clawtop kill --idle 30          # no transcript activity for 30 minutes (runtimes with a transcript)
clawtop kill --older-than 120   # runs older than 2 hours (any runtime)
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

- **Only gateway-spawned processes can be selected.** A process counts only if it is in the gateway's
  process tree (or carries OpenClaw's gateway markers in its environment) and runs in an agent workspace.
  A `claude`, `gemini` or `npx` you started from your own shell is never listed. See
  [what counts as a gateway run](../concepts.md#what-counts-as-a-gateway-run).
- **Whole stacks die together:** SIGTERM first, then SIGKILL for survivors. No half-dead MCP helpers are
  left holding memory.
- **PID reuse is guarded.** The command line of every process is re-checked just before it is signalled.
  If the PID now belongs to a different program, it is skipped.

## What happens to the session

Killing a stack stops the process. The gateway will see the run end; clawtop does not edit the session
itself. To close sessions afterwards, use [`sessions prune`](manage-sessions.md).

!!! warning
    You cannot tell from the table which Discord channel or cron job a run belongs to. clawtop shows the
    runtime and the agent. Use `IDLE` and `CTX` (transcript size) where they are available. Runs that are
    working right now show a small `IDLE`. For a runtime with no activity source `IDLE` is `-`, so check
    `AGE` and `MEM` and use `--older-than` or name the PID.
