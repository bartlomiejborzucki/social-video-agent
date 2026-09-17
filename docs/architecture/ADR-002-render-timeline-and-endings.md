# ADR-002: Sample-based audio, CFR video, and explicit visual endings

Status: accepted

## Context

A real 57-second render contained 57 seconds of AAC samples but declared only
about 2.8 seconds of audio because numeric PTS survived a filter time-base
change. The same output inherited a phone `avg_frame_rate` near 30.017 and
accumulated about five frames of cut rounding. A separate Reel protected a
privacy boundary by holding the last safe frame for 3.76 seconds; it was safe
but looked stalled.

## Decision

- Normalize every audio range and the post-concat stream to 48 kHz stereo
  `fltp`, `asettb=1/48000`, and `asetpts=N/SR/TB` after resampling.
- Allocate video frames from cumulative EDL duration, encode once at an
  explicit compatible CFR, and trim the combined graph to the exact budget.
- Stage the MP4 in Linux cache, probe and fully decode it, then publish it
  atomically.
- Treat a privacy stop as a hard source-time boundary. If primary moving video
  ends before the range timeline, require an explicit secondary video, end
  card, or duration-bounded hold. The default unapproved hold limit is 0.75 s.
- Sample decoded ending frames every 250 ms. A near-identical run over one
  second in the final ten seconds blocks delivery unless the matching hold or
  designed end card is explicitly recorded in the EDL.

## Consequences

Older EDLs whose audio and video spans match remain valid. Split A/V EDLs that
previously relied on an implicit long last-frame extension must add a visual
fill strategy. This is intentional: missing safe footage is an editorial
decision, not a renderer default.
