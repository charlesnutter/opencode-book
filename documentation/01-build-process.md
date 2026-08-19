# The build process

The production pipeline, step by step, with the commands that run each part.

```
opencode docs ──sync──► corpus/ (pinned)
                          │
                          ├─ extract   claims + verbatim quotes      (model)
                          ├─ validate  literal substring check       (NO model)
                          ├─ draft     prose from validated claims   (model)
                          ├─ verify    independent support audit     (model)
                          └─ voice     style pass                    (model)
                          │
                       build/*.md ──assemble──► manuscript.md ──publish──► .epub/.pdf
```

---

## Step 0 — Environment

```bash
cd ~/dev/ocbook
python3 -m venv .venv
./.venv/bin/pip install -e .
```

Two dependencies only: `pyyaml` and `httpx`. The `opencode-book` console script lands in
`.venv/bin/opencode-book`.

One packaging note: `pyproject.toml` pins `packages = ["opencode-book"]` explicitly.
Without it setuptools auto-discovery treats `corpus/`, `prompts/`, `chapters/`
and `voice/` as Python packages and the install fails.

---

## Step 1 — Sync and pin the corpus

```bash
./.venv/bin/opencode-book sync
```

```
synced 36 docs (49,468 words)
  repo:   anomalyco/opencode@dev
  commit: 040b8561400fcbe84eaf8d045ede46fc014e2d00
```

What it does:

- Reads the git tree at `anomalyco/opencode@dev` (note: the repo moved from
  `sst/opencode`).
- Takes only **top-level** `.mdx` files under `packages/web/src/content/docs/`.
  Anything one level deeper is a locale translation — there are 17 of them, and
  including them would inflate the corpus roughly 17× for no benefit.
- Writes each file to `corpus/docs/` and records sha256, byte count, word count
  and source URL in `corpus/lock.json`, alongside the resolved commit SHA.

`corpus/lock.json` is committed; `corpus/docs/` is gitignored. The lock is what
makes citations permanent — every footnote resolves to a pinned blob URL at a
known commit, not to a moving `dev` branch.

**Why there is no retrieval layer.** The whole English corpus is ~49.5k words,
roughly 70k tokens. It fits in a single modern context window. A vector store
would add the most failure-prone component in a typical doc pipeline to solve a
problem this corpus does not have. Chapters name their sources explicitly
instead.

---

## Step 2 — Find citable anchors

```bash
./.venv/bin/opencode-book anchors --doc agents.mdx
```

```
agents.mdx
  agents.mdx#built-in            320w  Built-in
  agents.mdx#configure           195w  Configure
  agents.mdx#options            1586w  Options
    agents.mdx#permissions        448w  Permissions
    agents.mdx#primary-agents      80w  Primary agents
```

Each of the 36 docs is parsed into heading-delimited sections — 627 in total.
Each section carries two bodies:

- `text` — content up to the next heading of any level
- `full_text` — content up to the next heading of the *same or higher* rank, so
  citing `## Configure` includes its `### JSON` and `### Markdown` children

`full_text` is what gets sent to the model and what the validator checks
against.

---

## Step 3 — Write chapter specs

A chapter is a directory under `chapters/` containing a `chapter.yaml`:

```yaml
id: agents
title: Agents and Subagents
target_words: 2600
objectives:
  - Distinguish primary agents from subagents in plain language
  - Configure a custom agent in both JSON and markdown
sources:
  - agents.mdx#types
  - agents.mdx#primary-agents
  - agents.mdx#permissions
```

Sources are `doc#anchor` refs, never free text. This is what makes the
many-docs-to-one-chapter mapping explicit, diffable, and reviewable. A bad ref
fails at build time with the list of valid anchors rather than silently
producing a thin chapter.

Verify every spec resolves before spending model time:

```bash
./.venv/bin/python -c "
import yaml
from pathlib import Path
from opencode_book.corpus import Corpus
c = Corpus(Path('corpus'))
for d in sorted(Path('chapters').iterdir()):
    spec = yaml.safe_load((d/'chapter.yaml').read_text())
    refs = spec.get('sources') or []
    words = sum(len(c.resolve(r).full_text.split()) for r in refs)
    print(f'{d.name:<28} {len(refs):>2} refs {words:>6} words')
"
```

Current state:

| Chapter | Refs | Source words |
|---|---:|---:|
| 01-why-harnesses | 2 | 1,765 |
| 02-first-session | 8 | 1,482 |
| 03-configuring-opencode | 4 | 3,163 |
| 04-rules-and-context | 8 | 611 |
| 05-agents-and-subagents | 13 | 1,872 |
| 06-permissions-and-safety | 10 | 1,152 |
| 07-skills-and-commands | 8 | 355 |
| 08-mcp-servers | 8 | 2,513 |

