"""typewriter -- the end-of-line bell of a manual typewriter, then the carriage
coming home.

Acoustic model
--------------
Three physical events, in the order the machine does them, overlapping the way
they overlap in life.

1. THE BELL.  A typewriter bell is a small stamped-steel hemisphere, roughly
   30 mm across, flicked by a light hammer.  Because it is a *shell* and not a
   string its modes are strongly inharmonic, and a cup that size rings a little
   under 2 kHz.  The ratios here -- 1.00, 2.70, 5.20, 8.10 -- put every mode
   well off any small-integer multiple of the others, which is what stops the
   ear hearing a pitch and makes it hear metal.

   Radiation and internal losses both climb with frequency, so each mode gets
   its own decay: 105 ms for the prime, 75 ms for the 2.70 partner, 30 ms and
   15 ms for the two above it.  The ordering matters more than the exact
   numbers -- the top of the spectrum has to collapse first, and that collapse
   *is* the "ting".  But the 2.70 mode is deliberately kept alive much longer
   than the two glint modes: give it their decay instead and everything after
   the first tenth of a second is a bare sine at 1980 Hz -- a beep, which is
   the one thing a bell must not sound like.

   Two more details of a real strike.  A shell that is not perfectly
   axisymmetric splits each mode into a close doublet, and the pair beats.  The
   splits here (6.5 Hz on the prime, 11 Hz on the 2.70 mode) are chosen against
   two limits at once: slow enough that the mode always loses more amplitude
   over half a beat than the beat can hand back -- otherwise the crest props the
   ting up into a flat top instead of rippling a decay -- and fast enough that
   two or three beat periods still fit inside the mode's audible life, rather
   than the single half-swell you get from a split so narrow the mode dies
   before the beat comes round.

   And the hammer is in contact for only two or three milliseconds, which is
   broadband: hence the high-passed noise chip at t = 0 and a short FM burst
   whose 1:1.73 ratio scatters sidebands no reasonable number of sines would
   cover.

2. THE CARRIAGE RETURN, starting 200 ms in so it overlaps the bell's tail --
   you slap the lever while the ting is still going.  The carriage is a mass on
   short stiff rails driven by a spring drum: broadband mechanical noise, band
   limited to roughly 900-2500 Hz because nothing on the frame is big enough to
   radiate low end and nothing is sharp enough to hiss.  Three cues sell the
   motion.  The interval between contacts stretches as the carriage slows
   (``TOOTH_HZ0`` -> ``TOOTH_HZ1``, a tick every 8.5 ms at the start and every
   18 ms by the end); the noise dulls on the way, the swept band-pass centre
   sliding 2400 -> 1150 Hz, because the fast bright contact transients thin out
   with speed; and the teeth do not all land equally hard -- ``_wobble`` gives
   the rattle a slow, seeded irregularity so it reads as a mechanism rather
   than as a tremolo on hiss.

   The burst does *not* fade away before the impact.  It is still running at
   nearly half strength when the carriage arrives and is cut off by the
   collision over the last 10 ms, because a carriage that has already stopped
   cannot hit anything.

3. THE STOP.  A dry, low-passed noise thud with an 18 ms decay -- the frame is
   a few kilos of steel bolted to a desk, so there is no ring to speak of --
   with a 4 ms metal-on-metal contact chip riding on top, and the return spring
   left twanging behind it.  The sub-bass under 170 Hz is cut away: a
   typewriter knocks, it does not thump like a kick drum, and everything left
   sits in the 170-480 Hz knock-on-wood band plus the contact's bite around
   1.9 kHz.

   The spring is the last thing you hear, so it gets modelled rather than
   sketched.  What is actually ringing is a coiled steel band inside a drum
   bolted to the frame, and a struck object like that has its own inharmonic
   modes: 318 Hz with partners at 1.62x and 2.33x, each dying faster than the
   one below it, plus a band of noise "grain" around the fundamental for the
   30 ms of coil scrape that a pure oscillator cannot produce.  A single sine
   here is the trap -- it decays into a clean tone and the last quarter of the
   voice turns into a leftover beep.  1.62 is kept alive nearly as long as the
   fundamental on purpose: two inharmonic tones ringing together stay a
   metallic twang all the way down, where one alone becomes a note.

Under all of this the bell is still ringing faintly, and the whole mix goes
through a small Schroeder room at wet 0.10 -- a desk, not a bell tower.

Lengths are set so that the file is audible for as long as it is long.  Every
part tapers to zero on its own envelope rather than being cut -- a cut leaves a
step, and a step is a click -- and the file ends where the room's decay stops
being worth carrying.  Ramping the reverb away with a hand-drawn envelope
instead is the trap: it holds the dust just above ``trim_tail``'s 1e-4
threshold and buys a fifth of a second of file with nothing in it above
-65 dB.

Verify with ``python3 tools/analyze.py sounds/typewriter.wav``: three events
(strike at 0, carriage plateau from 0.20 down ~16 dB, impact at 0.45 up to
~8 dB under the strike), partials at 1971 and 5318 Hz through the bell's ring,
the carriage's partials between 0.25 and 0.42 all inside the 900-2500 Hz
window, and ~318 Hz thereafter.
"""

