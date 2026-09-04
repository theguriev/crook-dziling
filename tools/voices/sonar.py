"""sonar -- one transducer ping released into a very large body of water.

Acoustic model
--------------
Active sonar radiates a short narrow-band tone burst and then listens. Almost
everything you hear afterwards is the water, not the source, and that is the
point of this voice: the ping is over inside a fifth of a second and the
remaining 1.7 s is the space answering.

1. The burst.  Hull-mounted mid-frequency sonar lives in the low kilohertz.
   ``F0`` = 1240 Hz sits at the bottom of that band deliberately -- this is a
   notification someone may hear forty times a day, and a low-mid tone is less
   fatiguing than the 2-4 kHz region where the ear is most sensitive.  A driven
   transducer does not hold pitch across a burst; the radiation load shifts as
   the ringdown begins, so the tone glides down ``GLIDE`` = 4.5% across the
   whole buffer, which is 2.8% (1235 -> 1200 Hz) across the part that is
   actually audible -- Goertzel on two windows inside it reads 1230.5 Hz at
   20-50 ms and 1207.5 Hz at 110-150 ms.  That slide is most of what separates
   "transducer" from "sine generator" to the ear.  One quiet inharmonic partial
   at ``PARTIAL_RATIO`` = 2.76 stands for a plate mode of the radiating face --
   the metallic edge on the front of the ping.  It measures 18 dB below the
   fundamental at the crest and is damped faster (``PARTIAL_SHARP``), because
   water damps an undriven plate mode faster than the driven one.

2. The envelope.  A Gaussian, not a gate: a rectangular burst splatters energy
   across the spectrum at both edges, which is a click.  The rise sigma is
   short and the fall sigma 4.5x longer -- driven hard, then left to ring out.
   The pedestal is subtracted and the curve rescaled so the envelope is exactly
   zero at both ends rather than merely small.  Measured -20 dB width is 135 ms
   (24 ms rise, 111 ms fall), inside the 90-140 ms a short-pulse ping occupies.
   The fall length is not free: it has to still be sounding when the room
   arrives, or the two crest separately and the gesture turns into a swell.
   See note 4.

3. The returns.  ``DELAY_TIME`` = 276 ms is a real number: sound travels at
   ~1500 m/s in seawater, so a 276 ms round trip puts the reflector about 207 m
   away and the next one twice as far.  ``dsp.delay`` hands back dry+wet, so the
   dry copy is subtracted off and only the repeats survive.  Their peaks measure
   -13.1, -33.5 and -54.1 dB against the direct ping: one answer you can point
   at, and two that fall under the room and only thicken it.  About 12 dB a hop
   is two-way spherical spreading at double the range; the rest is reflection
   loss.  The bus shares one lowpass whose cutoff falls with time
   (``_absorption``), so each return is duller as well as quieter -- the plate
   mode sits 19.2 dB under the fundamental in the direct ping and 29.0, 31.5,
   33.5 dB under it in the returns.  Molecular absorption at 1 kHz is genuinely
   negligible over a few hundred metres, so what this filter stands in for is
   scattering and boundary loss on the reflection path, which is not.

4. The room.  A Schroeder reverb at ``ROOM`` = 0.845 (measured T60 1.52 s by
   backward integration on its impulse response) fed through a ``PRE_DELAY`` of
   22 ms -- a 33 m round trip, the boat's own depth under the surface.  The field
   is taken at ``wet=1.0`` and mixed by hand at ``ROOM_MIX`` rather than through
   ``dsp.reverb``'s crossfade, because that crossfade is not a normalised wet
   control: measured on this source it returns the field 1.15x hotter than the
   send in peak and 1.35x in RMS, so a literal ``wet=0.5`` puts the loudest
   moment of the whole file at 0.155 s -- the room, not the ping -- and inverts
   the gesture into a swell.  Mixed explicitly the room crests 4.1 dB under the
   direct arrival, the file crests on the ping at 0.045 s, and the wet bus still
   carries half the energy in the mix.

5. Conditioning the room (``_steady_decay``).  ``dsp.reverb`` is four combs of
   36-51 ms, so near 1240 Hz it offers about five modes per 30 Hz.  A
   narrow-band tone recirculating in that few modes beats against itself: the
   modal sum is a narrow-band fading process and its envelope swings by 5-8 dB
   with a ~50 ms period, heard as warble rather than as a room.  Left raw, the
   finished file rises by up to +8.1 dB out of its own nulls and is not monotone
   even at 100 ms.  That is not a tuning problem -- coherent summation cannot
   smooth a fading process, only bandwidth can, and the spec here is a tone.
   Diffusing the send through an allpass chain, splitting it across two or three
   pre-delays, summing two rooms, feeding early-reflection taps and skipping the
   reverb's own build-up were all measured; every one of them left the worst
   rise higher than doing nothing to the send at all.  So the wet bus is
   measured twice instead, over ``DECAY_FAST`` and ``DECAY_SLOW``, and the fast
   curve is laid onto the ratcheted slow one: the beat comes off, the room's own
   decay stays.  A real ocean, with orders of magnitude more scattering paths,
   decays like the slow curve and not like the beat.

What the finished file measures.  1.926 s, 166 KiB, peak 0.5494, dc -0.000004,
clipped 0.  The peak is well under the usual 0.89 because ``dsp.master`` matches
loudness across the set rather than peak, and a 16 dB crest factor buys that
match cheaply here; every level quoted below is the file as committed.  On a
25 ms RMS window hopped 5 ms -- fine enough to catch warble a 25 ms grid
straddles and hides -- the level after the crest rises above its own running
minimum four times by more than 1 dB, and never by 3 dB: +1.3 dB at 0.160 s and
+1.8 dB at 0.229 s, where the ping hands over to the room, then +2.8 dB at
0.319 s and +2.4 dB at 0.389 s -- the first return arriving and the room
answering it, the one event this voice is supposed to have.  Both disappear if
``_returns`` is taken out; nothing after 0.39 s rises by even 1 dB.  At 100 ms
the whole file is strictly monotone, -12.4 dB down to -76.3 dBFS across 20
windows; the last third never exceeds -53.5 dBFS and the file ends on true zero.
The largest sample-to-sample step anywhere is 0.11458 at 0.0547 s, which is
exactly the largest step the bare burst produces on its own at this peak, and
the 200 largest steps in the file all fall between 0.044 and 0.082 s, inside the
burst crest.  There is no discontinuity anywhere.

Nothing else -- no noise bed, no second ping, and no noise source at all, so
there is nothing to seed; two renders are byte-identical.
"""

