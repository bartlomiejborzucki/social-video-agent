# Windows agent, WSL2 engine

Read this only when the agent itself is a native Windows process. If the agent
is already inside WSL, nothing here applies: that is `wsl-native`, it is
unchanged, and there is no boundary to cross.

## The division

| Side | Owns |
|---|---|
| Windows agent | native ImageGen, Canva MCP, Windows Chrome, deciding whether any of them is needed, obtaining consent |
| WSL2 engine | media analysis, FFmpeg/FFprobe, local transcription, Remotion, text composition, rendering, technical QA, delivery encodes |

Never mix the two in one render. A Windows FFmpeg and a Linux FFmpeg do not
produce the same file, so a run that used both would not be the run that was
reviewed.

## Reaching the engine

One adapter, kept in the repository:

```powershell
.\scripts\windows\social-video-agent.ps1 doctor
.\scripts\windows\social-video-agent.ps1 workflow init "C:\Users\User\Videos\Mój film.mp4" --project-root "C:\Users\User\projects\reel"
```

It resolves WSL2, picks the distribution, checks the engine is installed, and
passes your arguments through as an array. Do not build a `wsl.exe` command
string yourself, do not use `Invoke-Expression`, and do not reach for
`ffmpeg.exe`, Windows Python or Windows Node when something fails — the adapter
refuses those on purpose.

Choosing the distribution: an explicit `-Distribution` or
`$env:SOCIAL_VIDEO_WSL_DISTRIBUTION` wins, then the WSL default, then a single
WSL2 distribution. Several with no default is an ambiguity the user settles; the
adapter stops rather than running the edit on a machine they did not pick.

## Paths

Pass the user's path as they gave it. The engine normalises it exactly once,
with `wslpath`, inside the right distribution. It handles drive letters, spaces,
Polish characters, brackets, OneDrive folders, `/mnt/c/...`, Linux paths, and
`\\wsl$\<distro>\...` UNC paths. Normalising an already-converted path is a
no-op, which is what stops `/mnt/c/mnt/c/...` from ever being built.

Do not convert paths yourself, do not quote them into the argument, and do not
hand a `C:\...` path to anything Linux.

## Where files live

- source media: untouched, wherever the user keeps it;
- workflow state, config, approved plans, final files: the user's project
  directory, so the project stays self-contained and resumable;
- heavy intermediates, render cache, contact sheets, frames: a Linux directory
  under `~/.cache/social-video-agent`, never inside a synced folder. A source
  under `/mnt/<drive>` gets its workspace there automatically;
- finished results: copied atomically to the delivery directory the user asked
  for, including a Windows one.

Never create scratch directories inside a OneDrive-synced project. Only ever
clean up files this workflow created, inside that cache directory.

## Stage 0

`workflow init` writes `runtime.json`: the agent platform, the runtime mode,
the distribution and its WSL version, the project path on each side, the cache
root, which engine binaries exist, the image policy and the Remotion licence
declaration.

Capabilities that only you can see — native ImageGen, Canva — are written in
their own `session` block as `unknown_to_cli` and marked session-scoped. Record
what you used, but **re-check your own tool list when you resume**: they belong
to the session that had them, not to the project.

## Diagnosis

`doctor` separates the two sides and names one cause at a time: WSL missing,
WSL broken, no distribution, WSL 1 only, an ambiguous distribution, the engine
missing inside a working distribution, a path failure, or a capability that only
the agent can establish. Report the one it names rather than a general failure.

## Installation

The engine is installed in WSL as it always was (clone the repository there and
run `./scripts/wsl/bootstrap.sh`). The Windows side gets only the skill folder,
so Codex can recognise the request — no FFmpeg, Node, Python or Remotion is
duplicated on Windows. Re-running the installer is harmless. After the skill
list changes, a new session (or an app restart) may be needed before the skill
is found.
