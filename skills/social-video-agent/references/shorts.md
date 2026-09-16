# Long recording to several short clips

For a recording that contains several standalone moments rather than one piece.

## Approach

1. **Transcribe once.** Everything downstream reuses it; never re-transcribe per
   clip.
2. **Read the packed transcript in full** before proposing anything.
3. **Find candidates.** A candidate is a span that makes sense with no prior
   context. Look for: a claim followed by its justification, a question answered
   in full, a self-contained story, a strong opinion with a reason.
4. **Judge each candidate honestly**, on:
   - hook quality — does the first sentence earn the next five seconds?
   - standalone comprehensibility — does it work cold?
   - information density — is anything wasted?
   - payoff — does it deliver what it implies?
   - ending quality — does it land or trail off?
   - context dependency — how much does it lean on what came before?

   These are editorial judgements, not measurements. Record them with a written
   reason, and treat a confident number with suspicion.
5. **Refine boundaries.** Start on the first word of the thought, not mid-
   sentence. End after the point lands, before the speaker starts the next one.
   Boundaries snap to word edges automatically.
6. **Render each clip separately**, each with its own EDL, framing, and captions.
7. **QA each one.**

## Choosing

Prefer fewer, better clips. Five strong shorts beat ten padded ones, and a
candidate that needs a caption explaining the setup is not standalone — it is a
fragment.

If the user asks for N and only M are genuinely good, produce M and say why.

## Store the reasoning

Each candidate keeps its span, topic, transcript, scores, and the reason it was
put forward. The user should be able to disagree with a selection and see
exactly what you were thinking.
