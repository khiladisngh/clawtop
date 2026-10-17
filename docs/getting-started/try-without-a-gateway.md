# Try it without a gateway

You do not need OpenClaw to see what clawtop looks like. `scripts/demo.py` runs the **real** CLI against
made-up sample data: four agent runs, a few sessions with subagents, and six hours of memory history.
`kill` and `sessions archive` are simulated, so nothing is ever stopped or archived.

```sh
git clone https://github.com/khiladisngh/clawtop
cd clawtop
uv sync

uv run python scripts/demo.py                    # status overview
uv run python scripts/demo.py sessions tree
uv run python scripts/demo.py history --last 6h
uv run python scripts/demo.py sessions list --kind subagent --titles
```

The interactive picker needs answers; pass them in `CLAWTOP_DEMO_ANSWERS`, separated by `;`:

```sh
CLAWTOP_DEMO_ANSWERS="stale;y" uv run python scripts/demo.py kill
```

That answers the picker with `stale` and the confirmation with `y`, and echoes both as a terminal would.

!!! note
    On Windows, run it inside WSL. Rich's Windows console path does not emit ANSI colour when piped, so
    the output looks different there.
