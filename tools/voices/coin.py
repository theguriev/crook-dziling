"""The little two-note "bling" an arcade game plays when you scoop up a coin.

Acoustic model
--------------
There is no instrument to model here: the sound *is* a piece of hardware, the
Ricoh 2A03 that sang inside the NES, so this module models the chip rather than
a resonator.  Everything below is the 2A03's own behaviour, in signal order.

1. Two pulse channels.  The 2A03 has exactly two voices that can hold a pitch,
   so a coin pickup is written for both:  Pulse 1 carries the melody at 50 %
   duty (the fat, hollow chiptune lead), Pulse 2 doubles it at 12.5 % duty and
   about a third of the level.  A square has odd harmonics only; a 12.5 % pulse
   weights harmonic k by |sin(k.pi/8)|/k, so the thin channel is what puts the
   even partials into the voice -- measured on the rendered file at -19.3 dB
   (k=2), -22.6 dB (k=4) and -29.3 dB (k=6) under the fundamental, a reedy sheen
   over the square rather than a second instrument beside it.  k=8 and its
   multiples are missing from both channels -- 50 % duty has no even harmonics
   at all and 12.5 % puts its own null exactly there -- measured 62 dB down.

   The two channels are generated from the same phase origin, so the reed's
   narrow pulse sits on top of the lead's rising edge and the mix is lopsided:
   +1.26 against -0.87, a crest factor of 1.46.  That is deliberate.  The driver
   normalises by *peak*, so a lopsided wave lands quieter than a symmetrical one
   would, and a raw square is easily the hottest thing in this sound set --
   starting the two channels at different phases would buy 3.2 dB of loudness
   nobody asked for.

2. Pitch quantisation.  A pulse channel's frequency is not chosen freely, it is
   an 11-bit countdown of the CPU clock:  f = 1789773 / (16 * (t + 1)).  The
   notes are therefore snapped to the grid the chip can actually produce, which
   lands B5 at 989.92 Hz (+4 cents) and E6 at 1316.01 Hz (-3 cents) instead of
   at their equal-tempered 987.77 / 1318.51.  That mistuning is small enough to
   read as in tune and is a real fingerprint of the hardware.

3. The melody: B5 for four frames, then E6 held -- the rising fourth of the
   canonical arcade coin.  (The written spec asked for "a perfect fifth or minor
   seventh" and then named B5 -> E6, which is a fourth; the concrete pitches win,
   because they are the interval everyone actually recognises as a coin.)  The
   grid pulls the jump to 493 cents rather than a tempered 500.  The two notes
   share one continuously integrated phase, exactly as the chip does when the
   game rewrites the timer register under a running sequencer, so the note change
   cannot click; the jump is articulation enough without a gap.

4. The 4-bit volume register.  A pulse channel's amplitude is an integer in
   0..15 and game code can only rewrite it once per 60 Hz frame, so the decay of
   the second note is a staircase of 14 audible steps of 16.7 ms each, not a
   smooth ramp.  That stepping is half the charm, and it is also why the tail is
   linear rather than exponential: it is a register counting down, not a
   resonance dying away.

5. Output stage.  The pulse output is unipolar (0..15), i.e. a 12.5 % pulse
   carries a large negative mean once mapped to +/-1, and the console blocks that
   DC with a coupling capacitor before the jack.  Modelling that as a filter
   would leave a settling thump at the onset, so the mean of each duty cycle,
   2d - 1, is simply removed analytically instead -- same result, no transient,
   and it works: the realised mean of the mix measures +0.0001 over the first
   note and +0.0012 over the second.  A one-pole lowpass at 14 kHz then stands
   in for the console's own output rolloff (the value emulators have used for
   the NES since blargg's filter notes).  It costs the fundamental 0.03 dB and
   2.3 dB at the top partial, which is the difference between bright and
   piercing.

   What it deliberately does *not* do is band-limit the pulses.  ``dsp.square``
   switches on a sample boundary, so every harmonic above Nyquist folds back:
   E6's 27th lands at 8568 Hz and its 33rd at 672 Hz, and the fold-back is a
   dense comb whose loudest lines measure -28 dB and which totals -18 dB
   relative to the fundamental.  Be clear about what that is -- a real 2A03, and
   any band-limited emulator of one, does not produce it; it is the signature of
   rendering a hard pulse straight at 44.1 kHz.  It stays because the brief asks
   for exactly that raw square, because the folded lines sit under the chip's
   own 3rd and 5th harmonics (-8 dB and -13 dB), and because removing it would
   mean synthesising the pulse additively -- a different, smoother instrument.

Deliberately absent: reverb and noise.  The chip's noise channel is a separate
voice that a coin pickup never uses, and a 1985 console had no reverb at all.
Dry, bright, 8-bit.
"""

import dsp

NAME = "coin"
TITLE = "Coin"
DESCRIPTION = "The two-note chiptune bling of scooping up an arcade coin"

# -- 2A03 hardware constants ------------------------------------------------
CPU_HZ = 1789773.0          # NTSC 2A03 clock; the pulse timer divides it by 16
VOL_MAX = 15                # 4-bit volume register: 0..15
FRAME_SAMPLES = 735         # one video frame, rounded to exactly 60 Hz so that
                            # 44100 / 60 divides evenly and every register write
                            # lands on a sample (real NTSC is 60.0988 Hz)

