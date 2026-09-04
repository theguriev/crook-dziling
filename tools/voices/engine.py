"""A throttle blip on a naturally aspirated four-cylinder petrol engine.

Russian drivers call this a *progazovka*: the car is standing still, the engine
is idling, the driver stabs the accelerator, the unloaded crank spins up to the
limiter and then falls back to idle.  Everything below is driven from one
rpm(t) curve, exactly as the real thing is.

Acoustic model
--------------
1. Firing rate.  A four-stroke engine fires every cylinder once per two
   revolutions, so the exhaust pulse rate is ``rpm/60 * cylinders/2 = rpm/30``.
   At the 850 rpm idle that is 28.3 Hz; at the 6800 rpm limiter it is 226.7 Hz.
   ``_rpm`` is the single source of truth and every other stage reads it.

2. rpm(t).  An unloaded engine only has to accelerate its own rotating mass, so
   it revs up hard and then flattens as it meets the limiter -- an ease-out.
   Coming back down it is fighting nothing but friction and pumping losses, so
   the fall is about twice as long as the rise and is an ease-in-out.  At the
   top the soft limiter cuts fuel in bursts; that shows up here as a small rpm
   flutter *and* a matching dip in combustion level (``_cut``), which is the
   "brap" you hear when an engine bounces off its limiter.  At the bottom the
   slammed-shut throttle drags the engine a little *under* its idle target
   before the idle-air valve catches it and walks it back up -- the small sag
   and recovery you hear at the end of every real throttle blip.

3. Exhaust source.  A cylinder blowing down into the header is a pressure
   impulse, so the core is ``dsp.pulse_train`` at the firing rate.  A saw at the
   same rate supplies the low body that a single narrow impulse per cycle does
   not, and a sine at twice the firing rate stands in for the strong second
   order of a four-into-one manifold.  A four-cylinder is never perfectly even,
   and the cylinder-to-cylinder scatter repeats once per engine *cycle* --
   rpm/120, 7 Hz at idle -- which is added as a gentle half-order amplitude
   modulation.  It is what makes an idle lope rather than buzz, and it matters
   most at idle, so its depth falls away as the revs climb.

4. Exhaust resonances.  Two bandpasses in parallel with the raw pulse:
   * one whose centre tracks 2.8x the firing rate, i.e. the part of the
     spectrum the exhaust plumbing emphasises moves with the engine, which is
     most of why a rev sounds like a rev and not like a siren;
   * a fixed 420 Hz muffler formant -- the half-wave resonance c/2L of a ~0.6 m
     silencer chamber full of hot gas (c is about 500 m/s at exhaust
     temperature, not 343).

5. Tailpipe radiation.  A pipe mouth much smaller than a wavelength is a poor
   radiator, and the pressure that does escape is what a listener a few metres
   away hears -- not the pressure inside the pipe.  Two cascaded one-pole
   highpasses at 95 Hz (12 dB/octave) are a deliberately mild stand-in for that
   rolloff; the full f^2 radiation law would hold all the way to the ka = 1
   corner near 1.8 kHz and would leave nothing but hiss.  It is housekeeping as
   well: it stops the 28 Hz idle fundamental, which no laptop speaker can
   reproduce anyway, from eating all the headroom.

6. Induction roar.  Seeded noise through three bandpasses: two whose centres
   and levels climb with rpm (quiet and dark at idle, loud and bright at the
   top) and one fixed at the 1260 Hz quarter-wave resonance c/4L of a ~68 mm
   inlet runner.  The runner resonance belongs on this path and not on the
   exhaust, because it is the induction air that flows through the runner.  The
   whole lot is gated by the exhaust pulse train, because the air is pulled in
   in gulps -- one intake stroke per firing -- not as a steady hiss.

7. Valvetrain and injector clatter.  A 16-valve four opens every valve once per
   engine cycle, so valve events arrive at 16 per two revolutions = rpm/7.5 Hz,
   exactly four times the firing rate: 113 Hz at idle, 907 Hz at the limiter.
   Each event taps a resonance around 1.8 kHz, modelled as seeded noise gated
   by a pulse train at that rate and then bandpassed, so the tap rings rather
   than clicks.  This is block noise, not exhaust noise, so it is mixed in
   after the tailpipe filter, it does not follow the combustion level curve,
   and the limiter's fuel cut does not touch it -- the valves keep moving
   whether or not the cylinder fires.  It is also what makes the idle survive a
   laptop speaker: the exhaust at 850 rpm is almost entirely under 150 Hz,
   which such a speaker simply does not reproduce, so without the clatter the
   blip would appear out of, and vanish back into, silence.

8. Non-linearity.  A modest ``soft_clip`` at the end: real recordings of a
   tailpipe compress on the peaks, and it keeps the limiter section from poking
   out over the rest.  It is deliberately gentle: fewer than two samples in a
   thousand reach the knee, and the driver's normalize then only has to pull
   the result back by about 7 %.
"""

