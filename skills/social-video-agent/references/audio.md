# Music, ducking, and sound effects

Audio is where a short is believed or not. Speech comes first; everything here
sits under it.

## The licence is a field, not a footnote

`audio_bed` requires `license_confirmed: true`, and so does every sound effect.
The renderer refuses a track nobody has claimed the rights to. This tool does
not supply, clear, or fetch music — the file is a local path the project already
owns or has licensed, and the basis goes in `license_note`.

Never suggest downloading a track, and never describe a track as "royalty free"
on the user's behalf. Ask what they hold the rights to.

## Policy first

`music_policy` and `sfx_policy` in the project config are executable:

- `none` — the renderer refuses an EDL that mixes a bed. This is the default.
- `optional` — allowed when it serves the edit.
- `required` — an edit without one fails Stage 2.

Brand QA compares the mix that actually happened against the policy.

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
  "license_confirmed": true,
  "license_note": "Licencja projektu, faktura 2026-03.",
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
 "license_confirmed": true, "reason": "Akcent na liczbie, która jest puentą."}
```

Nothing places an effect on a timer. A whoosh on every cut is not sound design,
it is a tell, and it is the first thing that makes a corporate short look
generic. If you cannot write the reason, do not place the effect.

## Loudness

The bed and effects are mixed **before** the loudness pass, so normalisation
measures the finished mix rather than the speech alone. With
`normalize_audio: false` a limiter is inserted instead, because summing a bed
and effects is exactly where clipping appears.
