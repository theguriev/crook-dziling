"""Tiny dependency-free DSP toolkit used to synthesise dziling's sounds.

Everything is a plain Python ``list`` of floats in roughly [-1, 1] at ``SR``.
No numpy, no scipy, no sample packs -- every sound in ``sounds/`` is generated
from these primitives by ``tools/generate_sounds.py`` so the whole set is
reproducible and unambiguously ours to publish.

``master`` is the output stage every shipped sound goes through; both drivers
call it, so a voice previewed with ``render_one.py`` is byte-identical to the
one CI regenerates.

``pad``, ``triangle``, ``adsr`` and ``karplus`` are toolkit surface for
contributed voices on purpose -- none of the six shipped ones uses them.
"""

import math
import struct
import wave

SR = 44100
TWO_PI = 2.0 * math.pi


# --------------------------------------------------------------------------
# buffers
# --------------------------------------------------------------------------

def frames(dur):
    return max(0, int(round(dur * SR)))


def silence(dur):
    return [0.0] * frames(dur)


def add_at(buf, sig, t):
    """Mix ``sig`` into ``buf`` starting at time ``t`` (seconds), growing buf."""
    start = frames(t)
    need = start + len(sig)
    if need > len(buf):
        buf.extend([0.0] * (need - len(buf)))
    for i, v in enumerate(sig):
        buf[start + i] += v
    return buf


def mix(*sigs):
    out = []
    for s in sigs:
        if len(s) > len(out):
            out.extend([0.0] * (len(s) - len(out)))
        for i, v in enumerate(s):
            out[i] += v
    return out


def gain(sig, g):
    return [v * g for v in sig]


def mul(a, b):
    n = min(len(a), len(b))
    return [a[i] * b[i] for i in range(n)]


def concat(*sigs):
    out = []
    for s in sigs:
        out.extend(s)
    return out


def pad(sig, dur):
    """Right-pad to at least ``dur`` seconds (room for tails to ring out)."""
    n = frames(dur)
    if len(sig) < n:
        sig = sig + [0.0] * (n - len(sig))
    return sig


# --------------------------------------------------------------------------
# oscillators -- ``freq`` may be a number or a callable f(t) for sweeps
# --------------------------------------------------------------------------

def _freq_at(freq, t):
    return freq(t) if callable(freq) else freq


def _phase_ramp(freq, dur):
    """Integrate frequency into phase so sweeps stay click-free."""
    n = frames(dur)
    out = [0.0] * n
    ph = 0.0
    dt = 1.0 / SR
    for i in range(n):
        out[i] = ph
        ph += TWO_PI * _freq_at(freq, i * dt) * dt
        if ph > TWO_PI:
            ph -= TWO_PI
    return out


def sine(freq, dur, phase=0.0):
    return [math.sin(p + phase) for p in _phase_ramp(freq, dur)]


def triangle(freq, dur):
    out = []
    for p in _phase_ramp(freq, dur):
        x = p / TWO_PI
        out.append(4.0 * abs(x - 0.5) - 1.0)
    return out


def saw(freq, dur):
    return [2.0 * (p / TWO_PI) - 1.0 for p in _phase_ramp(freq, dur)]


def square(freq, dur, duty=0.5):
    return [1.0 if (p / TWO_PI) < duty else -1.0 for p in _phase_ramp(freq, dur)]


def pulse_train(freq, dur, width=0.06):
    """Narrow impulses -- the raw material for engine exhaust pulses."""
    out = []
    for p in _phase_ramp(freq, dur):
        x = p / TWO_PI
        out.append(math.exp(-((x / width) ** 2)) - 0.15)
    return out


def fm(carrier, ratio, index, dur):
    """Classic 2-operator FM -- ``index`` may be a callable f(t)."""
    n = frames(dur)
    out = [0.0] * n
    cph = mph = 0.0
    dt = 1.0 / SR
    for i in range(n):
        t = i * dt
        c = _freq_at(carrier, t)
        idx = _freq_at(index, t)
        out[i] = math.sin(cph + idx * math.sin(mph))
        cph += TWO_PI * c * dt
        mph += TWO_PI * c * ratio * dt
    return out


