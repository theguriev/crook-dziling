"""dzin -- the small bright bell the plugin is named after.

Acoustic model
--------------
A struck bell is a *plate* ringing in several modes at once, so its partials sit
at inharmonic ratios of the strike tone instead of on a harmonic series.  The
ratios are the classic small-bell set:

    0.50  hum      an octave below the strike tone -- what makes a bell warm
    1.00  prime    the pitch you name the bell after
    2.01  nominal  nominally the octave; real bells land a few cents off it
    2.40  tierce   an octave plus a minor third -- the partial that says "bell"
    3.02  quint
    4.20  }        upper plate modes: brief, and what makes the strike sparkle
    5.40  }

Three physical facts drive the rest of the patch.

1.  Radiation losses grow with frequency, so high modes die sooner than low
    ones.  Each partial therefore gets its own ``dsp.perc`` with its own time
    constant -- the ``decay`` column of ``PARTIALS``, a multiple of the note's
    ``tau0``.  The prime rings for ~0.38 s, the quint decays 4.5x quicker and the
    5.4 mode 15x quicker, both measured against the prime -- 9 dB down 25 ms in.
    That spread is the single strongest cue that the listener heard struck metal
    and not a beep.

    The column is not a power law in frequency, and the tierce deliberately
    outlives the nominal below it.  Both choices come from the same trap.  A
    power law steep enough to clear the upper modes in tens of milliseconds also
    kills the tierce by ~0.12 s, and once the tierce is gone the only partials
    still ringing are 0.5 / 1.0 / 2.0 -- exact octaves, which the ear fuses into
    a single harmonic tone.  Two thirds of the sound is then the sine beep the
    inharmonicity exists to avoid.  Measured bells do not behave that way
    either: hum, prime, tierce and nominal all have decay times of the same
    order, with the sharp fall-off starting above the quint.  Here the tierce
    and nominal sit together at ~0.55 x tau0, which keeps a minor third in the
    tail from end to end -- audible at -18 dB under the prime at 0.30 s where
    the power law had it at -27 dB.

2.  The instant of impact is broadband and very short: a mallet in contact for a
    few milliseconds.  That is ``_mallet`` -- noise band-passed high (4.3 kHz
    body, 6.3 kHz edge) with a 5 ms time constant, so it is over before the bell
    has finished speaking.  It is deliberately not loud: the bell's own 4.2 mode
    already fills 4-7 kHz for the first 100 ms, so the click's job is to sharpen
    the first 2 ms (it lifts them 3 dB) rather than to be heard as a knock.

3.  Real strikes are not perfectly axial, so the two halves of a mode split by a
    fraction of a hertz and beat slowly.  The prime is doubled BEAT_HZ above
    itself for that living, non-electronic shimmer -- shallowly, see _strike().

On top of the additive skeleton sits one 2-operator FM voice at a 1:1.41
carrier:modulator ratio (Chowning's bell ratio) with a fast-decaying index,
which fills in the dense inharmonic clang of the first few tens of milliseconds
without any single partial having to be loud.

Two strikes: C6, then G6 a perfect fifth above 125 ms later at 60% of the body
level.  The second bell is smaller but takes the same mallet, so its click lands
at 80% of the first while its body is at 60%.  That is what makes the pair read
as two hits: the first bell on its own is still within 2 dB of its loudest when
the second arrives, so the level barely moves, and the event is carried by the
new transient -- a 14 dB jump in the 3-5 kHz band and a 2 dB step out of the dip
before it (10 ms and 5 ms RMS windows respectively).

Nothing is *placed* above HF_STOP and 5-7.2 kHz is tapered, because this sound
is meant to be heard forty times a day and shrillness is what makes a
notification hurt.  The two broadband sources (mallet, FM clang) are the only
things that could stray up there, so both are rolled off at HF_STOP.  A small
Schroeder room (wet 0.18) lets the tail bloom instead of stopping dead.
"""

import math

import dsp

NAME = "dzin"
TITLE = "Dzin"
DESCRIPTION = "A small bright bell struck twice, warm and quick to fade"

# ratio, amplitude, starting phase (rad), decay (as a multiple of the note's
# tau0).  Phases are spread so the partials do not all crest together on the
# attack and spike the peak.  See note 1 in the module docstring for why the
# decay column is a table and not a power law in frequency.
PARTIALS = (
    # ratio   amp   phase  decay
    (0.500,  0.11,  1.40,  1.30),   # hum
    (1.000,  1.00,  0.00,  1.00),   # prime
    (2.010,  0.48,  1.10,  0.52),   # nominal
    (2.400,  0.44,  2.30,  0.56),   # tierce
    (3.020,  0.25,  0.60,  0.22),   # quint
    (4.200,  0.24,  1.90,  0.11),   # upper plate mode
    (5.400,  0.17,  2.90,  0.065),  # upper plate mode
)

# No partial is placed at or above HF_STOP; between HF_KNEE and HF_STOP its
# amplitude is faded out linearly so the top end arrives gradually.
HF_KNEE = 5000.0
HF_STOP = 7200.0

# Slow detune of the split prime -- see the note in _strike().
BEAT_HZ = 1.9
BEAT_DEPTH = 0.14

# Mallet contact: a few ms of noise, band-passed high.  MALLET_DUR only has to
# outlast the envelope; at 40 ms the tail is exp(-0.0395 / 0.005) = 4e-4 of the
# peak, so the buffer ends on silence rather than on a cut waveform.
MALLET_DUR = 0.040
MALLET_TAU = 0.005