Six of these eight target more words than their sources contain; 04 and 07
severely so — see
[G1](03-gaps-and-mitigations.md#g1-most-chapters-target-more-words-than-their-sources-support).

---

## Step 4 — Point at a model

`models.yaml` maps *roles* to models. Stages ask for a role, never a model name,
so swapping is a config edit.

<a name="models"></a>

**Current setup: one model, four roles**, differing only by temperature:

| Role | Temp | Rationale |
|---|---|---|
| `extract` | 0.1 | graded by string match; needs near-deterministic quoting |
| `draft` | 0.4 | the writer |
| `verify` | 0.0 | auditor |
| `voice` | 0.7 | room to vary rhythm |

The differentiated setup is kept commented in `models.yaml`. It is better on
quality but its three models total ~69 GB — `qwen3-30b-a3b` @8bit (32.5) +
`glm-4.7-flash` @6bit (24.4) + `gpt-oss-20b` (12.1) — against the M5 Pro's hard
64 GB ceiling. They cannot all stay resident, so each role change evicts and
reloads from disk.

**Hardware note.** The M5 Pro is 307 GB/s with a 64 GB ceiling. Prefer MoE
models: dense models are bandwidth-bound (every parameter read per token), while
MoE activates ~3B per token and sidesteps that wall. The effect is large enough
on Pro-tier silicon that an M4 Pro can beat an M3 Ultra on an 80B MoE despite a
third the bandwidth.

Any OpenAI-compatible server works:

```bash
mlx_lm.server --model mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit --port 1234
# or LM Studio (:1234), Ollama, llama.cpp, or a hosted API
```

---

## Step 5 — Build

```bash
./.venv/bin/opencode-book status          # what's stale
./.venv/bin/opencode-book build 05-agents # one chapter
./.venv/bin/opencode-book build           # everything stale
./.venv/bin/opencode-book build --force   # rebuild regardless
```

Chapter slugs accept unambiguous partials: `05`, `agents`, `05-agents` all
resolve to `05-agents-and-subagents`.

### The five stages

**extract** — the only stage that reads raw sources. Returns claims, each with a
verbatim quote and the ref it came from. Batched at `max_source_words` (default
12,000) so corpus growth never exceeds a context window.

**validate** — *pure code, no model.* Asserts each quote appears as a literal
substring of the cited source. Whitespace is normalised (models reflow long
quotes); nothing else is. No fuzzy matching, no edit-distance threshold.

This is the load-bearing component. Published citation-hallucination rates for
LLMs run roughly 11–57%; a substring assertion collapses the fabricated-citation
class to about zero, in microseconds. Rejections are categorised, because they
are different bugs:

```
rejected [bogus]: quote not found verbatim in skills.mdx#understand-discovery (fabricated or paraphrased)
rejected [c3]:    quote not found in agents.mdx#subagents (it appears in agents.mdx#primary-agents -- miscited)
```

**draft** — writes prose from validated claims **only**. It never sees raw
documentation, which is what stops it "remembering" a flag that does not exist.

**verify** — audits the draft against the evidence. Should be a different model
from `draft`; currently is not (see
[G3](03-gaps-and-mitigations.md#g3-shared-model-weakens-the-verify-stage)).
Unsupported passages trigger a bounded revision loop (`max_revisions`, default 1).

**voice** — style pass against `voice/exemplars.md`, forbidden from changing any
factual statement or touching code blocks.

### Stage-major ordering

`opencode-book build` with more than one chapter runs **stage-major**: every chapter
through `extract`, then every chapter through `draft`, and so on. With
per-role models this is 4 model loads per run instead of 4 per chapter — on 8
chapters, 4 loads instead of 32. Failures are isolated per chapter, so one bad
extraction no longer aborts the run.

`--chapter-major` restores per-chapter ordering for debugging.

### Outputs

- `build/<chapter>.md` — the chapter, with a build stamp comment on top
- `build/<chapter>.claims.json` — audit trail: accepted claims, rejections with
  reasons, verify verdicts

### Staleness

Each artifact's stamp carries a fingerprint over four inputs:

```
chapter spec + prompt templates + source excerpts + model identity
```

| You change | What rebuilds |
|---|---|
| upstream docs (`opencode-book sync`) | only chapters citing changed sections |
| a file in `prompts/` | every chapter |
| a model in `models.yaml` | every chapter, and outputs are diffable |
| one `chapter.yaml` | that chapter |

Verified behaviour:

```bash
./.venv/bin/opencode-book status | grep skills     # -> ok
printf '\n<!-- tweak -->\n' >> prompts/draft.md
./.venv/bin/opencode-book status | grep skills     # -> STALE
```

---

## Step 6 — Assemble

```bash
./.venv/bin/opencode-book assemble
```

Concatenates built chapters in filename order into `build/manuscript.md`,
stripping each build stamp and prefixing each chapter's `title` as an `h1`.

---

## Step 7 — Publish (not yet run)

```bash
docker build -t ocbook-publish publish/
docker run --rm -v "$(pwd):/work" ocbook-publish bash /work/publish/build.sh
```

Produces `build/publish/opencode-book.epub` and `.pdf` via pandoc, weasyprint
and epubcheck in a container.

**This has never been executed against generated chapters.** The approach was
proven on a different corpus (the community *Deep Dive into OpenCode* book →
Kindle EPUB + 755-page PDF) and re-pointed at opencode-book's output shape without a
test run. `publish/README.md` carries the full WIP caveat and — more valuable —
seven confirmed gotchas, including Debian's broken `epubcheck` launcher, `@page`
CSS failing epubcheck, and `--include-before-body` multiplying across every
chapter of an EPUB.

Before the first run you must supply `publish/assets/cover.png`,
`publish/metadata.yaml`, `publish/epub-metadata.xml`,
`publish/epub-titlepage.md` and `publish/frontmatter.md`.

---

## Testing without a model

```bash
./.venv/bin/python tests/mock_server.py &
./.venv/bin/opencode-book build --force
```

`tests/mock_server.py` returns real quotes pulled from the corpus plus one
deliberately fabricated claim, so the validator's reject path is exercised on
every run. Useful for checking plumbing; produces ~25-word placeholder chapters.