class Noise:
    """Deterministic white noise (a plain LCG, so builds are reproducible)."""

    def __init__(self, seed=1):
        self.state = (seed * 2654435761 + 1) & 0xFFFFFFFF

    def next(self):
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return (self.state / 2147483648.0) - 1.0

    def buffer(self, dur):
        return [self.next() for _ in range(frames(dur))]


def noise(dur, seed=1):
    return Noise(seed).buffer(dur)


# --------------------------------------------------------------------------
# envelopes
# --------------------------------------------------------------------------

def env_from(points):
    """Piecewise-linear envelope from [(time, level), ...] (times ascending)."""
    if len(points) < 2:
        raise ValueError("env_from needs at least two points, got %d" % len(points))
    total = points[-1][0]
    n = frames(total)
    out = [0.0] * n
    seg = 0
    for i in range(n):
        t = i / SR
        while seg < len(points) - 2 and t >= points[seg + 1][0]:
            seg += 1
        t0, v0 = points[seg]
        t1, v1 = points[seg + 1]
        span = t1 - t0
        k = 0.0 if span <= 0 else (t - t0) / span
        out[i] = v0 + (v1 - v0) * max(0.0, min(1.0, k))
    return out


def perc(dur, attack=0.004, tau=0.12, curve=1.0):
    """Percussive envelope: quick attack, exponential decay."""
    n = frames(dur)
    a = max(1, frames(attack))
    out = [0.0] * n
    for i in range(n):
        rise = min(1.0, i / a)
        decay = math.exp(-((i - a) / SR) / tau) if i > a else 1.0
        out[i] = (rise ** curve) * decay
    return out


def adsr(dur, a=0.01, d=0.05, s=0.7, r=0.1):
    n = frames(dur)
    out = [0.0] * n
    na, nd, nr = frames(a), frames(d), frames(r)
    ns = max(0, n - na - nd - nr)
    i = 0
    for k in range(na):
        if i < n:
            out[i] = k / max(1, na)
            i += 1
    for k in range(nd):
        if i < n:
            out[i] = 1.0 + (s - 1.0) * (k / max(1, nd))
            i += 1
    for _ in range(ns):
        if i < n:
            out[i] = s
            i += 1
    for k in range(nr):
        if i < n:
            out[i] = s * (1.0 - k / max(1, nr))
            i += 1
    return out


def fade(sig, fade_in=0.003, fade_out=0.01):
    """Taper both edges so nothing clicks on playback."""
    n = len(sig)
    fi, fo = frames(fade_in), frames(fade_out)
    for i in range(min(fi, n)):
        sig[i] *= i / max(1, fi)
    for i in range(min(fo, n)):
        sig[n - 1 - i] *= i / max(1, fo)
    return sig


# --------------------------------------------------------------------------
# filters & effects
# --------------------------------------------------------------------------

def lowpass1(sig, cutoff):
    """One-pole lowpass; ``cutoff`` may be a callable f(t) for sweeps."""
    out = [0.0] * len(sig)
    y = 0.0
    for i, x in enumerate(sig):
        fc = _freq_at(cutoff, i / SR)
        a = 1.0 - math.exp(-TWO_PI * max(1.0, fc) / SR)
        y += a * (x - y)
        out[i] = y
    return out


def highpass1(sig, cutoff):
    """One-pole highpass (the complement of lowpass1); ``cutoff`` may be f(t)."""
    out = [0.0] * len(sig)
    y = 0.0
    for i, x in enumerate(sig):
        fc = _freq_at(cutoff, i / SR)
        a = 1.0 - math.exp(-TWO_PI * max(1.0, fc) / SR)
        y += a * (x - y)
        out[i] = x - y
    return out