import math

import dsp

NAME = "sonar"
TITLE = "Sonar"
DESCRIPTION = "One sonar ping released into a very large room and left to fade"

# --- the burst -----------------------------------------------------------
PING_AT = 0.004        # a hair of pre-roll: the driver's 3 ms fade-in lands on
                       # silence rather than on the envelope's first millimetre
BURST = 0.220          # buffer length; long enough that the Gaussian is down to
                       # 3.7e-3 at its end, so pinning that end to zero (below)
                       # costs no audible part of the ringdown
PEAK_AT = 0.046        # crest a fifth of the way in: driven, then released
SIGMA_IN = 0.0115      # rise sigma -- 24 ms from -20 dB up to the crest
SIGMA_OUT = 0.0520     # fall sigma, 4.5x the rise: the element rings out. Also
                       # the lever that keeps the ping sounding while the room
                       # builds; shorter and the two crest separately (note 4)

F0 = 1240.0            # low end of the mid-frequency sonar band
GLIDE = 0.045          # downward glide across the buffer, as a fraction of F0;
                       # 2.8% across the audible (-20 dB) part of the burst
PING_LEVEL = 0.72      # leaves headroom for the wet busses; driver normalises

PARTIAL_RATIO = 2.76   # inharmonic plate mode of the radiating face
PARTIAL_AMP = 0.13     # quiet: a metallic edge, not a second voice
PARTIAL_SHARP = 1.8    # envelope exponent -> sigma / sqrt(1.8): damped sooner

# --- the returns ---------------------------------------------------------
DELAY_TIME = 0.276     # ~207 m out and back at 1500 m/s in seawater
DELAY_WET = 0.26       # first hop is WET (-11.7 dB before the lowpass), each
DELAY_FB = 0.40        # further hop WET * FB = 0.104 down on the one before
RETURNS_HELD = 3       # hops the dry buffer is sized to hold whole. The third
                       # is already -54 dB and the fourth would be -75; there is
                       # nothing under that worth carrying a buffer for.

# Cutoff of the return bus over time: fc(t) = FLOOR + SPAN * e^(-t/TAU),
# so 2.0 kHz at the first return, 1.6 kHz at the second, 1.4 kHz at the third.
ABS_FLOOR = 820.0
ABS_SPAN = 1700.0
ABS_TAU = 0.75

# --- the room ------------------------------------------------------------
# Sized so the last hop the delay produces still fits whole, rather than being
# clipped mid-burst by the end of the buffer.
DRY_LEN = PING_AT + RETURNS_HELD * DELAY_TIME + BURST    # 1.052 s
PRE_DELAY = 0.022      # 33 m round trip: the surface, over the boat's head
ROOM = 0.845           # Schroeder comb feedback -> measured T60 1.52 s
ROOM_MIX = 0.56        # hand-mixed, not dsp.reverb's crossfade: puts the room
                       # 4.1 dB under the ping and half the energy in the mix
ROOM_TAIL = 0.852      # rings on past the last return; TOTAL comes to 1.926 s

# --- conditioning the room (see note 5) ----------------------------------
DECAY_FAST = 0.010     # centred RMS window: ~12 cycles of F0, resolves one fade
DECAY_SLOW = 0.250     # ...and one long enough to average five or six of them
DECAY_LIMIT_DB = 18.0  # hard bound on the correction, either way. At 12 dB the
                       # deepest nulls stay uncorrected and the tail still rises
                       # 2.2 dB climbing out of one; above 18 nothing changes.