import math

import dsp

NAME = "engine"
TITLE = "Engine"
DESCRIPTION = "A throttle blip on a four-cylinder petrol engine, idle to the limiter and back"

# -- the engine ------------------------------------------------------------
IDLE_RPM = 850.0
PEAK_RPM = 6800.0
FIRE_PER_RPM = 1.0 / 30.0      # four-stroke, four cylinders: rpm/60 * 4/2
CYCLE_PER_RPM = 1.0 / 120.0    # one full engine cycle = two revolutions

# -- the blip --------------------------------------------------------------
T_IDLE_IN = 0.12               # the beat before the driver's foot lands
T_RISE = 0.40                  # unloaded spin-up to the limiter
LIMIT_HZ = 22.0                # soft limiter cuts fuel in ~22 Hz bursts
LIMIT_CYCLES = 2               # a whole number of them, so nothing steps
T_HOLD = LIMIT_CYCLES / LIMIT_HZ
T_FALL = 0.78                  # falls slower than it rose: friction only
T_RECOVER = 0.30               # idle-air valve walking the sag back up
T_IDLE_OUT = 0.22              # settled idle to end on
DUR = T_IDLE_IN + T_RISE + T_HOLD + T_FALL + T_RECOVER + T_IDLE_OUT

_RISE_END = T_IDLE_IN + T_RISE
_HOLD_END = _RISE_END + T_HOLD
_FALL_END = _HOLD_END + T_FALL
_RECOVER_END = _FALL_END + T_RECOVER

RISE_SHAPE = 2.3               # exponent of the ease-out; >1 = hard then flat
LIMIT_DIP = 150.0              # rpm lost on each limiter cut
LIMIT_CUT = 0.34               # and the matching dip in combustion level
IDLE_SAG = 70.0                # rpm the closed throttle drags it under idle

# -- exhaust source --------------------------------------------------------
# Blowdown pulse width as a fraction of the firing period.  Valve timing is
# fixed in crank degrees, so a constant fraction is the right shape.  The pulse
# is a gaussian of standard deviation ``width * period``, so its spectrum is a
# gaussian too, with its -3 dB corner at 0.19 / (width * period): 177 Hz at
# idle, 1.4 kHz at the limiter.  Widen it and the top of the rev loses its
# edge; narrow it much further and the idle turns into a tick.
PULSE_WIDTH = 0.030
BODY_MIX = 0.32                # saw at the firing rate: the low body
SECOND_MIX = 0.16              # second order of a four-into-one manifold
LOPE_IDLE = 0.17               # half-order AM depth at idle (cylinder scatter)
LOPE_PEAK = 0.05               # ... and at the limiter, where it evens out

# -- exhaust resonances ----------------------------------------------------
TRACK_RATIO = 2.8              # moving formant: 79 Hz at idle, 635 Hz at the top
TRACK_Q = 2.4
MUFFLER_HZ = 420.0             # c/2L, L ~ 0.6 m, c ~ 500 m/s in hot gas
MUFFLER_Q = 2.8
DIRECT_MIX = 0.50
TRACK_MIX = 0.95
MUFFLER_MIX = 1.20
RADIATE_HZ = 95.0              # tailpipe radiation corner, applied twice

# -- induction roar --------------------------------------------------------
NOISE_SEED = 5
ROAR_LO_Q = 0.70               # wide: an airbox is a dull resonator
ROAR_HI_Q = 0.90
ROAR_LO_HZ = 380.0             # airbox band at idle ...
ROAR_LO_SPAN = 2000.0          # ... and how far it climbs by the limiter
ROAR_HI_HZ = 1500.0            # throttle-body hiss at idle ...
ROAR_HI_SPAN = 3200.0          # ... and where it ends up at the top
RUNNER_HZ = 1260.0             # c/4L, L ~ 68 mm inlet runner, c = 343 m/s
RUNNER_Q = 3.2                 # a pipe, so much sharper than the airbox
ROAR_LO_IDLE = 0.34            # some air even at idle, so it is never silent
ROAR_LO_GAIN = 0.85
ROAR_HI_IDLE = 0.055           # barely there at idle: nothing is flowing yet
ROAR_HI_GAIN = 0.55            # squared against rpm: brightness arrives late
RUNNER_IDLE = 0.60             # the runner rings whenever air moves at all
RUNNER_GAIN = 0.70
INDUCT_BASE = 0.65             # roar floor between intake strokes
INDUCT_GATE = 0.60             # ... and how much each stroke gulps on top