def biquad(sig, kind, freq, q=0.707):
    """Direct-form-II biquad; ``freq`` may be a callable f(t)."""
    out = [0.0] * len(sig)
    z1 = z2 = 0.0
    for i, x in enumerate(sig):
        f = max(20.0, min(SR * 0.45, _freq_at(freq, i / SR)))
        w = TWO_PI * f / SR
        alpha = math.sin(w) / (2.0 * q)
        cw = math.cos(w)
        if kind == "lp":
            b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
        elif kind == "hp":
            b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
        elif kind == "bp":
            b0, b1, b2 = alpha, 0.0, -alpha
        else:
            raise ValueError(kind)
        a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
        y = (b0 / a0) * x + z1
        z1 = (b1 / a0) * x - (a1 / a0) * y + z2
        z2 = (b2 / a0) * x - (a2 / a0) * y
        out[i] = y
    return out


def delay(sig, time, feedback=0.35, wet=0.3, tail=0.0):
    d = frames(time)
    if d <= 0:
        return list(sig)
    buf = list(sig) + [0.0] * frames(tail)
    out = list(buf)
    for i in range(d, len(buf)):
        out[i] += wet * out[i - d] * feedback + wet * buf[i - d] * (1 - feedback)
    return out


def reverb(sig, room=0.72, wet=0.22, tail=1.2):
    """Small Schroeder reverb -- four combs into two allpasses."""
    src = list(sig) + [0.0] * frames(tail)
    n = len(src)
    combs = [(1687, room), (1601, room * 0.98), (2053, room * 0.96), (2251, room * 0.94)]
    acc = [0.0] * n
    for size, fb in combs:
        buf = [0.0] * size
        idx = 0
        for i in range(n):
            v = buf[idx]
            acc[i] += v
            buf[idx] = src[i] + v * fb
            idx = (idx + 1) % size
    acc = [v * 0.25 for v in acc]
    for size, fb in ((225, 0.5), (556, 0.5)):
        buf = [0.0] * size
        idx = 0
        for i in range(n):
            v = buf[idx]
            y = -acc[i] + v
            buf[idx] = acc[i] + v * fb
            acc[i] = y
            idx = (idx + 1) % size
    return [src[i] * (1 - wet) + acc[i] * wet for i in range(n)]


def karplus(freq, dur, damping=0.5, seed=7, decay=0.996):
    """Plucked string -- a short noise burst run through a damped delay line."""
    n = frames(dur)
    if freq <= 0.0:
        raise ValueError("karplus needs a positive frequency, got %r" % (freq,))
    size = max(2, int(SR / freq))
    rng = Noise(seed)
    buf = [rng.next() for _ in range(size)]
    out = [0.0] * n
    idx = 0
    prev = 0.0
    for i in range(n):
        cur = buf[idx]
        avg = damping * cur + (1.0 - damping) * prev
        prev = cur
        buf[idx] = avg * decay
        out[i] = cur
        idx = (idx + 1) % size
    return out


def soft_clip(sig, drive=1.0):
    return [math.tanh(v * drive) for v in sig]


def normalize(sig, peak=0.89):
    m = max((abs(v) for v in sig), default=0.0)
    if m <= 1e-9:
        return list(sig)
    k = peak / m
    return [v * k for v in sig]


def trim_tail(sig, threshold=1e-4, keep=0.05):
    """Drop trailing near-silence so files stay small."""
    end = len(sig)
    while end > 1 and abs(sig[end - 1]) < threshold:
        end -= 1
    return sig[: min(len(sig), end + frames(keep))]


# --------------------------------------------------------------------------
# loudness
#
# Peak is not loudness.  Six sounds all normalised to the same peak differ by
# more than 12 dB to the ear, because a square-wave beep has a crest factor of
# 5 dB and a typewriter click has one of 20 dB.  A user who switches sounds at
# a fixed VOLUME should not have the level jump, so the master chain matches
# every voice to one K-weighted loudness instead of one peak.
#
# The weighting is ITU-R BS.1770-4: a +4 dB high shelf standing in for the head
# and torso, then a highpass that discounts sub-bass the way the ear does.  The
# integration window is deliberately shorter than the broadcast standard's
# 400 ms.  These are single events of a third of a second to two seconds, and
# 400 ms smears a click's loudness across four times its own duration; 200 ms
# is close to the ear's own integration time for short bursts and ranks this
# set the way listening does.
# --------------------------------------------------------------------------

