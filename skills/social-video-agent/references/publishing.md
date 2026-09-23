# Platforms, safe zones, and publishing copy

## Safe zones

Every feed paints its own UI over the video: a caption block and handle along
the bottom, action buttons down the right, a title row at the top. Type placed
under that furniture is not read.

```bash
social-video-agent platforms
social-video-agent qa WORKSPACE --platform reels
social-video-agent deliver WORKSPACE --output DEST --with-captions --platform reels
```

Specs are JSON in the platform registry and their reserved percentages are
**conservative estimates, not published specifications** — platforms move their
overlays without notice. Report them as measurements with both numbers, and
correct the JSON rather than arguing with the check.

Set `target_platforms: [reels]` in the project config and every QA run and
delivery checks those destinations without being asked.

Duration is checked twice: the hard platform limit is an error, the editorial
ceiling is a warning. A clip past the ceiling is allowed when the payoff
justifies it; say why in the editorial review rather than trimming to hit a
number.

## publish.json

Titles, descriptions and hashtags are editorial decisions, so the agent writes
them and the CLI validates them. Nothing generates this file for you.

```json
{
  "schema_version": 1,
  "platform": "reels",
  "language": "pl",
  "title": "Nikt ci tego nie powie o montażu",
  "description": "Trzy błędy, które kosztują zasięgi...",
  "hashtags": ["#montaż", "#reels"],
  "alt_text": "Osoba przy biurku tłumaczy trzy błędy montażowe.",
  "spoken_hook": "Najgorszy błąd to cięcie w oddechu.",
  "cta": "Zapisz na później."
}
```

Rules that hold: hashtags are single words and unique, the title must fit every
targeted platform, and `alt_text` describes the frame rather than repeating the
title. `deliver --publish` validates it against the target platforms and records
it in the delivery manifest with its hash.

## Opening checks

The ending has always been measured; the opening now is too. `qa` reports
whether the clip opens on an image rather than black, and whether a caption is
on screen within the first second — muted autoplay is the normal case, so a
silent first second is a lost viewer. `qa/opening-contact-sheet.png` covers the
first three seconds for the same targeted inspection the ending sheet gets.

## Handing the edit to a human editor

`social-video-agent export WORKSPACE` writes the cut to `exports/` as FCPXML
(Final Cut, Resolve), Premiere/FCP7 XML, OpenTimelineIO and CMX 3600 EDL, or one
of them with `--format`. Cuts land on the same frames as in the render; media
is referenced by absolute path. The command lists what the timeline cannot
carry -- framing, punch-ins, speed, holds, captions, overlays, music, effects,
voice cleanup and motion graphics -- so tell the user those stay in the render
and captions come from the workspace's SRT/ASS.

