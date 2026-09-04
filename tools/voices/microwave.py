"""The "your food is ready" beep of a domestic microwave oven.

Acoustic model
--------------
Consumer ovens announce end-of-cycle with a piezoelectric disc buzzer glued
behind the plastic front panel and driven by a squarewave oscillator.  This
module follows that chain in order.

1. Drive -- a near-square pulse at 2700 Hz.  Piezo beepers cluster in the
   2.4-3.0 kHz region because that is both where a cheap 12-20 mm disc is most
   efficient and where human hearing is most sensitive; 2700 Hz sits in the
   middle of that band.  The duty cycle is 0.45 rather than 0.50 so the even
   harmonics (5400 Hz, 10800 Hz) survive; those, plus the odd harmonics any
   rectangular wave carries, are what make the tone read as hard plastic
   instead of as a sine-wave hospital monitor.
2. AC coupling -- a piezo element is a capacitor and passes no DC, so the
   pulse's mean (2*DUTY - 1 = -0.10) is simply never synthesised.
3. Resonance -- the disc has a mechanical resonance at the drive frequency.  A
   0 dB-peak bandpass at 2700 Hz is added *underneath* the drive, lifting the
   fundamental about 2 dB over its own harmonics.  The drive stays at unity
   and the sum is trimmed afterwards by LEVEL: buying that same emphasis by
   scaling the drive down instead would pay for it out of the harmonic edge,
   which is the one thing this beep cannot afford to lose.
4. Radiation rolloff -- a small disc behind a plastic grille is a poor radiator
   above ~8 kHz, so a one-pole lowpass at 8500 Hz takes the glassy top off and
   keeps the beep from being painful.
5. Gate -- the oscillator is switched on and off.  The 4 ms rise and 6 ms fall
   are the settling time of a disc that cannot start or stop instantly, and
   they are also what keeps every segment edge click-free.  Gating comes last,
   after the filters, so no filter ring leaks into the gaps and the silence
   between beeps is exact.
6. Cabinet -- each onset mechanically taps the panel the disc is glued to: a
   very quiet, heavily lowpassed noise tick, held a fixed 30 dB under the tone.

Timing is the other half of the impression: four evenly spaced beeps, 130 ms on
and 130 ms off, the flat "beep-beep-beep-beep" nearly every domestic oven uses.
All four beeps are the same tone -- only the cabinet tap differs -- so the tone
is rendered once and reused.

Measured on the rendered file: fundamental 2700 Hz with harmonics at -18.9 dB
(5400), -14.4 dB (8100) and -21.4 dB (10800) relative to it, for 26% total
harmonic content against 42% for the bare pulse and 0% for a sine.  Nothing
non-harmonic rises above -45 dB.
"""

import math

import dsp

NAME = "microwave"
TITLE = "Microwave"
DESCRIPTION = "Four flat piezo beeps announcing that your food is ready"

# -- the oscillator that drives the disc -----------------------------------
BEEP_HZ = 2700.0        # piezo buzzer fundamental (real units: 2.4-3.0 kHz)
DUTY = 0.45             # off-centre so the even harmonics are not cancelled
TOP_PARTIAL_HZ = 19000.0  # where the Fourier sum stops: above this the 8.5 kHz
                          # rolloff has buried the partial anyway, and it keeps
                          # every term well clear of Nyquist (22050 Hz) so
                          # nothing folds back down into the audible band.

# -- the disc and the panel it is glued to ---------------------------------
RES_Q = 3.2             # disc resonance -- broad, it is a damped ceramic disc
RES_MIX = 0.25          # resonance sits under the drive: +1.94 dB on the
                        # fundamental, which is the "slight" emphasis wanted
TOP_HZ = 8500.0         # radiation rolloff of a small disc behind a grille
LEVEL = 0.79            # output trim: puts the render's internal peak at 1.13,
                        # well under the ~1.5 the driver's normalize wants
TICK_DB_UNDER = 30.0    # cabinet tap, measured against the gated tone's peak
TICK_DUR = 0.030        # long enough for the tap to decay out of earshot

# -- the pattern ------------------------------------------------------------
N_BEEPS = 4
BEEP_ON = 0.130         # seconds of tone per beep
BEEP_GAP = 0.130        # seconds of silence between beeps -- equal to BEEP_ON,
                        # because a real oven's cadence is dead even
ATTACK = 0.004          # disc take-off; also the anti-click edge
RELEASE = 0.006         # disc stop
SUSTAIN = 0.93          # the tone droops a little while it is held
LEAD = 0.005            # silence before beep 1, so the driver's 3 ms fade-in
                        # lands on nothing instead of shaving that beep's
                        # attack and making it uneven with the other three