import math

import dsp

NAME = "typewriter"
TITLE = "Typewriter"
DESCRIPTION = "A typewriter's end-of-line bell, then the carriage rattling back to its stop"

# Seeds for every noise source.  Named and fixed so two builds are byte
# identical; nothing here ever calls random or time.
SEED_HAMMER = 9181
SEED_CONTACT = 4271
SEED_RAIL = 5503
SEED_JITTER = 2749
SEED_THUD = 6607
SEED_COIL = 3313

# ---------------------------------------------------------------------------
# 1. the bell
# ---------------------------------------------------------------------------

BELL_F0 = 1980.0                 # prime mode of a ~30 mm steel hemisphere

# ratio, amplitude, decay tau (s), starting phase (rad), doublet split (Hz).
# Phases are spread so the modes do not all crest on the same sample and waste
# headroom.  A split of 0 means the mode is short enough that no beat would be
# heard before it is gone.
BELL_MODES = (
    (1.00, 1.00, 0.105, 0.00, 6.5),   # 1980 Hz  -- the note you hear
    (2.70, 0.55, 0.075, 1.70, 11.0),  # 5346 Hz  -- the metallic partner
    (5.20, 0.22, 0.030, 0.40, 0.0),   # 10.3 kHz -- a few hundredths of glint
    (8.10, 0.08, 0.015, 2.60, 0.0),   # 16.0 kHz -- a flick of air, then gone
)

BELL_SPLIT_DEPTH = 0.22          # doublet partner level, relative to its mode.
                                 # A partner at 0.22 swings the pair between
                                 # 1.22x and 0.78x -- 3.9 dB of breathing.  Much
                                 # below 0.15 and the beat stops being audible;
                                 # much above it and the crest out-runs the
                                 # decay, so the ting grows a flat top instead
                                 # of falling away.  Each split is likewise
                                 # slow enough that its mode loses more than
                                 # 3.9 dB per half beat (6.4 dB for the prime,
                                 # 5.2 dB for the 2.70) -- the beat then ripples
                                 # a falling envelope rather than propping it up.
HAMMER_DUR = 0.030               # the chip's 2.8 ms tau, ten times over
HAMMER_LEVEL = 0.55              # loud: the strike is the loudest instant here
CLANG_LEVEL = 0.16               # the FM burst colours the strike, it is not it
MODE_TAIL = 11.0                 # render a mode for tail*tau; e^-11 = 1.7e-5,
                                 # so the truncation step is ~95 dB down and
                                 # cannot click
CLANG_DUR = 0.24                 # the FM strike burst runs 8 time constants of
                                 # its 30 ms decay and no more

# ---------------------------------------------------------------------------
# 2. the carriage
# ---------------------------------------------------------------------------

CARRIAGE_AT = 0.200              # slap the lever while the bell still rings
CARRIAGE_DUR = 0.258             # spec'd 180-260 ms of travel
TOOTH_HZ0 = 118.0                # contact rate at the start of the run...
TOOTH_HZ1 = 56.0                 # ...and at the end, as the carriage slows
RATTLE_FLOOR = 0.30              # the carriage hisses between ticks; it never
                                 # actually goes quiet, so the ripple sits on a
                                 # bed rather than gating it
TICK_ROUND = 1400.0              # pulse_train's rising edge is instantaneous:
                                 # its phase wraps from 1 back to 0 in one
                                 # sample, so each tooth would multiply the
                                 # noise bed by a step and put a click on every
                                 # one of them.  A one-pole at 1400 Hz rounds
                                 # that into a ~0.3 ms attack -- still an
                                 # impact, no longer an edge.
