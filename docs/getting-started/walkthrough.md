# Walkthrough video

A 1 minute 43 second silent walkthrough: install, the overview, stopping runaway runs, the memory
history, and the session tree.

<video controls preload="metadata" poster="../../assets/walkthrough/poster.jpg" width="100%">
  <source src="../assets/walkthrough/clawtop-walkthrough.mp4" type="video/mp4">
  Your browser cannot play this video.
  <a href="../assets/walkthrough/clawtop-walkthrough.mp4">Download the MP4</a>.
</video>

[Download the MP4](../assets/walkthrough/clawtop-walkthrough.mp4) (2.5 MB, 1920x1080, H.264, no audio).

## Chapters

| Time | Scene |
|---|---|
| 0:00 | Title |
| 0:05 | Install with `uv` and check the version |
| 0:12 | `clawtop --help` |
| 0:21 | `clawtop`: memory bars and the table of agent runs |
| 0:36 | `clawtop kill`: the interactive picker |
| 0:49 | `clawtop history --last 6h` |
| 1:03 | `clawtop sessions list --titles` |
| 1:13 | `clawtop sessions tree` |
| 1:27 | `clawtop sessions prune` |
| 1:38 | End card |

## What to know

- **Real:** every command, every line of output and the colours come from `clawtop 0.2.3`, installed
  from GitHub into a throwaway directory on Linux (WSL). The install, the version and the help text are
  unedited captures.
- **Sample data:** the processes, memory figures, session titles and the memory history are made up, so
  that no real session titles or IDs appear in a public video. The data lives in
  [`scripts/demo.py`](https://github.com/khiladisngh/clawtop/blob/main/scripts/demo.py); you can run it
  yourself (see [Try it without a gateway](try-without-a-gateway.md)).
- **Simulated:** killing runs and archiving sessions. Nothing real is stopped or archived.
- **Composed for the video:** the typing animation, the line-by-line reveal of each output, and the
  crossfades between scenes. The captions are added too.
- **Not shown:** `watch` (a live, repainting view), `sampler install`, and the `--json` output.