# -- voice balance ----------------------------------------------------------
LEAD_DUTY = 0.5             # Pulse 1: the classic hollow chiptune lead
REED_DUTY = 0.125           # Pulse 2: thin reed, supplies the even harmonics
LEAD_LEVEL = 0.80           # leaves room for the reed under the 1.5 ceiling the
                            # driver's normalise wants to see
REED_LEVEL = 0.26           # the DC-blocked 12.5 % pulse peaks at 1.75, so this
                            # holds the mix peak at 1.26 -- about a third of the
                            # lead, loud enough to hear as a reed, quiet enough
                            # that the square is still the voice
OUT_LP_HZ = 14000.0         # console output rolloff -- gentle, one pole

# -- timing, in NES frames --------------------------------------------------
NOTE1_FRAMES = 4            # 66.7 ms blip
HOLD_FRAMES = 7             # second note at full volume, 116.7 ms
DECAY_FRAMES = 14           # volume 14 -> 1, one step per frame, 233.3 ms
TOTAL_FRAMES = NOTE1_FRAMES + HOLD_FRAMES + DECAY_FRAMES   # 416.7 ms

# The chip starts and stops a level dead, which a modern DAC turns into a click,
# so the module owns a short ramp at each end -- long enough to be silent (one
# and a half to two cycles of the note it lands on), short enough to leave the
# blip its bite.  The release costs the last register step 0.25 dB of its height.
ATTACK = 0.0015             # ~1.5 cycles of B5
RELEASE = 0.0015            # ~2 cycles of E6

# The driver runs dsp.fade(fade_in=3 ms, fade_out=10 ms) over whatever render()
# returns.  Both are longer than the ramps above, so without these two pads the
# driver's fades would compound with them: the attack would take 4 ms instead of
# 1.5 to reach full, and the last volume step would measure 2.2 dB shallower
# than the register says it is.  Padding with a little more silence than the
# driver's fades need parks them where they do no harm.  (trim_tail keeps the
# tail: it only ever trims back to `end + 50 ms`, which is past the file's end.)
LEAD_SILENCE = 0.004        # > 3 ms fade-in
TAIL_SILENCE = 0.012        # > 10 ms fade-out


def _nes_pitch(hz):
    """Snap a pitch to the nearest one the 11-bit pulse timer can produce."""
    timer = int(round(CPU_HZ / (16.0 * hz))) - 1
    timer = max(1, min(0x7FF, timer))
    return CPU_HZ / (16.0 * (timer + 1))


NOTE1_HZ = _nes_pitch(987.7666)     # B5
NOTE2_HZ = _nes_pitch(1318.5102)    # E6, a fourth up

NOTE1_SECS = NOTE1_FRAMES * FRAME_SAMPLES / float(dsp.SR)
TOTAL_SECS = TOTAL_FRAMES * FRAME_SAMPLES / float(dsp.SR)


def _melody(t):
    """Timer register over time -- one step, no glide (the chip cannot glide)."""
    return NOTE1_HZ if t < NOTE1_SECS else NOTE2_HZ


def _pulse(duty):
    """One pulse channel, DC-blocked the way the console's coupling cap is.

    ``dsp.square`` swings +/-1, so its mean is 2*duty - 1: zero at 50 % duty but
    -0.75 at 12.5 %.  Removing it here rather than with a highpass keeps the
    onset free of the settling transient a real filter would add.
    """
    return [v - (2.0 * duty - 1.0) for v in dsp.square(_melody, TOTAL_SECS, duty)]


def _volume():
    """The 4-bit volume register as it is rewritten, once per 60 Hz frame."""
    levels = [VOL_MAX] * (NOTE1_FRAMES + HOLD_FRAMES)
    # Linear decay in register units: 14, 13, ... 1.  Ending on 1 rather than 0
    # keeps every frame audible; the release ramp below takes it the rest of the
    # way, and is the one place this envelope is not a register value.
    levels += [VOL_MAX - 1 - k for k in range(DECAY_FRAMES)]

    env = []
    for level in levels:
        env.extend([level / float(VOL_MAX)] * FRAME_SAMPLES)

    n_in, n_out = dsp.frames(ATTACK), dsp.frames(RELEASE)
    for i in range(n_in):
        env[i] *= i / float(n_in)
    for i in range(n_out):
        env[len(env) - 1 - i] *= i / float(n_out)
    return env


def render():
    lead = _pulse(LEAD_DUTY)
    reed = _pulse(REED_DUTY)
    mixed = [LEAD_LEVEL * lead[i] + REED_LEVEL * reed[i] for i in range(len(lead))]
    # Filter before the envelope: at 14 kHz the pole settles in ~11 us, so the
    # volume staircase stays as sharp-edged as the register that drew it.
    mixed = dsp.lowpass1(mixed, OUT_LP_HZ)
    note = dsp.mul(mixed, _volume())
    return dsp.concat(dsp.silence(LEAD_SILENCE), note, dsp.silence(TAIL_SILENCE))