BAND_HI = 2400.0                 # swept band-pass centre: fast and bright...
BAND_LO = 1150.0                 # ...to slow and dull
RAIL_MIX = 0.75                  # the fixed rail note, under the moving contact

# ---------------------------------------------------------------------------
# 3. the stop
# ---------------------------------------------------------------------------

STOP_AT = 0.452                  # 6 ms before the carriage envelope closes:
                                 # the collision is what stops the motion
THUD_DUR = 0.18                  # 10 time constants of the 18 ms body decay:
                                 # the buffer has to end 90 dB down, because a
                                 # buffer that ends mid-decay ends on a step
CONTACT_LEVEL = 0.75             # the metal chip, relative to the body knock

SPRING_F0 = 318.0                # coiled return spring in its drum
# ratio, amplitude, decay tau (s), starting phase (rad).  Inharmonic on
# purpose: 1.62 and 2.33 are far enough off 2 and 3 that the cluster reads as a
# struck steel object and not as a note with overtones.
SPRING_MODES = (
    (1.00, 1.00, 0.105, 0.00),
    (1.62, 0.50, 0.072, 2.10),
    (2.33, 0.24, 0.019, 0.90),
)
SPRING_GRAIN = 0.50              # coil scrape: band-passed noise at the
                                 # fundamental, mixed under the modes so the
                                 # twang has a rough edge instead of being a
                                 # laboratory sine
SPRING_GRAIN_TAU = 0.030         # the scrape is over long before the tone is
SPRING_DUR = 0.40                # nearly 4 time constants of the fundamental...
SPRING_OUT = 0.070               # ...then taper the remaining 2% to nothing,
                                 # so the spring ends itself rather than
                                 # leaning on the global fade to hide a step

# ---------------------------------------------------------------------------
# mix -- levels are peak amplitudes before the driver normalises, chosen so the
# strike is the loudest moment, the impact sits ~8 dB under it, and the
# carriage coasts ~16 dB under it as background mechanism
# ---------------------------------------------------------------------------

BELL_LEVEL = 0.44
CARRIAGE_LEVEL = 1.95            # the band-passes throw most of the noise away
THUD_LEVEL = 2.60                # ...and so does the 170-480 Hz window here
SPRING_LEVEL = 0.034             # peaks ~22 dB under the impact: present in the
                                 # tail, never the event

# ---------------------------------------------------------------------------
# lengths
# ---------------------------------------------------------------------------

DRY_DUR = 0.87                   # dry mix; everything has tapered out by here
DRY_FADE_FROM = 0.83             # a safety taper on the sum, not a cut
ROOM_TAIL = 0.07                 # how much of the room's own decay to keep.
                                 # The comb feedback would ring for another
                                 # half second below -60 dB; that is file, not
                                 # sound, so it is cut here and the driver's
                                 # 10 ms fade takes the -62 dB edge off.


def _wobble(dur, seed, cutoff=60.0):
    """A slow, smooth, deterministic wander in [0, 1].

    Twice-lowpassed white noise, scaled so +/-2.2 sigma spans the range: wide
    enough to swing properly, tight enough that a rare excursion only clamps
    instead of dominating.  Used to make the escapement ticks uneven.
    """
    w = dsp.lowpass1(dsp.lowpass1(dsp.noise(dur, seed=seed), cutoff), cutoff)
    n = max(1, len(w))
    sigma = math.sqrt(sum(v * v for v in w) / n)
    if sigma <= 1e-12:
        return [0.5] * len(w)
    return [min(1.0, max(0.0, 0.5 + 0.5 * (v / (2.2 * sigma)))) for v in w]


def _hammer(dur, level, seed):
    """The two or three milliseconds the hammer is in contact with the bell.

    Filtered *before* it is enveloped so the biquad never rings on a gate edge:
    the burst starts and stops on the envelope only.
    """
    chip = dsp.highpass1(dsp.noise(dur, seed=seed), 3000.0)   # bright half only
    chip = dsp.biquad(chip, "lp", 11000.0, q=0.6)
    env = dsp.perc(dur, attack=0.0004, tau=0.0028)
    return dsp.gain(dsp.mul(chip, env), level)