TAIL = 0.060            # more than trim_tail's 50 ms keep, so it really trims


def _drive(dur):
    """A band-limited +/-1 pulse of duty DUTY, summed from its Fourier series.

    ``dsp.square`` aliases badly at this pitch: 2700 Hz is exactly 44100 * 3/49,
    so every harmonic above Nyquist folds back onto an exact multiple of 900 Hz.
    Measured on the naive oscillator, that pile-up puts a 900 Hz buzz only 22 dB
    under the fundamental into the beep, and the 8.2-sample-per-half-cycle grid
    also quantises the duty, dropping the wanted 5400 Hz partial from 0.197 to
    0.122.  Summing the series by hand instead keeps the spectrum exactly where
    the model says it is: partials at k * 2700 Hz with amplitude
    4 / (k*pi) * |sin(k*pi*DUTY)|, and nothing anywhere else.

    The k = 0 term -- the pulse's DC mean, 2*DUTY - 1 -- is left out, which is
    the piezo's AC coupling: a ceramic disc is a capacitor and never sees it.
    """
    out = [0.0] * dsp.frames(dur)
    k = 1
    while k * BEEP_HZ <= TOP_PARTIAL_HZ:
        # Rectangular-wave coefficients: a_k on cos(k.w.t), b_k on sin(k.w.t).
        a = (2.0 / (k * math.pi)) * math.sin(dsp.TWO_PI * k * DUTY)
        b = (2.0 / (k * math.pi)) * (1.0 - math.cos(dsp.TWO_PI * k * DUTY))
        amp = math.hypot(a, b)
        if amp > 1e-9:
            # a.cos + b.sin == amp.sin(theta + atan2(a, b)), so one oscillator
            # per partial rather than two.
            partial = dsp.sine(k * BEEP_HZ, dur, phase=math.atan2(a, b))
            for i, v in enumerate(partial):
                out[i] += amp * v
        k += 1
    return out


def _tone(dur):
    """Drive -> disc resonance -> radiation rolloff, at a safe output level."""
    drive = _drive(dur)
    resonance = dsp.biquad(drive, "bp", BEEP_HZ, q=RES_Q)
    # The bandpass is added under a full-strength drive, not blended against a
    # weakened one, so only the fundamental gains and the harmonics keep their
    # absolute level; LEVEL then takes the whole sum back down for headroom.
    tone = [LEVEL * (drive[i] + RES_MIX * resonance[i]) for i in range(len(drive))]
    return dsp.lowpass1(tone, TOP_HZ)


def _gate(dur):
    """The on/off envelope of one beep -- also the anti-click edge."""
    return dsp.env_from([
        (0.0, 0.0),
        (ATTACK, 1.0),
        (dur - RELEASE, SUSTAIN),
        (dur, 0.0),
    ])


def _tick(seed, peak):
    """Cabinet tap: the panel the disc is glued to, struck by the disc.

    White noise through a 700 Hz one-pole (a big flat plastic panel only
    resonates low), a 120 Hz highpass so the tap contributes no DC, and a very
    short decay so it reads as a tap rather than as hiss.  It is normalised to
    an explicit peak rather than left at whatever its seed produced, so all
    four taps land at the same loudness and the four beeps stay even.
    """
    tick = dsp.Noise(seed).buffer(TICK_DUR)
    tick = dsp.highpass1(dsp.lowpass1(tick, 700.0), 120.0)
    tick = dsp.mul(tick, dsp.perc(TICK_DUR, attack=0.001, tau=0.008))
    # perc's exponential is still at ~3% of peak when the buffer ends; taper it
    # so the tap does not stop on a step part-way through the beep.
    tick = dsp.fade(tick, fade_in=0.0, fade_out=0.008)
    return dsp.normalize(tick, peak=peak)


def render():
    # Every beep is the same tone through the same gate; rendering it once is
    # both faster and a statement that the four beeps really are identical.
    beep = dsp.mul(_tone(BEEP_ON), _gate(BEEP_ON))
    tick_peak = max(abs(v) for v in beep) * 10.0 ** (-TICK_DB_UNDER / 20.0)

    period = BEEP_ON + BEEP_GAP
    buf = dsp.silence(LEAD + (N_BEEPS - 1) * period + BEEP_ON + TAIL)
    for k in range(N_BEEPS):
        one = list(beep)
        # A distinct seed per beep: four different taps on the same panel,
        # fixed at build time so the render is reproducible.
        tick = _tick(11 + 7 * k, tick_peak)
        for i in range(min(len(one), len(tick))):
            one[i] += tick[i]
        dsp.add_at(buf, one, LEAD + k * period)
    return buf
