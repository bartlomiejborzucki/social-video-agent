# Canva MCP (optional)

Canva publishes a remote MCP server at `https://mcp.canva.com/mcp`. This
repository ships a project-scoped `.mcp.json` that declares it, so an
MCP-capable host offers it on the next session start. Nothing is sent to Canva
until you approve the server and complete its OAuth sign-in in a browser.

## What it is good for here

- A cover built from an existing **brand template**, when the project's design
  system already lives in Canva and the typography must match it exactly.
- An exported end-card graphic used as an `image_asset` plate.
- Reading brand assets you have already published there.

## What it is not for

**B-roll.** Generic stock footage that has nothing to do with the recording
reads as filler and undermines the person on camera. B-roll should come from the
same shoot: the EDL already supports approved secondary footage through
`secondary_video_source`.

## Boundaries

- Canva is a network service. Anything you send it leaves the machine, so it
  falls under the same rule as generated plates: no source media, no brand files
  the project has not already published there, and no transcript content beyond
  the copy you intend to put on screen.
- A design is created only when a tool call created it. If the server is not
  connected, say the route is unavailable rather than describing a design that
  does not exist.
- Exports land in the workspace like any other asset and are recorded with their
  hash when delivered.

The alternative needs no account: `social-video-agent cover` composes the cover
locally from the brand contract, which is the default route.