def _bell(dur, level, seed):
    """Struck steel hemisphere: inharmonic modes + FM clang + hammer chip."""
    out = dsp.silence(dur)

    for ratio, amp, tau, phase, split in BELL_MODES:
        freq = BELL_F0 * ratio
        # High modes speak faster as well as dying faster -- the hammer couples
        # to a short wavelength almost immediately.
        attack = 0.0008 + 0.0016 / ratio
        seg = min(dur, attack + MODE_TAIL * tau)
        env = dsp.perc(seg, attack=attack, tau=tau)
        dsp.add_at(out, dsp.gain(dsp.mul(dsp.sine(freq, seg, phase), env), amp), 0.0)
        if split:
            # The other half of the doublet: same envelope, a few Hz away, and
            # launched in phase -- one hammer blow starts both halves together
            # and they only drift apart afterwards, which is the beat.
            partner = dsp.mul(dsp.sine(freq + split, seg, phase), env)
            dsp.add_at(out, dsp.gain(partner, amp * BELL_SPLIT_DEPTH), 0.0)

    # Inharmonic clang: dense sidebands for the first few hundredths of the
    # strike, then nothing.  1.73 is deliberately irrational-looking -- any
    # simple ratio would fold the sidebands back onto a harmonic series.
    clang = dsp.fm(BELL_F0, 1.73, lambda t: 2.4 * math.exp(-t / 0.018), CLANG_DUR)
    clang = dsp.mul(clang, dsp.perc(CLANG_DUR, attack=0.0012, tau=0.030))
    dsp.add_at(out, dsp.gain(clang, CLANG_LEVEL), 0.0)

    dsp.add_at(out, _hammer(HAMMER_DUR, HAMMER_LEVEL, seed), 0.0)
    return dsp.gain(out, level)


def _rattle(dur, seed):
    """Amplitude ripple of the escapement teeth, slowing with the carriage.

    ``pulse_train`` runs from -0.15 to 0.85, so clamping the negative part away
    leaves a narrow tick roughly a fifth of each cycle wide.  ``_wobble`` then
    scales each tick between 0.45x and 1.20x, because no two teeth in a real
    machine are struck equally hard -- that unevenness is most of what makes
    the burst read as machinery instead of as modulated hiss.  Finally the
    whole curve is rounded (see ``TICK_ROUND``) so no tooth begins on a step.
    """
    rate = lambda t: TOOTH_HZ0 + (TOOTH_HZ1 - TOOTH_HZ0) * (t / dur)
    teeth = dsp.pulse_train(rate, dur, width=0.16)
    jitter = _wobble(dur, seed)
    span = 1.0 - RATTLE_FLOOR
    raw = [RATTLE_FLOOR + span * max(0.0, teeth[i]) * (0.45 + 0.75 * jitter[i])
           for i in range(len(teeth))]
    return dsp.lowpass1(raw, TICK_ROUND)


def _carriage(dur, level, seed_contact, seed_rail, seed_jitter):
    """Band-limited mechanical noise that slows, dulls and is cut off by the stop."""
    centre = lambda t: BAND_HI + (BAND_LO - BAND_HI) * (t / dur)
    # Two decorrelated sources: the moving contact, which sweeps down as the
    # carriage slows, and the rails, which sing at a fixed pitch throughout.
    sweep = dsp.biquad(dsp.noise(dur, seed=seed_contact), "bp", centre, q=0.8)
    rails = dsp.biquad(dsp.noise(dur, seed=seed_rail), "bp", 1350.0, q=0.6)
    car = [sweep[i] + RAIL_MIX * rails[i] for i in range(len(sweep))]

    # Hold the burst inside the 900-2500 Hz window the machine can actually
    # radiate: no desk thump below, no hiss above.  Both edges are cascaded
    # rather than single stages -- one 12 dB/oct skirt leaves enough 3-5 kHz
    # through to read as hiss rather than as machinery.
    car = dsp.highpass1(car, 700.0)
    car = dsp.biquad(car, "hp", 900.0, q=0.7)
    car = dsp.biquad(car, "lp", 2500.0, q=0.7)
    car = dsp.biquad(car, "lp", 2500.0, q=0.6)

    car = dsp.mul(car, _rattle(dur, seed_jitter))
    # 16 ms to get going, then a long coast losing speed -- and still at 0.46
    # when the margin stop arrives, which the last 10 ms then kills.
    env = dsp.env_from([(0.0, 0.0), (0.016, 1.0), (0.090, 0.82),
                        (0.200, 0.58), (dur - 0.010, 0.46), (dur, 0.0)])
    return dsp.gain(dsp.mul(car, env), level)


