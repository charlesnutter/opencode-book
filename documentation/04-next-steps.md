# Next steps

Ordered so that each step's outcome informs the next, and so the assumptions
most likely to be wrong get tested earliest.

---

## 1. Write your voice exemplars

**~30 min. Do this first.**

Replace the placeholders in `voice/exemplars.md` with 3–5 paragraphs you wrote.
Models match demonstrated rhythm far better than described rhythm.

This comes first because every later step is judged against it. Running the
bake-off with borrowed exemplars measures how well each model imitates *my*
placeholder voice, which is not information you want.

While you're there, extend `banned_phrases` in `book.yaml` with any tic you
already know you hate.

---

## 2. Stand up a local model and run the bake-off

**~1 hour, mostly model download.** Addresses
[G0](03-gaps-and-mitigations.md#g0-no-local-model-has-ever-run).

```bash
# ~17 GB
mlx_lm.server --model mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit --port 1234

./.venv/bin/opencode-book bakeoff 05-agents --models qwen3-30b-a3b-instruct-2507,glm-4.7-flash
```

Chapter 05 is the right subject: it is the one chapter with a known-good
reference output (`tools/replay/draft.md`) to compare against.

**What to watch:**

| Signal | Reading |
|---|---|
| `extract: 18/22 validated` or better | quoting discipline is fine |
| `extract: 3/22` | model isn't quoting verbatim — prompt problem, not architecture |
| JSON parse failures | most likely first-hour failure; `parse_json_loose` salvages some |
| Prose quality vs `tools/replay/draft.md` | the actual decision |

**The decision this forces:** local-first, or local-extraction with a hosted
voice pass. Everything downstream depends on it, and it cannot be answered by
reasoning — only by reading output.

---

## 3. Fix the two prompt gaps

**~30 min.** Addresses
[G2](03-gaps-and-mitigations.md#g2-extract-prompt-does-not-ask-for-code-blocks)
and [G4](03-gaps-and-mitigations.md#g4-validation-checks-quotes-not-entailment).

Both are edits to `prompts/extract.md`:

- Require fenced code blocks to be captured as claims.
- Forbid claims that assert more than their quote establishes.

Then re-run chapter 05 and diff against the replay output. Because prompt
changes move the fingerprint, `opencode-book status` will correctly mark all eight
chapters stale — a good incidental test of the staleness machinery against a
real model.

---

## 4. Rebalance chapter targets

**~30 min.** Addresses
[G1](03-gaps-and-mitigations.md#g1-most-chapters-target-more-words-than-their-sources-support).

Six of eight chapters ask for more words than their sources contain. Most are
mild and fine; `07-skills-and-commands` (5.6×) and `04-rules-and-context` (3.3×)
are not. Lower those targets, widen their `sources`, and add the preflight check
from G1 so the mismatch surfaces before a build rather than after.

---

## 5. Split verify onto a second model

**~15 min config, plus download.** Addresses
[G3](03-gaps-and-mitigations.md#g3-shared-model-weakens-the-verify-stage).

Uncomment the differentiated block in `models.yaml`. Keep qwen at 4-bit (~17 GB)
so the working set stays under the 64 GB ceiling. Stage-major ordering already
limits evictions to one per stage per run.

Compare verify output before and after on the same chapter. If the second model
flags passages the first did not, that is the independence argument paying off —
and worth recording, since it justifies the memory cost.

---

## 6. Build all eight chapters

**~45 min, mostly unattended.**

```bash
rm -f build/*.md build/*.claims.json    # clear mock artifacts (G7)
./.venv/bin/opencode-book build
./.venv/bin/opencode-book assemble
```

Then read `build/manuscript.md` end to end. This is the first point at which
cross-chapter problems become visible: repetition, terminology drift, chapters
that assume something a later chapter explains.

---

## 7. Run the publish stage

**~1–2 hours, expect debugging.** Addresses
[G5](03-gaps-and-mitigations.md#g5-publish-stage-never-executed).

Supply the five inputs listed in `publish/README.md`, then:

```bash
docker build -t ocbook-publish publish/
docker run --rm -v "$(pwd):/work" ocbook-publish bash /work/publish/build.sh
```

Try it on one chapter before the full manuscript. Read the seven gotchas first —
they are confirmed findings and will save the debugging time they describe.

Test the EPUB on the **Oasis at default font size**: the smallest realistic
reading pane. If it is legible there, the Scribe is fine.

---

## 8. Expand the corpus

**Half a day.** Addresses
[G6](03-gaps-and-mitigations.md#g6-corpus-expansion-is-not-wired-up).

Add `corpus/external/` that `sync` never overwrites, teach `Corpus.sections()`
to read it, and require `title:` and `source_url:` frontmatter so citations
still resolve.

Do this *after* the pipeline is proven on official docs. It is the step that
makes chapter 01 (currently 2 refs, conceptual) and the two thin chapters
genuinely good, but it also introduces the licensing question — worth taking
seriously before publishing rather than after.

---

## Deferred

Worth doing eventually, not now:

- **Backend provenance in the build stamp** ([G7](03-gaps-and-mitigations.md#g7-build-mixes-real-and-placeholder-artifacts)) — clearing `build/` by hand is fine for one person.
- **Refactor the publish pandoc wiring** — the EPUB and PDF invocations are
  near-duplicates that should share config. Wait until it has run once; the
  right abstraction will be obvious then.
- **Executable verification** — extract every command and config block from a
  chapter and run it in a container. Textual grounding proves the book matches
  the docs; execution proves it matches reality, and catches cases where the
  docs themselves are stale. The strongest verification available for a how-to
  book about a CLI, and the natural next step once the text pipeline is boring.