# -- valvetrain and injector clatter ---------------------------------------
CLATTER_SEED = 11              # its own noise stream: it is not the same air
VALVE_PER_FIRE = 4.0           # 16 valves / 2 revolutions = 4x the firing rate
CLATTER_WIDTH = 0.13           # tap width as a fraction of the valve period
CLATTER_HZ = 1750.0            # what the tapped ironmongery rings at, at idle
CLATTER_SPAN = 900.0           # ... it brightens only a little with rpm
CLATTER_Q = 1.1                # ring, not click, but nothing like a tone
CLATTER_IDLE = 0.60            # per-tap level at idle ...
CLATTER_RISE = 0.25            # ... and how much harder each tap lands at the
                               # top.  Small on purpose: eight times as many
                               # taps a second already makes it much louder up
                               # there, and mechanical noise grows far more
                               # slowly with rpm than combustion noise does.

# -- mixdown ---------------------------------------------------------------
# These three are relative weights; their common scale only matters through
# DRIVE, since the driver normalizes afterwards.  As set, the summed mix peaks
# at 1.40, so the tanh below bends the loudest 0.17 % of samples and no more.
EXHAUST_MIX = 0.72
ROAR_MIX = 0.77
CLATTER_MIX = 1.28             # larger than the others because a narrow
                               # bandpass on noise gives up most of its input
LEVEL_IDLE = 0.42              # idle stays clearly audible at both ends
LEVEL_SHAPE = 0.70             # level tracks rpm, but compressed
DRIVE = 1.35                   # tanh drive: peaks compress like a recording
DC_HZ = 20.0                   # final DC trap, well below the idle fundamental
EDGE_IN = 0.020                # never start or stop on a raw waveform edge
EDGE_OUT = 0.050


def _smoothstep(x):
    """Ease-in-out on [0, 1], flat at both ends so joins never kink."""
    return x * x * (3.0 - 2.0 * x)


def _cut(t):
    """Limiter fuel-cut amount in [0, 1] -- zero everywhere but the hold.

    A raised cosine over a whole number of cycles, so it leaves and rejoins the
    rpm curve at exactly zero and neither boundary steps.
    """
    if not (_RISE_END <= t < _HOLD_END):
        return 0.0
    phase = dsp.TWO_PI * LIMIT_HZ * (t - _RISE_END)
    return 0.5 - 0.5 * math.cos(phase)


def _rpm(t):
    """The one curve everything else is derived from."""
    if t < T_IDLE_IN:
        return IDLE_RPM
    if t < _RISE_END:
        # Ease-out: an unloaded crank accelerates hard, then meets the limiter.
        x = (t - T_IDLE_IN) / T_RISE
        return IDLE_RPM + (PEAK_RPM - IDLE_RPM) * (1.0 - (1.0 - x) ** RISE_SHAPE)
    if t < _HOLD_END:
        return PEAK_RPM - LIMIT_DIP * _cut(t)
    if t < _FALL_END:
        # Ease-in-out: it leaves the limiter gently and undershoots gently.
        x = (t - _HOLD_END) / T_FALL
        return PEAK_RPM - (PEAK_RPM - IDLE_RPM + IDLE_SAG) * _smoothstep(x)
    if t < _RECOVER_END:
        # The idle-air valve walking the sag back up to the idle target.
        x = (t - _FALL_END) / T_RECOVER
        return IDLE_RPM - IDLE_SAG * (1.0 - _smoothstep(x))
    return IDLE_RPM


def _fire(t):
    """Exhaust firing frequency in Hz: 28.3 at idle, 226.7 at the limiter."""
    return _rpm(t) * FIRE_PER_RPM


def _rev(t):
    """Normalised rev fraction in [0, 1]; the throttle position, in effect.

    Clamped at the bottom: the idle sag is a pitch event, not a throttle event,
    and a negative fraction would be meaningless to the shaping that uses it.
    """
    return max(0.0, (_rpm(t) - IDLE_RPM) / (PEAK_RPM - IDLE_RPM))


