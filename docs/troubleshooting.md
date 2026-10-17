# Troubleshooting

## `gateway NOT RUNNING`, or no run stacks listed

clawtop finds the gateway with `systemctl --user show openclaw-gateway -p MainPID`. Check that the unit
exists and runs as the same user that runs clawtop:

```sh
systemctl --user status openclaw-gateway
```

Over SSH or `su`, the user manager may need `XDG_RUNTIME_DIR=/run/user/$(id -u)`; clawtop sets it when it
is missing.

## `error: `openclaw` not found on PATH`

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

Only the `claude` process at the top of a gateway-spawned stack can be named. Use the PID from the first
column of `clawtop status`, not a helper's PID.

## A killed run came back

Most likely the gateway started a new run for the same session or cron job. Killing a stack stops that
process only; it does not cancel the work. To stop the cause, archive the session or disable the cron job
in OpenClaw.