def _gauss_env(dur, peak_at, sigma_in, sigma_out):
    """Two-sided Gaussian, exactly zero at both ends.

    Both halves have zero slope at the crest, so the asymmetry introduces no
    corner there. Subtracting the larger edge value and rescaling pins the ends
    to true zero instead of the ~1e-3 the raw curve leaves on the fall side.
    """
    n = dsp.frames(dur)
    out = [0.0] * n
    for i in range(n):
        t = i / dsp.SR
        s = sigma_in if t < peak_at else sigma_out
        out[i] = math.exp(-((t - peak_at) ** 2) / (2.0 * s * s))
    pedestal = max(out[0], out[-1])
    scale = 1.0 / (1.0 - pedestal)
    return [max(0.0, (v - pedestal) * scale) for v in out]


def _ping():
    """The tone burst: a gliding fundamental plus one damped plate mode."""
    env = _gauss_env(BURST, PEAK_AT, SIGMA_IN, SIGMA_OUT)

    def glide(t):
        """Linear drop from F0 to F0 * (1 - GLIDE) across the burst."""
        return F0 * (1.0 - GLIDE * min(1.0, t / BURST))

    body = dsp.mul(dsp.sine(glide, BURST), env)

    # The plate mode tracks the same glide, so the two stay locked together
    # instead of drifting apart into a chord.
    edge_env = [v ** PARTIAL_SHARP for v in env]
    edge = dsp.mul(dsp.sine(lambda t: PARTIAL_RATIO * glide(t), BURST), edge_env)

    return dsp.gain(dsp.mix(body, dsp.gain(edge, PARTIAL_AMP)), PING_LEVEL)


def _absorption(t):
    """Return-path cutoff: the further out the reflector, the duller the answer."""
    return ABS_FLOOR + ABS_SPAN * math.exp(-t / ABS_TAU)


def _returns(direct):
    """Just the distant returns -- the direct ping is already in the mix.

    ``dsp.delay`` hands back dry + wet, so the dry copy is subtracted off again
    and only the repeats survive. They then share one lowpass with a
    time-varying cutoff, which dulls each successive return more than the last
    without needing a separate filter per tap.
    """
    wet = dsp.delay(direct, DELAY_TIME, feedback=DELAY_FB, wet=DELAY_WET)
    echoes = [wet[i] - direct[i] for i in range(len(direct))]
    return dsp.biquad(echoes, "lp", _absorption, q=0.707)


def _moving_rms(sig, window):
    """Centred short-time RMS, so the gain it drives never lags the signal."""
    n = len(sig)
    w = max(1, dsp.frames(window))
    cum = [0.0] * (n + 1)
    for i, x in enumerate(sig):
        cum[i + 1] = cum[i] + x * x
    half = w // 2
    out = [0.0] * n
    for i in range(n):
        a = max(0, i - half)          # both edges clamp independently, so the
        b = min(n, i - half + w)      # window stays centred and just shortens
        out[i] = math.sqrt((cum[b] - cum[a]) / (b - a))
    return out


def _steady_decay(sig, fast=DECAY_FAST, slow=DECAY_SLOW, limit_db=DECAY_LIMIT_DB):
    """Take the fading off a narrow-band reverb bus, leaving its own decay.

    See note 5 in the module docstring: four combs cannot hold enough modes to
    reverberate a pure tone smoothly, so the raw field beats. Measure it twice
    -- once over ``fast``, short enough to resolve a single fade, and once over
    ``slow``, long enough to average several and so to see only the decay the
    fades ride on. Ratchet the slow curve so it can never climb, and apply the
    gain that puts the fast curve onto it. The result decays exactly as the room
    measured, minus the beat, and adds no sidebands -- it removes amplitude
    modulation rather than imposing any (the 1122/1322 Hz skirts around the
    tone come out 1-2 dB quieter than in the raw field, not louder). A bus that
    does not fade has the two curves on top of each other and comes back
    untouched; ``limit_db`` then bounds what this can do to any bus at all.
    Everything before the crest is left alone, so the room still arrives on its
    own build-up.
    """
    quick = _moving_rms(sig, fast)      # follows each individual fade
    broad = _moving_rms(sig, slow)      # the decay those fades ride on
    if not broad:
        return list(sig)
    crest = max(broad)
    if crest <= 0.0:
        return list(sig)
    lo = 10.0 ** (-limit_db / 20.0)
    hi = 10.0 ** (limit_db / 20.0)
    floor = crest * 1e-5                # ignore the digital silence at the end
    out = list(sig)
    target = crest
    for i in range(broad.index(crest) + 1, len(sig)):
        if broad[i] < target:           # ratchet: the decay may only fall
            target = broad[i]
        if quick[i] > floor:
            out[i] = sig[i] * min(hi, max(lo, target / quick[i]))
    return out


def render():
    direct = dsp.silence(DRY_LEN)
    dsp.add_at(direct, _ping(), PING_AT)

    # What reaches the listener straight down the water column.
    early = dsp.mix(direct, _returns(direct))

    # ...and what comes back off everything else, PRE_DELAY later.
    send = dsp.silence(PRE_DELAY) + early
    field = _steady_decay(dsp.reverb(send, room=ROOM, wet=1.0, tail=ROOM_TAIL))

    return dsp.mix(early, dsp.gain(field, ROOM_MIX))
