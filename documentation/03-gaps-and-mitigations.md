# Gaps and mitigations

Known problems, roughly in order of how much they threaten the project.
Each has a recommended fix.

---

## G0: No local model has ever run

**The central untested assumption.** Every run to date has used either
`tests/mock_server.py` (placeholder text) or `tools/replay/server.py` (prose I
wrote by hand). Nothing has tested whether a 30B local model can produce
publishable book prose, return strict JSON reliably, or copy quotes verbatim.

Local models are strong at extraction and verification and noticeably weaker at
warm, long-form writing — which is exactly the quality this book depends on.

**Mitigation.** Run the bake-off before building anything else:

```bash
./.venv/bin/obook bakeoff 05-agents --models qwen3-30b-a3b,glm-4.7-flash
```

Read both against `tools/replay/draft.md` as a reference point. The decision
that falls out is binary and shapes everything after it: local-first, or
local-extraction plus hosted-voice.

Watch the extract line. `18/22 claims validated (82%)` means the approach works.
`3/22` means the model is not quoting verbatim — a prompt problem, not an
architecture problem.

---

## G1: Most chapters target more words than their sources support

Running the preflight check below reveals this is broader than it first looked —
**six of eight chapters** ask for more words than their sources contain:

| Chapter | Target | Source words | Ratio |
|---|---:|---:|---:|
| 07-skills-and-commands | 2,000 | 355 | **5.6×** |
| 04-rules-and-context | 2,000 | 611 | **3.3×** |
| 06-permissions-and-safety | 2,200 | 1,152 | 1.9× |
| 02-first-session | 2,200 | 1,482 | 1.5× |
| 05-agents-and-subagents | 2,600 | 1,872 | 1.4× |
| 01-why-harnesses | 1,800 | 1,765 | 1.0× |
| 03-configuring-opencode | 2,400 | 3,163 | ok |
| 08-mcp-servers | 2,400 | 2,513 | ok |

Ratios near 1.0 are fine — good prose expands on its sources with explanation
and motivation, which is exactly the connective tissue the draft prompt permits.
Chapter 05 sat at 1.4× and produced ~1,560 words against a 2,600 target: it
simply under-delivered rather than padding, and the output was sound.

The severe cases are 07 and 04. A model asked for 2,000 words from 355 words of
source will pad or invent, and it will look like a pipeline failure when it is a
sourcing failure.

**Mitigation, in order:**

1. Treat `target_words` as an upper bound, not a quota, and lower it where the
   ratio exceeds ~1.5× (~800 for 07, ~1,200 for 04).
2. Widen `sources` — 07 could draw on `commands.mdx` and `custom-tools.mdx`.
3. Expand the corpus with third-party material (see G6). These chapters benefit
   most.

Add a preflight warning when `target_words` exceeds source words:

```bash
./.venv/bin/python -c "
import yaml
from pathlib import Path
from obook.corpus import Corpus
c = Corpus(Path('corpus'))
for d in sorted(Path('chapters').iterdir()):
    s = yaml.safe_load((d/'chapter.yaml').read_text())
    w = sum(len(c.resolve(r).full_text.split()) for r in s.get('sources') or [])
    t = s.get('target_words', 0)
    if t > w: print(f'{d.name}: target {t} > source {w} — will pad or invent')
"
```

---

## G2: Extract prompt does not ask for code blocks

`prompts/extract.md` says to prefer claims with "teaching weight" but never
mentions code. The first POC extract pass returned 26 claims and **zero code
examples**, leaving the drafter unable to write any config snippet without
inventing structure.

This is fatal for a how-to book and easy to miss, because the output looks fine
until you notice nothing is executable.

**Mitigation.** Add an explicit rule to `prompts/extract.md`:

> Capture fenced code blocks as claims in their own right. Quote the block
> verbatim, including its fence and any title attribute. A how-to chapter needs
> runnable examples, and prose claims alone cannot supply them.

