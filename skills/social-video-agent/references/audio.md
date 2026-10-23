# Voice cleanup, music, ducking, and sound effects

Audio is where a short is believed or not. Speech comes first; everything here
sits under it.

## Voice cleanup is measured, not applied

`audio_cleanup_policy` in the project config decides whether the speech is
repaired at all:

- `measured` — the default. The render measures this recording and applies only
  what the measurement justifies.
- `none` — the audio is rendered exactly as recorded, and nothing is even
  measured.
- `required` — the repair has to be justifiable; an edit whose speech cannot be
  measured fails rather than rendering unrepaired.

What is measured, on the cut speech before any bed is mixed under it: the
per-window RMS distribution (so the noise floor is the 10th percentile and
speech the 90th, and their difference is the usable SNR), energy below 60 Hz
where no voice lives, a narrow band at 50 and 60 Hz for mains hum, 5-9 kHz for
sibilance, and peak level for clipping.

What can then be applied, each only when its own threshold is crossed and each
with a ceiling:

| Measured | Applied | Ceiling |
| --- | --- | --- |
| below-60 Hz energy within 15 dB of the voice | high-pass at 80 Hz | two poles |
| a narrow mains band within 18 dB of the voice, concentrated enough to be a tone | notch at the fundamental only | -15 dB |
| SNR under 20 dB over an audible floor | `afftdn` | 10 dB of reduction |
| 5-9 kHz within 8 dB of the voice | de-esser | intensity 0.15 |
| loudness range over 12 LU | compressor | 2:1 |
| peaks at or above -0.1 dBFS | nothing | reported only |

Clipping is never repaired: reconstructing a flattened waveform is invention,
so it is reported and the advice is to re-record with headroom. Harmonics of a
mains hum are left alone for the same reason — notching 100 or 120 Hz thins the
voice, which is the artificial result this design exists to avoid.

Every render says what it changed and how to undo it, and records the
measurement, the applied steps, the skipped steps with their reasons, and the
ceilings in `audio_cleanup_applied`. Brand QA checks the repair against those
ceilings and against the policy. To get the untouched audio back, re-render with
`--no-audio-cleanup` or set `audio_cleanup_policy: none`; source media is never
modified, so nothing is lost either way.

This is deliberately not a one-button "enhance voice". The same chain applied to
every clip is how a good recording ends up sounding managed: pumping where the
speaker paused, a lisp where the de-esser guessed, and room ambience replaced by
a faint warble.

## Rights and policy

Music and effects need no licence declaration. `license_confirmed` and
`license_note` are optional fields recorded in the render manifest when the
source of a track is worth keeping. The rights to what is published remain the
account owner's, so prefer libraries whose terms allow use in social video.

`music_policy` and `sfx_policy` in the project config record the project's
preference (`none`, `optional`, `required`) for the editor to follow; the
renderer and brand QA do not enforce them. Brand QA still compares the voice
cleanup that actually happened against `audio_cleanup_policy`.

## The bed

```json
"audio_bed": {
  "path": "/abs/project/assets/audio/bed.m4a",
  "gain_db": -20.0,
  "duck": true,
  "duck_ratio": 8.0,
  "duck_threshold_db": -30.0,
  "duck_release_ms": 400,
  "fade_in": 0.5,
  "fade_out": 1.5,
  "reason": "Cicha pętla utrzymuje energię między cięciami w części technicznej."
}
```

Defaults that matter: `gain_db` is capped at 0 and defaults to -20, because a
bed level with the voice is not a bed. Ducking sidechains the speech into a
compressor on the music, so the bed retreats when the speaker talks and returns
in the gaps — that is what makes music sound mixed rather than laid on top. QA
warns when a bed is louder than -12 dB or is not ducked.

A bed shorter than the edit is an error. Set `loop: true` only when the track is
built to loop; an audible seam is worse than no music.

## Effects

`sound_effects` are placed by hand at a named moment with a reason:

```json
{"path": "/abs/project/assets/audio/accent.wav", "at": 4.2, "gain_db": -8,
 "reason": "Akcent na liczbie, która jest puentą."}
```

A whoosh on every cut tends to read as generic; give each effect a reason.

## Loudness

The bed and effects are mixed **before** the loudness pass, so normalisation
measures the finished mix rather than the speech alone. With
`normalize_audio: false` a limiter is inserted instead, because summing a bed
and effects is exactly where clipping appears.