def _hf_rolloff(sig):
    """Take broadband material off the top, 24 dB/oct above HF_STOP.

    Two cascaded 12 dB/oct sections rather than a textbook 4th-order Butterworth
    pair: a soft knee is wanted here, not a brick wall.
    """
    return dsp.biquad(dsp.biquad(sig, "lp", HF_STOP, q=0.707), "lp", HF_STOP, q=0.707)


def _hf_tilt(freq):
    """Amplitude weight that fades placed partials out towards HF_STOP."""
    if freq >= HF_STOP:
        return 0.0
    if freq <= HF_KNEE:
        return 1.0
    return (HF_STOP - freq) / (HF_STOP - HF_KNEE)


def _mallet(level, seed):
    """The mallet touching the bell: a few ms of band-passed noise.

    The noise is filtered *before* it is enveloped so the biquads are never
    handed a gate edge to ring on, and the envelope -- not the buffer -- is what
    starts and ends the burst.
    """
    nz = dsp.noise(MALLET_DUR, seed=seed)
    body = dsp.biquad(nz, "bp", 4300.0, q=1.1)          # wooden thump of contact
    edge = dsp.biquad(nz, "bp", 6300.0, q=1.6)          # the bright rim of it
    click = _hf_rolloff([body[i] + 0.9 * edge[i] for i in range(len(nz))])
    env = dsp.perc(MALLET_DUR, attack=0.0005, tau=MALLET_TAU)
    return dsp.gain(dsp.mul(click, env), level)


def _strike(f0, dur, level, tau0, mallet, seed):
    """One struck-bell note: additive inharmonic partials + FM clang + mallet."""
    parts = []

    for ratio, amp, phase, decay in PARTIALS:
        freq = f0 * ratio
        weight = amp * _hf_tilt(freq)
        if weight <= 0.0:
            continue
        tau = tau0 * decay
        # High modes speak faster as well as dying faster: a shorter attack.
        attack = 0.0015 + 0.004 / max(1.0, ratio)
        env = dsp.perc(dur, attack=attack, tau=tau)
        parts.append(dsp.gain(dsp.mul(dsp.sine(freq, dur, phase), env), weight))

        if ratio == 1.000:
            # Split prime: the two halves of the mode beat BEAT_HZ apart.  The
            # depth is capped so the beat crest can never out-climb the decay
            # (BEAT_DEPTH * 2pi * BEAT_HZ / (1 - BEAT_DEPTH) < 1 / tau0);
            # otherwise the note audibly swells back up mid-tail.
            beat = dsp.mul(dsp.sine(freq + BEAT_HZ, dur, phase + 0.9),
                           dsp.perc(dur, attack=attack, tau=tau * 0.85))
            parts.append(dsp.gain(beat, weight * BEAT_DEPTH))

    # Chowning bell FM: sidebands at f0 +- k*1.41*f0, inharmonic with the placed
    # partials and dense enough to read as clang without any one of them being
    # loud.  The index decays with a 70 ms time constant, so the spread
    # collapses towards the carrier while the voice itself decays over 130 ms.
    # At index 3 the outermost usable sideband is k=5, i.e. 8.4 kHz for the C6
    # strike -- past HF_STOP, which is why this voice gets _hf_rolloff too.
    clang = _hf_rolloff(dsp.fm(f0, 1.41, lambda t: 3.0 * math.exp(-t / 0.07), dur))
    clang = dsp.mul(clang, dsp.perc(dur, attack=0.003, tau=0.13))
    parts.append(dsp.gain(clang, 0.18))

    parts.append(_mallet(mallet, seed))
    return dsp.gain(dsp.mix(*parts), level)


# Dry length, and where the release starts.  The modes are still ringing when
# the buffer runs out -- a bell left alone takes several seconds -- so the last
# stretch is damped by hand.  A raised cosine is used rather than a line: it
# leaves the release with no slope discontinuity at either end, so the tail
# reads as a bell being stopped rather than as a fade-out being applied.
DRY_DUR = 0.92
RELEASE_AT = 0.46


def _release(n):
    """Raised-cosine damping from RELEASE_AT to the end of the dry buffer."""
    span = DRY_DUR - RELEASE_AT
    out = [1.0] * n
    for i in range(n):
        t = i / dsp.SR
        if t > RELEASE_AT:
            k = min(1.0, (t - RELEASE_AT) / span)
            out[i] = 0.5 * (1.0 + math.cos(math.pi * k))
    return out


def render():
    strike2_at = 0.125         # second strike 125 ms later, inside the 90-130 ms brief

    buf = dsp.silence(DRY_DUR)
    # C6 = 1046.5 Hz, then G6 = 1568.0 Hz, a perfect fifth above, body at 60%.
    # The smaller bell rings shorter (tau0) but takes nearly the same mallet.
    dsp.add_at(buf, _strike(1046.5, DRY_DUR, 0.42,
                            tau0=0.38, mallet=0.85, seed=1729), 0.0)
    # The second buffer is cut to end exactly with the first, which is where
    # _release has already reached zero -- so it is never truncated mid-ring.
    dsp.add_at(buf, _strike(1568.0, DRY_DUR - strike2_at, 0.25,
                            tau0=0.26, mallet=1.15, seed=4703), strike2_at)

    buf = dsp.mul(buf, _release(len(buf)))

    # Small room: enough bloom to sound like an object in a space, not a plugin.
    return dsp.reverb(buf, room=0.60, wet=0.18, tail=0.40)