Then add a preflight assertion: if a chapter's sources contain fenced blocks but
no accepted claim quote contains ` ``` `, fail loudly rather than shipping a
chapter with no examples.

---

## G3: Shared model weakens the verify stage

`verify` is meant to be a *different* model from `draft`, because a model is a
poor auditor of its own output. All four roles currently point at one model.

The POC did not test this honestly either — I wrote both the draft and the
audit, so the flagged overreaches say more about deliberate self-scrutiny than
about what a shared model would catch.

**Mitigation.** Split `verify` onto a second model as soon as the POC clears.
The commented block in `models.yaml` has the config. Memory pressure is real
(~69 GB across three models against a 64 GB ceiling), so either use 4-bit qwen
(~17 GB) to make room, or accept one eviction per stage transition — which
stage-major ordering already limits to once per run.

Until then, treat verify results as weaker evidence than the logs imply.

---

## G4: Validation checks quotes, not entailment

The validator asserts a quote exists in the cited source. It does **not** check
that the claim follows from the quote.

Both POC overreaches passed validation with real quotes attached:

| Claim text | Quote | Problem |
|---|---|---|
| "file edits and bash default to ask" | "By default, all of the following are set to `ask`:" | items not in quote |
| "placed globally or per project" | "Place them in:" | paths not in quote |

They were caught downstream by verify — which is the design working — but only
because verify happened to be scrupulous. This is a structural limitation, not
a bug.

**Mitigation.** Three layers, cheapest first:

1. Strengthen `prompts/extract.md`: *"the claim must not assert anything the
   quote does not establish. If the quote lists items by reference ('the
   following'), either quote the list too or narrow the claim."*
2. Add a cheap heuristic: flag claims whose text contains specifics (digits,
   backticked identifiers) absent from the quote. Advisory, not blocking.
3. Keep verify on a separate model (G3), since it is the only real entailment
   check in the system.

---

## G5: Publish stage never executed

`publish/` is documented and its assets are carried over from a pipeline that
genuinely worked — but on a different corpus (77 hand-authored files), and it
was re-pointed at obook's output shape without a test run.

Specific unknowns: whether the build-stamp stripper handles every chapter,
whether the diagram heuristics fire correctly on generated content (opencode
docs are mostly tagged code blocks, so rasterization may be a near no-op),
whether TOC depth and chapter splitting behave, and whether the EPUB and PDF
invocations have drifted apart.

**Mitigation.** Run it against the one real chapter before the full manuscript:

```bash
docker build -t ocbook-publish publish/
docker run --rm -v "$(pwd):/work" ocbook-publish bash /work/publish/build.sh
```

Five inputs must exist first: `publish/assets/cover.png`,
`publish/metadata.yaml`, `publish/epub-metadata.xml`,
`publish/epub-titlepage.md`, `publish/frontmatter.md`.

The seven gotchas in `publish/README.md` are confirmed findings and will
recur on a fresh machine — read them before debugging.

---

## G6: Corpus expansion is not wired up

`obook sync` overwrites `corpus/docs/` wholesale from upstream, so any
third-party article dropped there is destroyed on the next sync.

**Mitigation.** Add a second directory — `corpus/external/` — that `sync` never
touches, and have `Corpus.sections()` read both. External files need frontmatter
`title:` and a `source_url:` so citations still resolve.

Scaling is already handled: `extract` batches at `max_source_words` and is the
only stage that reads raw sources, while `draft` consumes compact claims. Corpus
size is therefore bounded by disk, not context. Prefer finer anchors and a lower
`max_source_words` over adding retrieval.

**Licensing caution.** opencode's docs are MIT and safe to quote with
attribution. Third-party articles are not automatically. Verbatim quotes live in
`claims.json` and the prose paraphrases, which helps — but if you publish, look
at it properly.

---

## G7: build/ mixes real and placeholder artifacts

Right now `build/` holds one real chapter and seven mock placeholders, and
`obook status` reports all eight as `ok` because a valid fingerprint says
nothing about which backend produced it.

| Chapter | Claims | Words | Source |
|---|---:|---:|---|
| 05-agents-and-subagents | 30 | 1,609 | replay (real) |
| the other seven | 2–6 | 65–80 | `tests/mock_server.py` |

**Mitigation.** Record the backend in the build stamp — the model `base_url` is
already captured, so add a `backend: mock \| replay \| live` field and surface it
in `obook status`. Until then, clear the directory when switching backends:

```bash
rm -f build/*.md build/*.claims.json
```

---

## G8: Voice exemplars are still placeholders

`voice/exemplars.md` contains samples I wrote, not Charles's writing. Since
exemplars control tone more than any prompt instruction does, every chapter
generated now inherits a borrowed voice.

**Mitigation.** Replace with 3–5 paragraphs of your own before any run whose
output you intend to keep. This is the highest-leverage 30 minutes available,
and it should happen *before* the bake-off — otherwise the bake-off compares
models against the wrong target.
