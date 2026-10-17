# Manage sessions

clawtop reads sessions through `openclaw sessions` (the supported gateway interface) and closes them with
`openclaw sessions archive`.

## List

```sh
clawtop sessions list                         # open sessions, longest idle first
clawtop sessions list --titles                # add the session title column
clawtop sessions list --kind subagent --idle-min 60
clawtop sessions list --agent builder --kind cron
clawtop sessions list --all                   # include finished and archived
```

Kinds are `subagent`, `cron`, `discord`, `main` and `node`. "Open" means not `done`, `failed`, `killed`,
`timeout` or archived.

## Tree: subagents under their parent

```sh
clawtop sessions tree
```

Sessions are grouped by agent. A subagent appears under the session that spawned it, with its title.

```text
builder
└── main  20s idle  188,000 tok
    ├── subagent Investigate flaky upload test  14h00m idle
    ├── subagent Draft release notes for v2.4  40m idle  120,000 tok  [done]
    ├── subagent Triage failing tests in CI  17m idle  120,000 tok  [done]
    └── subagent Refactor billing module  3m idle
```

Subagents usually finish within minutes, so the tree also shows sessions that finished in the last
6 hours, tagged `[done]`. Change that window with `--within HOURS`; `--within 0` shows open sessions
only. `--all` shows everything (hundreds of rows on a busy gateway). A dimmed row marked `(parent)` is
shown only to give a finished parent's children a place to hang.

Only subagent sessions have parents. Cron, Discord and node sessions are always top-level.

## Archive

```sh
clawtop sessions archive agent:builder:subagent:<uuid> --dry-run
clawtop sessions archive agent:builder:subagent:<uuid> agent:researcher:subagent:<uuid> --yes
```

## Prune idle sessions

```sh
clawtop sessions prune --dry-run              # open subagents idle for 6+ hours
clawtop sessions prune --idle-hours 12 --yes
```

`prune` selects **open subagent sessions** only. Channel and main sessions hold conversation context, so
they are never selected unless you ask:

```sh
clawtop sessions prune --kind cron --idle-hours 168 --dry-run
```

!!! note "Archived sessions"
    `openclaw sessions --json` does not say whether a session is archived: an archived session keeps its
    old status. clawtop reads the flag from each agent's database, read-only (`session_nodes.archived_at`
    in `~/.openclaw/agents/*/agent/openclaw-agent.sqlite`). If that database layout changes, clawtop
    falls back to treating nothing as archived instead of failing.
