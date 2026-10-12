# Claude Motion segments

A hook card, chapter card, call to action, quote or end card can be authored
as a Claude Motion film instead of drawn by Remotion. The film is written by
you, with your artifact tools; the user exports it; the CLI imports the export
and places it. Read this only when the motion plan holds one of those graphics
and the user wants it designed in Motion.

## When it is available

Only a Claude session whose `Artifact` tool lists the **Motion** type can write
a film. Look at your own tool list, not at the plan the user is on:

- **Motion listed:** continue below.
- **Not listed, or a Codex or other host:** say the bridge is unavailable in
  this session and keep the Remotion graphic. Never offer it.

It works on both renderers. On the FFmpeg route it is the only way to get a
designed hook or end card, and it needs no Remotion licence declaration.

## What leaves the machine

The film carries text, timing, the brand's colours and a font family name.
**The recording is never uploaded.** The logo and the brand font file are brand
files: they go up only when the project sets `brand_asset_upload: allowed`, or
when the user agrees for this film and you pass `--allow-brand-upload`. Without
either, the film has no logo and names the font by family only.

## Steps

1. After the motion plan is accepted, write the spec:

   ```bash
   social-video-agent motion film spec -w WORKSPACE --claude-motion available \
     [--scene hook_card --scene end_card]
   ```

   It writes `exports/motion-film/<film-id>/` with `film-spec.json`,
   `scenes.json` and `base.css`. A graphic shorter than one second is refused,
   because Motion refuses it; a `lower_third`, `callout` or `stat` is refused,
   because an exported film is opaque and full frame.

2. Create **one** film with the Motion type, titled after the spec. Write its
   `modules/scenes.json` and `modules/base.css` from the files the spec wrote,
   keeping `width`, `height`, `fps`, the scene ids and every `dur` exactly.
   Then one scene module per scene, its words taken from `film-spec.json`.
   - **No captions in the film.** Captions are burned over the edit later.
   - **Keep the brand.** Use the four palette colours and the font family the
     spec names. When `extended_letters` is not empty (Polish: ą ć ę ł ń ó ś ź
     ż), name a Google family that has those letters; the player's built-in
     faces do not.
   - **Stay inside the margins.** Keep words and logos inside
     `safe_margins_px` and clear of every `reserved_zones_px` edge.
   - **Same order and length.** Scenes play back to back in spec order; their
     durations add up to the film. Never reorder, merge or retime them.

3. Stop and ask the user to press **Export** on the film's page and give you
   the saved file's path. You never make the video file yourself.

4. Import it, naming the family the film's text is actually set in:

   ```bash
   social-video-agent motion film import EXPORT.mp4 -w WORKSPACE \
     --film-id FILM_ID --font-used "FAMILY"
   ```

   The import refuses another size or a length that does not match the
   scenes. It cuts one segment per scene, replaces the matching graphic in
   `motion-plan.json` with a full-frame overlay in `edl.json`, and records
   hashes in `motion-films.json`.

5. Render and review as usual. The motion sheet shows each segment. Brand QA
   fails a segment that changed after import, has the wrong size, or is set in
   a font other than the contract's. It warns when the brand changed after the
   spec, or when the segment's colours are not the brand's.

## Resume and undo

- `social-video-agent motion film status -w WORKSPACE` and `workflow status`
  list scenes specified and not yet imported. A session that resumes after the
  user exported continues at step 4.
- `motion film remove SCENE_ID -w WORKSPACE --film-id FILM_ID` takes a segment
  out and puts back the Remotion graphic it replaced.
- Changing a scene's text or timing means writing the spec again, editing the
  film, exporting and importing again. `--force` replaces a spec whose
  segments are already imported.
