# Walkthrough video

A 1 minute 43 second silent walkthrough: install from PyPI, then the interactive screen that plain
`clawtop` opens, end to end (dashboard, sort, filter, mark, kill, sessions, expanded panels, history, help),
and the one-shot status that scripts get instead.

<video controls preload="metadata" poster="../../assets/walkthrough/poster.jpg" width="100%">
  <source src="../assets/walkthrough/clawtop-walkthrough.mp4" type="video/mp4">
  Your browser cannot play this video.
  <a href="../assets/walkthrough/clawtop-walkthrough.mp4">Download the MP4</a>.
</video>

[Download the MP4](../assets/walkthrough/clawtop-walkthrough.mp4) (6.0 MB, 1920x1080, H.264, no audio).
The README and [The interactive screen](../guides/interactive-top.md) guide show a shorter animated tour of
the same screen as a GIF.

## Chapters

| Time | Scene |
|---|---|
| 0:00 | Title |
| 0:05 | `uv tool install clawtop` from PyPI, and the version |
| 0:12 | Plain `clawtop` opens the interactive screen |
| 0:14 | The dashboard: six panels, the focus border |
| 0:22 | Moving through the runs; the process tree follows |
| 0:27 | The sort menu (`s`) |
| 0:32 | Sorted by idle time |
| 0:36 | Filtering (`/`) |
| 0:41 | Marking runs (`space`, `A` for stale) |
| 0:47 | Killing: the confirmation dialog |
| 0:53 | After the kill: the runs are gone, the graph falls |
| 0:59 | The Sessions panel (`Tab` or `2`) |
| 1:04 | Expanding a panel (`e`, `Esc` to go back) |
| 1:09 | The memory graph, expanded |
| 1:16 | The History panel |
| 1:21 | The help screen |
| 1:26 | In a pipe or script: the one-shot status |
| 1:38 | End card |

## What to know

- **Real:** the install is the real `uv tool install clawtop` from PyPI, run into a throwaway directory
  on Linux (WSL), so nothing on the recording machine changed. Every screen after it is the installed
  `clawtop 0.5.0`: the dashboard, its panels, graph, menus and dialogs, and the `clawtop status` printout.
- **Sample data:** the processes, memory figures, session titles and the memory history are made up, so
  that no real session titles or IDs appear in a public video. The sample runs use three different
  programs (`claude`, `gemini`, `opencode`) to show that detection is not tied to one runtime. That is
  a demonstration of the display, not proof that those runtimes were tested: only Claude CLI has been
  verified on a real gateway (see [Concepts](../concepts.md#which-runtimes-does-clawtop-cover)). The data
  lives in [`scripts/demo.py`](https://github.com/khiladisngh/clawtop/blob/main/scripts/demo.py); you can
  run it yourself (see [Try it without a gateway](try-without-a-gateway.md)).
- **Simulated:** killing runs and archiving sessions. The demo removes them from its sample data so you
  can see the effect; nothing real is stopped or archived.
- **Composed for the video:** the typing animation, the line-by-line reveal of the install and status
  output, the crossfades, and the captions. The screen scenes are screenshots of the real screen after
  each key press, shown one after another rather than as a live recording.
- **Not shown:** the one-shot commands `kill`, `history`, `sessions` and `sampler`, and the `--json`
  output. They are covered in the [guides](../guides/interactive-top.md) and the
  [CLI reference](../reference/cli.md).
