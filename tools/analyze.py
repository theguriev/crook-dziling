#!/usr/bin/env python3
"""Inspect a rendered WAV without listening to it.

Prints duration, peak, DC offset, clipping, K-weighted loudness, an RMS
envelope in 25 ms slices and the strongest spectral peaks per slice (naive DFT
-- slow but dependency-free).  Use it to check that a voice actually does what
its docstring claims.
"""

import math
import os
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp  # noqa: E402


def read(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise SystemExit("expected 16-bit mono")
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    n = len(raw) // 2
    out = [0.0] * n
    for i in range(n):
        lo = raw[2 * i]
        hi = raw[2 * i + 1]
        v = lo | (hi << 8)
        if v >= 32768:
            v -= 65536
        out[i] = v / 32768.0
    return sr, out


def peaks(chunk, sr, lo=60.0, hi=9000.0, want=3, bins=420):
    """Log-spaced Goertzel sweep -- returns the loudest (freq, magnitude) pairs."""
    n = len(chunk)
    if n < 64:
        return []
    res = []
    for b in range(bins):
        f = lo * (hi / lo) ** (b / (bins - 1.0))
        w = 2.0 * math.pi * f / sr
        cw = 2.0 * math.cos(w)
        s1 = s2 = 0.0
        for x in chunk:
            s0 = x + cw * s1 - s2
            s2, s1 = s1, s0
        mag = math.sqrt(max(0.0, s1 * s1 + s2 * s2 - cw * s1 * s2)) / n
        res.append((mag, f))
    res.sort(reverse=True)
    picked = []
    for mag, f in res:
        if all(abs(math.log(f / g)) > 0.08 for _, g in picked):
            picked.append((mag, f))
        if len(picked) >= want:
            break
    return [(f, m) for m, f in picked]


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: analyze.py <file.wav> [slice_ms]")
    step_ms = float(argv[2]) if len(argv) > 2 else 25.0
    sr, sig = read(argv[1])
    n = len(sig)
    pk = max((abs(v) for v in sig), default=0.0)
    dc = sum(sig) / max(1, n)
    clipped = sum(1 for v in sig if abs(v) >= 0.999)
    print("file      %s" % argv[1])
    print("rate      %d Hz  frames %d  duration %.3f s" % (sr, n, n / float(sr)))
    print("peak      %.4f   dc %+.5f   clipped %d" % (pk, dc, clipped))
    print("loudness  %.2f LUFS  (loudest %d ms, K-weighted; the set is matched to %.1f)"
          % (dsp.loudness(sig), dsp.LOUDNESS_WINDOW * 1000, dsp.LOUDNESS_TARGET))
    step = int(sr * step_ms / 1000.0)
    print("\n  t(s)   rms    bar                          top partials (Hz)")
    for start in range(0, n, step):
        chunk = sig[start : start + step]
        if not chunk:
            break
        rms = math.sqrt(sum(v * v for v in chunk) / len(chunk))
        db = 20 * math.log10(rms + 1e-9)
        bar = "#" * max(0, min(26, int((db + 60) / 60 * 26)))
        tops = ""
        if rms > 0.011 * pk:
            tops = "  ".join("%6.0f(%.3f)" % (f, m) for f, m in peaks(chunk, sr))
        print("%6.3f  %.4f %-26s %s" % (start / float(sr), rms, bar, tops))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
