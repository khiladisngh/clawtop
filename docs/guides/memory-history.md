# Keep a memory history

`clawtop history` draws gateway memory over time. It needs samples, which a small systemd user timer
records once a minute.

## Start sampling

```sh
clawtop sampler install
```

This writes `clawtop-sample.service` and `clawtop-sample.timer` to `~/.config/systemd/user/` and enables
the timer. Each run appends one JSON line to `~/.openclaw/logs/mem-samples.jsonl` (override with
`CLAWTOP_LOG`). The file rotates at 20 MB.

Stop and remove it:

```sh
clawtop sampler uninstall
```

## Read it

```sh
clawtop history --last 6h     # also 90m, 2d, ...
```

You get a sparkline of the gateway's memory, a swap line when swap was used, the minimum, current and
peak values with the time of the peak, and a table of the run stacks that were alive at the peak.

The table answers the question "what was running when it spiked?". Sparkline columns keep the **maximum**
of the samples they cover, so a short spike survives a long window.

## Notes

- One sample is about 300 bytes plus about 40 bytes per run, so a day is roughly 0.5 MB.
- Corrupt lines (for example from a torn write) are skipped.
- `--log PATH` reads a different file.
