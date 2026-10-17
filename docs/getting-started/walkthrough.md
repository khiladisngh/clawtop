# Walkthrough video

A 1 minute 38 second silent walkthrough: install from PyPI, the one-shot overview, then the interactive
`clawtop top` screen from end to end (sort, filter, mark, kill, sessions, archive, history, help).

<video controls preload="metadata" poster="../../assets/walkthrough/poster.jpg" width="100%">
  <source src="../assets/walkthrough/clawtop-walkthrough.mp4" type="video/mp4">
  Your browser cannot play this video.
  <a href="../assets/walkthrough/clawtop-walkthrough.mp4">Download the MP4</a>.
</video>

[Download the MP4](../assets/walkthrough/clawtop-walkthrough.mp4) (5.2 MB, 1920x1080, H.264, no audio).
The README and the [Interactive view](../guides/interactive-top.md) guide show a shorter animated tour of
the same screen as a GIF.

## Chapters

| Time | Scene |
|---|---|
| 0:00 | Title |
| 0:05 | `uv tool install clawtop` from PyPI, and the version |
| 0:12 | `clawtop`: the one-shot overview |
| 0:25 | `clawtop top` starts the interactive screen |
| 0:27 | The live view: memory meters, the gateway graph, one row per run |
| 0:33 | The process tree of the highlighted run |
| 0:38 | Sorting (`s`, `i`, click a header) |
| 0:43 | Filtering (`/`) |
| 0:48 | Marking runs (`space`, `A` for stale) |
| 0:53 | Killing: the confirmation dialog |
| 0:59 | After the kill: the runs are gone and the meters drop |
| 1:05 | The Sessions tab: subagents under their parent |
| 1:11 | Archiving a session |
| 1:21 | The History tab |
| 1:27 | The help screen |
| 1:33 | End card |

## What to know

- **Real:** the install is the real `uv tool install clawtop` from PyPI, run into a throwaway directory
  on Linux (WSL), so nothing on the recording machine changed. Every screen after it is the installed
  `clawtop 0.4.0`: the commands, colours, tables, meters and the `clawtop top` interface itself.
- **Sample data:** the processes, memory figures, session titles and the memory history are made up, so
  that no real session titles or IDs appear in a public video. The sample runs use three different
  programs (`claude`, `gemini`, `opencode`) to show that detection is not tied to one runtime. That is
  a demonstration of the display, not proof that those runtimes were tested: only Claude CLI has been
  verified on a real gateway (see [Concepts](../concepts.md#which-runtimes-does-clawtop-cover)). The data
  lives in [`scripts/demo.py`](https://github.com/khiladisngh/clawtop/blob/main/scripts/demo.py); you can
  run it yourself (see [Try it without a gateway](try-without-a-gateway.md)).
- **Simulated:** killing runs and archiving sessions. The demo removes them from its sample data so you
  can see the effect; nothing real is stopped or archived.
- **Composed for the video:** the typing animation, the line-by-line reveal of the install and overview
  output, the crossfades, and the captions. The `clawtop top` scenes are screenshots of the real screen
  after each key press, shown one after another rather than as a live recording.
- **Not shown:** the one-shot commands `kill`, `history`, `sessions` and `sampler`, and the `--json`
  output. They are covered in the [guides](../guides/interactive-top.md) and the
  [CLI reference](../reference/cli.md).
