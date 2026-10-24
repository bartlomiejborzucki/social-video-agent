# Short-form practices: what helps a reel travel

Nothing makes a reel go viral on command. Reach on Reels, TikTok and Shorts
follows whether people stay past the first seconds, finish, replay and send it
on, and that depends on the audience as much as on the edit. Most published
numbers about it come from creator research, not from the platforms; treat
them as directions and trust the account's own analytics over any of them.
What an edit can do is avoid the known ways of losing a viewer. Every practice
below is either measured by `reel-check` or a judgement for you to make.

## The first second

- **Open on the situation.** Viewers decide in one to two seconds; TikTok is
  reported to read the swipe-away rate at two seconds, YouTube shows "viewed vs
  swiped away", Instagram is reported to weigh the three-second hold. Never a
  greeting, an introduction, a book title or a general question
  ([opening.md](opening.md) makes the visual half of this a rule).
- **Hear it within a second** (`situation heard at once`, ≤ 1.0 s). Trim the
  breath before the first word.
- **Read it at once.** The first caption carries the whole first sentence from
  frame 0, because most viewing starts muted.
- **Check the hook.** `hook check WORKSPACE` reads the first caption and the
  first second in Polish: not a name, title or book; the viewer addressed
  (`Twój poranek…`) or a tension or question left open; at most 8 words; the
  first word within 0.3 s; the picture moving in the first second; no
  greeting. A concrete situation is judged only when the project lists its
  niche's words under `situation:` in `.social-video/hook-words.yaml`; that
  file can replace any general list in
  `src/social_video/qa/data/hook_pl.yaml`. Each miss comes with a fix; it
  never blocks. The result is `analysis/hook-check.json` and `hook_check` /
  `hook_check_fixes` in the delivery manifest.
- **Test one change at a time.** `motion variants` renders opening variants
  along one axis and records what each tests:
  - `--axis text` (`--text LINE` or `--from-brief`): the opening line. A line
    the speaker says word for word may become the first caption, with its real
    timings; any other line appears as on-screen text over the opening and the
    captions keep the transcript. The variants must share one audio track,
    checked by hash.
  - `--axis first_shot` (`--first-shot SOURCE:START-END`): the first range is
    replaced, ranges two onwards stay identical, captions are rebuilt for the
    variant and its motion is moved by the change in length. When no recorded
    span can open that way, record `--pickup "what to film"` instead; it is
    not rendered.

  Give one `--hypothesis` per variant. Two variants is the default; more are
  harder to compare. Previews of the first 6 s come first
  (`previews/opening-<name>-6s.mp4`); render the chosen one with
  `--full --only NAME`, then `deliver --hook-variants` delivers it as
  `final-hook-<name>.mp4` with its own opening QA. The record is
  `analysis/hook-variants.json`: axis, base hashes, each variant's changes,
  shared elements and warnings. Spoken opening, pacing and ending are not
  built yet. Two different story structures are two concepts, not a test of
  one change.
- **Reading the results.** Two organic posts of two variants are not an A/B
  test: the date, the audience and the distribution differ. Say so whenever
  results are compared.

## The middle

- **Change the picture every three to five seconds** (`the picture changes
  every few seconds`, ≤ 5 s): a cut, a punch-in, a label, a graphic. Never for
  its own sake.
- **No dead air** (`no dead air inside the speech`, ≤ 0.7 s). Tighten pauses
  that are not a deliberate beat; keep the one before a punchline.
- **Caption every word** (`captioned for sound off`, ≥ 95 % of the speech).
- **One idea per reel.** A second idea is a second reel.

## The end

- **End on the payoff** (`ends on the payoff`, ≤ 0.6 s after the last word).
  A reel that stops right after the point lands is replayed, and a replay
  counts. Where it fits, let the last line lead back into the first.
- **No lingering end card** (`no lingering end card`, ≤ 2 s), and only at the
  end.

## Length

Keep it as short as the idea allows. The directional windows below are where
creator research puts the best completion; the sources disagree, so the
account's own completion numbers decide (`length suits <platform>`):

| Platform | Window |
|---|---|
| Reels | 7–45 s |
| TikTok | 15–60 s |
| Shorts | 15–50 s |

## Publishing

- **Ask for a save or a send, honestly** (`asks for a save or a send`). Sends
  and saves are widely reported as the strongest signals for reaching people
  who do not follow the account. One ask at the end of the description or in
  `cta`, in the brand's voice ("Wyślij to komuś, kto…"). Never bait.
- **Original only.** Never post a file carrying another platform's watermark;
  Instagram has said accounts that mostly repost unoriginal content are not
  recommended. Deliver a clean master per platform.
- **Set the cover at publication** from `cover.jpg`; it is what the profile grid
  and the share sheet show.
- **Test the hook, not the topic.** Publish the same idea with a different
  first sentence and compare viewed-vs-swiped or the 3-second hold after seven
  days, the D+7 check of [opening.md](opening.md).

## Running the check

```bash
social-video-agent reel-check WORKSPACE [--platform reels --platform shorts]
```

It writes `analysis/reel-check.json` and `.md`. `deliver` runs it on the
delivered video and records `reel_check` ("passed/total") and
`reel_check_warnings` in `delivery-manifest.json`. Every finding is advisory and
never blocks a delivery; say which ones you accepted and why in the editorial
review.

## Sources (2026, mostly creator research)

- [vidIQ: YouTube Shorts algorithm](https://vidiq.com/blog/post/youtube-shorts-algorithm/)
- [Toptal: YouTube Shorts length](https://www.toptal.com/creator/post/youtube-shorts-length)
- [bytecap: Shorts retention benchmarks](https://www.bytecap.io/research/youtube-shorts-retention-benchmarks)
- [InfluenceFlow: Shorts best practices 2026](https://influenceflow.io/resources/best-practices-for-youtube-shorts-the-ultimate-2026-creator-guide/)
- [Later: Instagram Reels algorithm](https://later.com/blog/instagram-reels-algorithm/)
- [TechCrunch: Instagram on original content](https://techcrunch.com/?p=2551088)
- [go-viral: TikTok length 2026 (Social Insider data)](https://www.go-viral.app/de/blog/tiktok-videolange/)
- [Opus Clip: anatomy of a viral TikTok, 2026](https://www.opus.pro/blog/anatomy-of-a-viral-tiktok-2026)
