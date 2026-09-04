# crook-dziling

A [Crook](https://github.com/theguriev/crook) plugin that plays a short sound when a command
finishes, so you can look away from a long build and still know when it is done.

That is the whole plugin. Six sounds, no network, no files, no telemetry. (*Dziling* is the Slavic
onomatopoeia for a small bell — the English *ding*.)

## What it needs

Crook with ABI 3 or later — the version that added `Capability::PlaySound` and the
`CommandFinished` event. Older builds will load the module, see an ABI they do not know, and say so
by name in the log rather than running it.

It also needs Crook's shell integration installed, because the signal it rings on is OSC 133 `D` —
the shell reporting that a command ended. Without it nothing ever finishes as far as Crook is
concerned, and the plugin stays silent. `crook --shell-integration` prints the snippet.

Finally it needs something on the machine that plays a wav: `pw-play`, `paplay`, `aplay`, `afplay`,
`play`, `ffplay` or `mpv`. Crook does not link an audio library — it has no build script and
requires no system library, deliberately — so it spawns whichever of those it finds.

## Install

```
mkdir -p ~/.local/share/crook/plugins/theguriev.dziling
curl -L -o ~/.local/share/crook/plugins/theguriev.dziling/plugin.wasm \
  https://github.com/theguriev/crook-dziling/releases/latest/download/plugin.wasm
```

Then restart Crook and allow it on the Plugins page. It asks for exactly two things:

| It wants to | Because |
| --- | --- |
| Know when a command finishes | That is what it rings on. It gets which pane, how it exited and how long it took — never the command line. |
| Play a sound | It hands Crook the audio; it never reaches a device itself. |

## The sounds

All six are in the module. Pick one from the command palette — every row below is an action named
`theguriev/dziling/<name>`, and choosing one plays it so you are picking by ear rather than by name.

| Name | Length | What it sounds like |
| --- | --- | --- |
| `dzin` **(default)** | 1.2 s | A small bright bell struck twice, warm and quick to fade |
| `microwave` | 1.0 s | Four flat piezo beeps announcing that your food is ready |
| `engine` | 1.9 s | A throttle blip on a four-cylinder petrol engine, idle to the limiter and back |
| `coin` | 0.4 s | The two-note chiptune bling of scooping up an arcade coin |
| `sonar` | 1.9 s | One sonar ping released into a very large room and left to fade |
| `typewriter` | 0.9 s | A typewriter's end-of-line bell, then the carriage rattling back to its stop |

Three more actions: `off` and `on` stop and start it ringing, and `test` plays the current sound
without waiting for a command.

## What it does not ring at

Anything that finished in under two seconds. Below that are the commands nobody is waiting on — a
`cd`, an `ls`, a `git status` — and a terminal that dinged at those would be unbearable within a
minute.

## Two things it cannot do yet

Being honest about these rather than letting you find them:

- **It forgets.** Which sound you chose, and whether you turned it off, last until you close the
  window. Crook's ABI has a `Storage` capability but no request that reaches it, so there is
  nowhere to write the choice down. When there is, this will use it.
- **The volume is fixed** at 70%, for the same reason.

## How the sounds were made

Every sound is synthesised from scratch by a Python module in `tools/voices/`, using the dependency-
free DSP toolkit in `tools/dsp.py` — oscillators, envelopes, biquads, a Schroeder reverb, a
Karplus-Strong string. No samples, no sample packs, no downloads, no numpy. `dzin` is an additive
bell with inharmonic partials over a Chowning FM clang; `coin` models the NES's 2A03 pulse channels
down to the 4-bit volume register. Each module's docstring says why it sounds the way it does.

The six are matched to each other on ITU-R BS.1770 loudness rather than on peak, so switching
sounds does not change how loud the plugin is — a flat beep and a typewriter click with identical
peaks measure 9.5 dB apart on a K-weighted meter.

The wavs are committed and CI fails if they are not byte-for-byte what the source produces:

```sh
python3 tools/generate_sounds.py
```

`tools/analyze.py` prints duration, peak, DC offset, clipping, loudness, an RMS envelope and the
strongest partials per slice, which is how a sound is checked without listening to it forty times.

## Building it

```sh
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
```

The module lands at `target/wasm32-unknown-unknown/release/crook_dziling.wasm`. It is about 670 KB,
of which 652 KB is the six sounds.

## Sibling

[`theguriev/dziling`](https://github.com/theguriev/dziling) is the same idea for Claude Code — a
plugin that rings when the agent finishes a turn, in any terminal. It shares these sounds and their
synthesis. This one is for Crook, and rings on commands rather than on turns.

## License

MIT. See [LICENSE](LICENSE).