LOUDNESS_WINDOW = 0.200
LOUDNESS_HOP = 0.025
LOUDNESS_TARGET = -12.5     # LUFS, the level every shipped sound is matched to


def _fixed_biquad(sig, b, a):
    """Direct-form-I biquad with constant coefficients (a[0] is 1)."""
    b0, b1, b2 = b
    a1, a2 = a
    x1 = x2 = y1 = y2 = 0.0
    out = [0.0] * len(sig)
    for i, x in enumerate(sig):
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[i] = y
        x2, x1 = x1, x
        y2, y1 = y1, y
    return out


def k_weight(sig, sr=SR):
    """The two BS.1770-4 pre-filters, derived for ``sr`` rather than hardcoded."""
    f0, gain_db, q = 1681.9744509555319, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / sr)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh ** 0.4996667741545416
    den = 1.0 + k / q + k * k
    shelf_b = ((vh + vb * k / q + k * k) / den,
               2.0 * (k * k - vh) / den,
               (vh - vb * k / q + k * k) / den)
    shelf_a = (2.0 * (k * k - 1.0) / den, (1.0 - k / q + k * k) / den)

    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sr)
    den = 1.0 + k / q + k * k
    hp_a = (2.0 * (k * k - 1.0) / den, (1.0 - k / q + k * k) / den)

    return _fixed_biquad(_fixed_biquad(sig, shelf_b, shelf_a), (1.0, -2.0, 1.0), hp_a)


def loudness(sig, window=LOUDNESS_WINDOW, hop=LOUDNESS_HOP):
    """Loudest K-weighted block, in LUFS.  ``-inf`` for silence.

    Quantised to 0.01 dB: the result drives a gain that ends up in a committed
    file, and CI checks those files byte for byte, so it must not wobble with
    the last bit of a libm ``tan`` on a different machine.
    """
    kw = k_weight(sig)
    n, step = frames(window), max(1, frames(hop))
    starts = range(0, max(1, len(kw) - n + 1), step) if len(kw) >= n else [0]
    best = 0.0
    for start in starts:
        blk = kw[start:start + n]
        if blk:
            best = max(best, sum(v * v for v in blk) / len(blk))
    if best <= 0.0:
        return float("-inf")
    return round(-0.691 + 10.0 * math.log10(best), 2)


def match_loudness(sig, target=LOUDNESS_TARGET, ceiling=0.89):
    """Scale ``sig`` to ``target`` LUFS, never pushing its peak past ``ceiling``."""
    measured = loudness(sig)
    if measured == float("-inf"):
        return list(sig)
    k = 10.0 ** ((target - measured) / 20.0)
    m = max((abs(v) for v in sig), default=0.0)
    if m * k > ceiling:
        k = ceiling / m
    return [v * k for v in sig]


def master(sig, target=LOUDNESS_TARGET, peak=0.89):
    """The output stage every shipped sound goes through, in one place.

    Trim the dead tail, taper both edges, peak-normalise for a known ceiling,
    then match the loudness.  ``render_one.py`` and ``generate_sounds.py`` both
    call this, so a voice previewed on its own is byte-identical to the one CI
    regenerates.
    """
    return match_loudness(normalize(fade(trim_tail(list(sig))), peak), target, peak)


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def write_wav(path, sig, sr=SR):
    """16-bit mono PCM -- the one format every player on every OS accepts."""
    data = bytearray()
    for v in sig:
        s = int(round(max(-1.0, min(1.0, v)) * 32767.0))
        data += struct.pack("<h", s)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(data))
    return len(sig) / float(sr)
