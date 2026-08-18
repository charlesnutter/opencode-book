# obook

Build a book from [opencode](https://opencode.ai)'s documentation, using local
models, with every factual claim machine-checked against the source.

It is a build system, not a chatbot. Chapters are declarative specs, outputs are
fingerprinted, and only stale chapters rebuild — so when upstream docs change,
or you tune a prompt, you regenerate exactly what's affected.

---

## Quick start

```bash
python3 -m venv .venv && ./.venv/bin/pip install -e .
./.venv/bin/obook sync            # fetch + pin the docs corpus
./.venv/bin/obook status          # what needs building
./.venv/bin/obook build 05-agents-and-subagents
./.venv/bin/obook assemble        # concatenate into build/manuscript.md
```

Then `publish/` turns those chapters into an EPUB and PDF — see
[publish/README.md](publish/README.md). That stage is a **work in progress**.

You need an OpenAI-compatible server running (LM Studio, `mlx_lm.server`,
Ollama, llama.cpp). Point `models.yaml` at it. To exercise the pipeline with no
model at all:

```bash
python tests/mock_server.py &     # returns real quotes + one fabrication
./.venv/bin/obook build 07-skills-and-commands --force
```

---

## How it works

```
extract   claims + verbatim quotes          fast model, batched per source
validate  literal substring check           NO MODEL — pure code
draft     prose from validated claims only  primary model
verify    independent support audit         a DIFFERENT model
voice     style pass against exemplars      voice model
```

**The validate stage is the point of the whole thing.** The extractor must
return a verbatim quote for every claim; `obook` then asserts that quote appears
literally in the cited source file. It's a string comparison, so it cannot
itself hallucinate. Published citation-hallucination rates for LLMs run roughly
11–57%; a substring assertion collapses the fabricated-citation class to about
zero, in microseconds.

Rejections are categorised, because they're different bugs:

```
rejected [bogus]: quote not found verbatim in skills.mdx#understand-discovery (fabricated or paraphrased)
rejected [c3]:    quote not found in agents.mdx#subagents (it appears in agents.mdx#primary-agents -- miscited)
```

The drafter never sees raw documentation — only validated claims. That's what
keeps it from "remembering" a flag that doesn't exist.

---

## Chapter specs

Each chapter is a directory with a `chapter.yaml`:

```yaml
id: agents
title: Agents and Subagents
target_words: 2600
objectives:
  - Distinguish primary agents from subagents in plain language
sources:
  - agents.mdx#types
  - agents.mdx#primary-agents
  - permissions.mdx#agents
```

Sources are `doc#anchor` refs, not free text. Many docs can feed one chapter;
one doc can feed many chapters. List valid anchors with:

```bash
obook anchors --doc agents.mdx
```

A bad ref fails loudly at build time with the list of valid anchors, rather than
silently producing a thin chapter.

---

## Staleness

A chapter's fingerprint hashes four inputs:

```
chapter spec  +  prompt templates  +  source excerpts  +  model identity
```

| You change | What rebuilds |
|---|---|
| upstream docs (`obook sync`) | only chapters citing changed sections |
| a file in `prompts/` | every chapter |
| a model in `models.yaml` | every chapter, and outputs are diffable |
| one `chapter.yaml` | that chapter |

---

## Models

`models.yaml` maps *roles* to models, so swapping is a config edit. Defaults are
tuned for a 64GB M5 Pro (307 GB/s, hard 64GB ceiling):

| Role | Default | Why |
|---|---|---|
| `extract` | gpt-oss-20b (~12GB) | high volume, graded by string match not taste |
| `draft` | qwen3-30b-a3b-instruct-2507 (~32GB @8bit) | MoE, ~3B active |
| `verify` | glm-4.7-flash (~24GB @6bit) | deliberately *not* the drafter |
| `voice` | glm-4.7-flash | the role most worth upgrading |

**Prefer MoE models on Apple Silicon.** Dense models are bandwidth-bound —
every parameter is read per token. MoE activates ~3B per token and sidesteps
that wall. On Pro-tier chips the effect is large enough that an M4 Pro can beat
an M3 Ultra on an 80B MoE despite a third the bandwidth.

Run the bake-off before committing to a model:

```bash
obook bakeoff 05-agents-and-subagents --models qwen3-30b-a3b,glm-4.7-flash,gpt-oss-20b
```

Then read all three and pick the voice you'd actually publish. Local models are
strong at extraction and verification and noticeably weaker at warm, book-length
prose — if the drafts read flat, point the `voice` role at a hosted API (see the
commented block in `models.yaml`) and leave everything else local.

---

## Voice

`voice/exemplars.md` controls tone more than any prompt does. Replace the
placeholders with 3–5 paragraphs **you wrote**. Models match demonstrated
rhythm far better than described rhythm — "be conversational" yields the
generic assistant register; your own paragraphs yield your voice.

`book.yaml` also carries `banned_phrases`. Add to it every time you catch a tic.

---

## Citations

`book.yaml` sets `citation_style`:

- **`chapter`** (default) — one deduplicated source list per chapter, listing
  each doc, the sections drawn on, and the pinned commit. Prose stays clean.
- **`inline`** — per-claim `[^footnote]` markers throughout.

This is presentation only. Claim-level verification runs either way, and the
full audit trail (accepted claims, rejections with reasons, verify verdicts)
always lands in `build/<chapter>.claims.json`.

---

## Growing the corpus

Right now the corpus is opencode's 36 canonical English docs — about 49,500
words, ~70k tokens. That fits in a single context window, which is why there's
no retrieval layer.

**Adding third-party articles and general background material does not break
this**, because of how the stages divide:

- `extract` is the only stage that reads raw sources, and it runs **per batch**
  (`max_source_words` in `book.yaml`, default 12,000). Batches are independent,
  so total corpus size is irrelevant — only a single chapter's declared sources
  matter, and even those get split.
- `draft` never sees raw sources at all. It consumes validated claims, which
  stay compact no matter how large the corpus grows.

So the scaling order is:

1. **Cite finer anchors.** `article.md#specific-section` instead of a whole doc.
   Free, and improves grounding quality.
2. **Lower `max_source_words`.** More batches, each with better recall. Local
   models degrade well before their nominal context limit, so smaller batches
   often *improve* extraction.
3. **Only then consider retrieval** — and prefer selecting whole sections via
   the anchor index over embedding chunks, so citations stay exact.

To add non-opencode sources, drop `.md`/`.mdx` files into `corpus/docs/` with
frontmatter `title:`, and cite them the same way. Two cautions:

- `obook sync` currently overwrites `corpus/docs/` from upstream. Keep added
  material in a separate directory and extend `Corpus` to read both, or vendor
  it after syncing.
- Verbatim quoting of third-party copyrighted material is a different legal
  question from quoting opencode's MIT-licensed docs. The quotes live in
  `claims.json` and the prose paraphrases, which helps — but if you publish,
  that's worth a real look.

---

## Layout

```
book.yaml              global settings, voice bans, citation style
models.yaml            role -> model mapping
corpus/lock.json       pinned commit + per-file hashes (committed)
corpus/docs/           vendored docs (gitignored, from `obook sync`)
chapters/*/chapter.yaml  chapter specs
prompts/               the 10 stage templates — the "skills"
voice/exemplars.md     your writing samples
build/                 generated chapters + claims audit trails
publish/               EPUB/PDF conversion (WIP — see publish/README.md)
obook/                 the tool
```

---

## Pipeline end to end

```
opencode docs  ->  obook sync     pinned corpus
               ->  obook build    grounded chapters (build/*.md)
               ->  obook assemble single manuscript
               ->  publish/       EPUB + PDF
```

Stages 1–3 are working and tested. Stage 4 is documented but unproven against
generated chapters.
