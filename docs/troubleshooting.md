# Troubleshooting

## `gateway NOT RUNNING`

clawtop finds the gateway with `systemctl --user show <unit> -p MainPID`. Check that the unit exists and
runs as the same user that runs clawtop:

```sh
systemctl --user status openclaw-gateway
```

If your unit has another name (a profile, or a custom install), set `CLAWTOP_UNIT`. Over SSH or `su`,
the user manager may need `XDG_RUNTIME_DIR=/run/user/$(id -u)`; clawtop sets it when it is missing.

## No run stacks are listed

Check these in order:

1. **Does your runtime start a process per run?** Runtimes that run inside the gateway (`openclaw`,
   `codex`, `copilot`, `muse`) have no process of their own; their memory is in the gateway's `main`
   figure. Only CLI backends and ACP harnesses show up. See
   [Concepts](concepts.md#which-runtimes-does-clawtop-cover).
2. **Are the agent workspaces known?** clawtop recognises a run by its working directory. The status
   panel says so when it found no workspaces. Look at `agents.defaults.workspace` and
   `agents.entries.*.workspace` in `openclaw.json`, or set `CLAWTOP_WORKSPACES=/path/to/workspaces`.
3. **Is it really gateway-spawned?** `ps -eo pid,ppid,cmd` should show the run's process under the
   gateway. Processes you started from your own shell are deliberately ignored.
4. **Does the run use another working directory?** If a runtime launches its process outside the agent
   workspace, clawtop does not see it yet. Please open an issue with `ps -eo pid,ppid,cmd` for that run.

## `error: openclaw not found on PATH`

The `sessions` commands call the `openclaw` CLI. Make sure it is on `PATH` for the shell clawtop runs in.
On Windows the forwarded command uses a login shell (`bash -lc`), so your WSL profile's `PATH` applies.

## The sessions list looks too long

Archived sessions are filtered out using each agent's database. If clawtop cannot read it (permissions,
or the layout changed), it silently shows archived sessions as open. Compare with
`clawtop sessions list --all`, and check that `~/.openclaw/agents/*/agent/openclaw-agent.sqlite` is
readable by your user.

## `clawtop history` says there are no samples

Run `clawtop sampler install` and wait a few minutes. Check `systemctl --user list-timers
clawtop-sample.timer` and that `CLAWTOP_LOG` is the same for the timer and for your shell.

## Colours or boxes look wrong on Windows

Run clawtop inside WSL, or let the Windows `clawtop` forward to it. Rich uses a different console path on
Windows that does not behave when output is piped.

## `clawtop kill` says a PID is not a stack leader

Only the process at the top of a gateway-spawned stack can be named. Use the PID from the first column
of `clawtop status`, not a helper's PID.

## A killed run came back

Most likely the gateway started a new run for the same session or cron job. Killing a stack stops that
process only; it does not cancel the work. To stop the cause, archive the session or disable the cron job
in OpenClaw.