def render():
    n = dsp.frames(DUR)
    dt = 1.0 / dsp.SR
    rev = [_rev(i * dt) for i in range(n)]

    # --- exhaust source ---------------------------------------------------
    pulses = dsp.pulse_train(_fire, DUR, width=PULSE_WIDTH)
    # pulse_train carries a standing offset (its own -0.15 minus the mean of
    # the gaussian); take it out exactly so the filters have no step to settle.
    offset = sum(pulses) / len(pulses)
    pulses = [v - offset for v in pulses]
    body = dsp.saw(_fire, DUR)
    second = dsp.sine(lambda t: 2.0 * _fire(t), DUR)
    core = [pulses[i] + BODY_MIX * body[i] + SECOND_MIX * second[i] for i in range(n)]

    # --- exhaust resonances -----------------------------------------------
    track = dsp.biquad(core, "bp", lambda t: TRACK_RATIO * _fire(t), q=TRACK_Q)
    muffler = dsp.biquad(core, "bp", MUFFLER_HZ, q=MUFFLER_Q)
    exhaust = [
        DIRECT_MIX * core[i] + TRACK_MIX * track[i] + MUFFLER_MIX * muffler[i]
        for i in range(n)
    ]
    # Radiation from a small open pipe rises as f^2 -- two one-poles, 12 dB/oct.
    exhaust = dsp.highpass1(dsp.highpass1(exhaust, RADIATE_HZ), RADIATE_HZ)

    # --- induction roar ---------------------------------------------------
    air = dsp.Noise(NOISE_SEED).buffer(DUR)
    roar_lo = dsp.biquad(
        air, "bp", lambda t: ROAR_LO_HZ + ROAR_LO_SPAN * _rev(t), q=ROAR_LO_Q
    )
    roar_hi = dsp.biquad(
        air, "bp", lambda t: ROAR_HI_HZ + ROAR_HI_SPAN * _rev(t), q=ROAR_HI_Q
    )
    runner = dsp.biquad(air, "bp", RUNNER_HZ, q=RUNNER_Q)
    roar = [0.0] * n
    for i in range(n):
        r = rev[i]
        # Air arrives in gulps: one intake stroke per exhaust pulse.
        gulp = INDUCT_BASE + INDUCT_GATE * max(0.0, pulses[i])
        roar[i] = gulp * (
            roar_lo[i] * (ROAR_LO_IDLE + ROAR_LO_GAIN * r)
            + roar_hi[i] * (ROAR_HI_IDLE + ROAR_HI_GAIN * r * r)
            + runner[i] * (RUNNER_IDLE + RUNNER_GAIN * r)
        )

    # --- valvetrain and injector clatter ----------------------------------
    # The gate is clamped at zero so it is silent between taps; each tap starts
    # on the gaussian's peak, which is the impulsive onset a tap should have,
    # and the bandpass turns that onset into a short ring.
    taps = dsp.pulse_train(lambda t: VALVE_PER_FIRE * _fire(t), DUR, width=CLATTER_WIDTH)
    metal = dsp.Noise(CLATTER_SEED).buffer(DUR)
    struck = [
        metal[i] * max(0.0, taps[i]) * (CLATTER_IDLE + CLATTER_RISE * rev[i])
        for i in range(n)
    ]
    clatter = dsp.biquad(
        struck, "bp", lambda t: CLATTER_HZ + CLATTER_SPAN * _rev(t), q=CLATTER_Q
    )

    # --- half-order lope, level, mixdown ----------------------------------
    # Only the combustion sources ride the level curve and the limiter cut;
    # the clatter is the block, and the block does not go quiet at idle.
    lope = dsp.sine(lambda t: _rpm(t) * CYCLE_PER_RPM, DUR)
    out = [0.0] * n
    for i in range(n):
        r = rev[i]
        depth = LOPE_IDLE + (LOPE_PEAK - LOPE_IDLE) * r
        level = LEVEL_IDLE + (1.0 - LEVEL_IDLE) * (r ** LEVEL_SHAPE)
        level *= 1.0 - LIMIT_CUT * _cut(i * dt)
        out[i] = (EXHAUST_MIX * exhaust[i] + ROAR_MIX * roar[i]) * level * (
            1.0 + depth * lope[i]
        ) + CLATTER_MIX * clatter[i]

    out = dsp.soft_clip(out, drive=DRIVE)
    out = dsp.highpass1(out, DC_HZ)
    return dsp.mul(out, dsp.env_from([
        (0.0, 0.0),
        (EDGE_IN, 1.0),
        (DUR - EDGE_OUT, 1.0),
        (DUR, 0.0),
    ]))