def _thud(dur, level, seed):
    """Carriage meeting its margin stop: dry, low, and over almost at once.

    Body and contact are two bands of the *same* noise because they are two
    bands of the same single collision.
    """
    nz = dsp.noise(dur, seed=seed)
    body = dsp.biquad(nz, "lp", 480.0, q=0.9)       # felted stop against a frame
    # A typewriter frame is a few kilos of steel on a desk, not a kick drum:
    # nothing down there is big enough to move air, so the sub-bass the
    # low-pass leaves behind is cut away and the knock sits in 170-480 Hz where
    # a laptop speaker can actually reproduce it.
    body = dsp.highpass1(body, 170.0)
    body = dsp.mul(body, dsp.perc(dur, attack=0.0008, tau=0.018))
    # 4 ms of metal on metal.  Q is high enough that the chip stays where the
    # comment says it is instead of spraying an octave of white noise above it.
    contact = dsp.biquad(nz, "bp", 1900.0, q=1.6)
    contact = dsp.mul(contact, dsp.perc(dur, attack=0.0004, tau=0.0040))
    return dsp.gain(dsp.mix(body, dsp.gain(contact, CONTACT_LEVEL)), level)


def _spring(dur, level, seed):
    """The return spring twanging after the impact.

    A coiled steel band in a drum, not a tuning fork: three inharmonic modes
    with staggered decays, plus a short band of noise at the fundamental for
    the scrape of the coil settling.  The grain is what keeps this from
    decaying into a bare 318 Hz sine, which is what the last quarter of the
    voice would otherwise be.
    """
    out = dsp.silence(dur)
    for ratio, amp, tau, phase in SPRING_MODES:
        env = dsp.perc(dur, attack=0.0015, tau=tau)
        tone = dsp.sine(SPRING_F0 * ratio, dur, phase)
        dsp.add_at(out, dsp.gain(dsp.mul(tone, env), amp), 0.0)

    # Q ~3.5 is loose enough to pass a band rather than a line: the result is
    # pitched-but-noisy, which is what a coil scraping in its drum sounds like.
    grain = dsp.biquad(dsp.noise(dur, seed=seed), "bp", SPRING_F0, q=3.5)
    grain = dsp.mul(grain, dsp.perc(dur, attack=0.0010, tau=SPRING_GRAIN_TAU))
    dsp.add_at(out, dsp.gain(grain, SPRING_GRAIN), 0.0)

    # The fundamental is still at ~2% of its peak when the buffer runs out, so
    # taper it rather than truncate it.  fade_in=0 leaves the attack alone.
    return dsp.fade(dsp.gain(out, level), 0.0, SPRING_OUT)


def render():
    buf = dsp.silence(DRY_DUR)

    dsp.add_at(buf, _bell(DRY_DUR, BELL_LEVEL, seed=SEED_HAMMER), 0.0)
    dsp.add_at(buf, _carriage(CARRIAGE_DUR, CARRIAGE_LEVEL, SEED_CONTACT,
                              SEED_RAIL, SEED_JITTER), CARRIAGE_AT)
    dsp.add_at(buf, _thud(THUD_DUR, THUD_LEVEL, seed=SEED_THUD), STOP_AT)
    dsp.add_at(buf, _spring(SPRING_DUR, SPRING_LEVEL, seed=SEED_COIL),
               STOP_AT + 0.004)

    # Every voice above already ends on its own taper; this is belt and braces
    # for the bell's prime mode, which is the one thing still running when the
    # dry buffer stops.
    buf = dsp.mul(buf, dsp.env_from([(0.0, 1.0), (DRY_FADE_FROM, 1.0),
                                     (DRY_DUR, 0.0)]))

    # A desk in a small room, not a hall.  ROOM_TAIL is what ends the file --
    # trim_tail is only the backstop, since the room never falls under its 1e-4
    # threshold on its own.  Ramping the room away with a hand-drawn envelope
    # instead just holds the dust above that threshold and buys empty file.
    return dsp.reverb(buf, room=0.62, wet=0.10, tail=ROOM_TAIL)
