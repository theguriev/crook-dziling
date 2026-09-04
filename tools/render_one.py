#!/usr/bin/env python3
"""Render a single voice module to sounds/<name>.wav (no manifest rewrite).

    python3 tools/render_one.py microwave

Handy while iterating on one voice; ``tools/generate_sounds.py`` does the whole
set plus the manifest.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dsp  # noqa: E402


def main(argv):
    if len(argv) != 2:
        raise SystemExit("usage: render_one.py <voice-name>")
    name = argv[1]
    path = os.path.join(HERE, "voices", name + ".py")
    spec = importlib.util.spec_from_file_location("voice_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sig = dsp.master(mod.render())
    os.makedirs(os.path.join(ROOT, "sounds"), exist_ok=True)
    out = os.path.join(ROOT, "sounds", name + ".wav")
    secs = dsp.write_wav(out, sig)
    print("%s  %.3fs  %.1f KiB  peak %.3f  %.2f LUFS"
          % (out, secs, os.path.getsize(out) / 1024.0,
             max(abs(v) for v in sig), dsp.loudness(sig)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
