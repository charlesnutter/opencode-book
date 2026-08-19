# Agent guidelines

Instructions for an agent working on **opencode-book** — a build system that generates a
how-to book about opencode from official documentation and third-party sources,
with every factual claim machine-checked against its source.

Read `documentation/` for how the system works. This file is about how to *work
on* it.

> Every rule here traces back to something that actually went wrong during this
> project. When something new goes wrong, add a rule rather than remembering it.
> A rule you cannot trace to a real failure is probably noise — delete it.

---

## 1. Non-negotiables

These are the invariants. Breaking one produces a book that looks fine and is
quietly wrong, which is worse than an obvious failure.

1. **The drafter never sees raw sources.** It receives validated claims only.
   This is what stops it "remembering" a flag that does not exist.
2. **Validation is code, never a model.** `opencode_book/validate.py` asserts each quote
   is a literal substring of its cited source. Do not add fuzzy matching, edit
   distance, or "close enough" thresholds. The value of the check is that it
   cannot itself hallucinate.
3. **Never weaken a check to make a run pass.** If validation rejects most
   claims, the extraction is wrong. Fix the prompt, not the validator.
4. **Every factual sentence traces to a claim.** Connective tissue, motivation,
   and analogy are free. Product facts are not.
5. **Never invent to fill a gap.** If the sources do not cover a step, write
   around the gap and flag it. A chapter with an honest hole beats a chapter
   with a fabricated flag.

---

## 2. Verification discipline

Most errors in this project came from asserting something plausible without
checking. The pattern repeated often enough to warrant its own section.

| Rule | What went wrong |
|---|---|
| Verify a negative result with a second method before relying on it | A Unicode box-drawing scan returned empty, so the corpus was declared "pure ASCII". It wasn't — 16 files used box-drawing characters, and the first diagram pass silently mangled them |
| Do not trust your own verification regex | A `grep '^## User'` check appeared to find leaked content; the matches were inside fenced tool output. Verify the verifier before acting on it |
| Check for primary sources on disk before reconstructing from memory | A session transcript was about to be rebuilt from recollection. The real JSONL was sitting in `~/.claude/projects/` |
| Run the diagnostic, don't estimate from it | Two chapters were reported as under-sourced. Running the preflight showed six of eight exceeded their targets |
| Verify version and identity claims against primary sources | SEO "best local LLM 2026" articles confidently named Qwen3.6, Gemma 4, and GLM 5.2. None appear in HuggingFace download data. Use the HF API or the official repo, never a listicle |
| Re-check upstream identity periodically | opencode moved from `sst/opencode` to `anomalyco/opencode`. URLs rot |

When you state a fact in a commit message, a doc, or to the user, you should be
able to name the command that established it.

---

## 3. Corpus rules

### Official documentation

- Sync with `opencode-book sync`. It pins a commit into `corpus/lock.json`; that pin is
  what makes citations permanent.
- **Only top-level `.mdx` files are canonical English.** Anything one level
  deeper is a locale translation. There are 17 locales — including them inflates
  the corpus ~17× for nothing.
- Never hand-edit `corpus/docs/`. It is regenerated and gitignored.
- There is deliberately **no retrieval layer**. The corpus is ~70k tokens and
  fits in context. Do not add a vector store — it is the most failure-prone
  component in a typical doc pipeline and this corpus does not need it.

### Third-party sources

The book is expected to draw on articles and general background material, not
just opencode's docs. Rules for that:

1. **Put them in `corpus/external/`, never `corpus/docs/`.** `opencode-book sync`
   overwrites `corpus/docs/` wholesale — anything you add there is destroyed on
   the next sync.
2. **Require frontmatter**: `title:`, `source_url:`, `retrieved:`, and
   `license:` (or `license: unknown`). Without `source_url` the citation cannot
   resolve and the material is unusable.
3. **Snapshot, don't hotlink.** Store the text locally so quotes stay verifiable
   when the page changes or disappears.
4. **Keep third-party quotes short.** Verbatim quotes live in `claims.json` for
   verification; the prose should paraphrase and attribute. Quoting opencode's
   MIT-licensed docs at length is fine. Quoting someone's blog at length is a
   different question, and this repo is public.
5. **Record the license per source.** `license: unknown` is a valid value and a
   signal to paraphrase rather than quote.
6. **Never mix an unlicensed source into a chapter silently.** If a chapter
   depends on material you cannot license, say so in the chapter's `notes:`.

### Licensing, stated plainly

| Thing | License | Implication |
|---|---|---|
| opencode source and docs (`anomalyco/opencode`) | MIT | Safe to quote and build on, with attribution |
| This repo's code | MIT (`LICENSE`) | Yours |
| The *Deep Dive into OpenCode* community book | **none — all rights reserved** | Do not redistribute its text. It was the model for the publish pipeline, not a source |
| Third-party articles | varies | Check per source; default to paraphrase |

A software license does not extend to a book written *about* that software.
These are separate works with separate rights holders.

---

## 4. Chapter specs

- Sources are `doc#anchor` refs, never free text. Find them with
  `opencode-book anchors --doc agents.mdx`.
- **Verify every ref resolves before spending model time.** A bad ref fails the
  build; catching it earlier is cheaper.
- **Treat `target_words` as a ceiling, not a quota.** A target far above the
  available source words guarantees padding or invention. Ratios up to ~1.5×
  are healthy — good prose expands on sources with explanation. Beyond that,
  either widen `sources` or lower the target.

```bash
# preflight: catch targets that exceed their sources
./.venv/bin/python -c "
import yaml
from pathlib import Path
from opencode_book.corpus import Corpus
c = Corpus(Path('corpus'))
for d in sorted(Path('chapters').iterdir()):
    s = yaml.safe_load((d/'chapter.yaml').read_text())
    w = sum(len(c.resolve(r).full_text.split()) for r in s.get('sources') or [])
    t = s.get('target_words', 0)
    if t > w * 1.5: print(f'{d.name}: target {t} vs source {w} — will pad or invent')
"
```

---

## 5. Extraction and claims

- **Capture fenced code blocks as claims.** The first extract pass on chapter 05
  returned 26 claims and zero code examples, leaving the drafter unable to write
  a single config snippet without inventing JSON structure. For a how-to book
  that is fatal, and it is invisible until you notice nothing is runnable.
- **A claim must not assert more than its quote establishes.** Validation checks
  that a quote *exists*, not that the claim *follows from it*. Two claims passed
  validation with real quotes attached while their text overreached:
  - "file edits and bash default to `ask`" — the quote said "all of the
    following are set to `ask`:" without naming the items
  - "placed globally or per project" — the quote stopped before the paths
  If the quote refers to a list by reference, quote the list too or narrow the
  claim.
- Quotes must be **character-exact**. Em-dashes, curly apostrophes and inline
  backticks in opencode's docs are the usual failure points. Do not normalise
  them.
- Prefer fewer solid claims to more shaky ones.

---

## 6. Verification

- `verify` should run on a **different model** than `draft`. A model is a poor
  auditor of its own output. When they share a model — the current POC posture —
  treat verify results as weaker evidence than the logs suggest.
- The verify stage is the only real entailment check in the system. Do not
  disable it to speed up a run.
- Strongest verification available for a how-to book about a CLI is
  **execution**: extract every command and config block and run it in a
  container. Textual grounding proves the book matches the docs; execution
  proves it matches reality, and catches docs that are themselves stale.

---

## 7. Models and hardware

Target machine: **M5 Pro, 64 GB unified memory, 307 GB/s**.

- **Sum the resident set against the ceiling before proposing a model lineup.**
  A three-model config was specified totalling ~69 GB against a 64 GB limit —
  they could never all stay resident, and every role change evicted weights to
  disk.
- **Prefer MoE over dense.** Dense models are bandwidth-bound (every parameter
  read per token); MoE activates ~3B per token and sidesteps that wall. The
  effect is large enough on Pro-tier silicon that an M4 Pro can beat an M3 Ultra
  on an 80B MoE despite a third the bandwidth.
- **Builds are stage-major**: every chapter through `extract`, then every chapter
  through `draft`. Chapter-major ordering makes each role change a model change,
  turning 4 model loads into 4×chapters. Use `--chapter-major` only to debug a
  single chapter.
- Roles are indirection: stages ask for a role, never a model name. Keep it that
  way so swapping stays a config edit.
- **The voice stage is the weakest link for local models** and the first role
  worth pointing at a hosted API.

---

## 8. Voice and tone

- The audience is working developers. Approachable and conversational — a
  colleague explaining something at a whiteboard, not a spec.
- **Voice is controlled by exemplars, not adjectives.** "Be conversational"
  produces the generic assistant register. `voice/exemplars.md` must contain
  paragraphs the author actually wrote.
- `voice/exemplars.md` currently holds **placeholders**. Any output generated
  against them inherits a borrowed voice. Replace before generating anything
  intended to be kept.
- Add to `banned_phrases` in `book.yaml` whenever a tic surfaces. Cheaper than
  editing prose by hand.
- The voice pass may not change facts, touch code blocks, or add citations.

---

## 9. Citations

- Default is `citation_style: chapter` — one deduplicated source list per
  chapter. **This is presentation only.** Claim-level verification runs
  regardless, and the audit trail always lands in `build/<chapter>.claims.json`.
- Do not "simplify" by removing claim-level grounding. The reader-facing format
  and the verification mechanism are independent; conflating them was an early
  over-engineering mistake.
- Every citation resolves to both a live URL and a pinned commit blob.

---

## 10. Publishing

`publish/` is **work in progress and has never been run** against generated
chapters. Read `publish/README.md` before touching it — its seven recorded
gotchas are confirmed findings that will recur on a fresh machine:

Debian's `epubcheck` package ships a broken launcher; `@page` paged-media CSS
fails epubcheck and must live in `style-print.css`; `--include-before-body`
multiplies across every chapter of an EPUB; an image-only section emits an empty
`<h1>` that fails nav validation; a `title:` in metadata emits a stray header
ahead of the PDF cover; print pages are narrower than Kindle reflow width; and
pandoc resolves relative image paths against its working directory, not each
file's location.

General rules learned here:

- **Use absolute paths for generated assets.** Relative paths computed per-file
  break the moment files from several directories are concatenated.
- **Match thresholds to the output medium.** A code-width threshold safe for
  Kindle reflow wrapped mid-diagram in a 6.5in PDF.
- **Consider pagination when rasterizing.** A 116-line tree became a 4581px-tall
  image that could not paginate; it was better left as text.
- Verify where output actually landed. A hardcoded path once wrote the build
  into the repo root instead of the build directory.

---

## 11. Shell and tooling hazards

Small things that cost real time:

- **Check whether a path is a symlink before redirecting into it.**
  `> /usr/bin/epubcheck` followed the symlink and destroyed the jar it pointed
  at. Remove the link first.
- **Restart stateful test harnesses between runs.** `tools/replay/server.py`
  counts verify calls; a stale server made the revision loop appear not to fire.
- Use `KeyError` only for lookups. Its `__str__` returns `repr(arg)`, which
  escapes newlines and mangles multi-line "did you mean" messages. Define a
  dedicated exception instead.
- `argparse` treats a value beginning with `-` as a flag. Use `--opt=value`.
- setuptools auto-discovery claims content directories as packages. Keep
  `packages = ["opencode-book"]` pinned in `pyproject.toml`.

---

## 12. Working style

- **Mark uncertainty explicitly.** When something is unproven, say so where it
  cannot be missed — at the top of the file, not in a footnote. `publish/` is
  labelled WIP for exactly this reason.
- **Distinguish "documented" from "verified".** State plainly which stages have
  actually run and which have not.
- **Prefer the simpler thing the user asked for.** Chapter-level source lists
  were requested over inline footnotes; the inline machinery was more than the
  job needed.
- **Report failures with their output.** If a check fails, show it. If a step
  was skipped, say so.
- **Surface findings that contradict earlier statements**, including your own.
  Correcting "two chapters are thin" to "six of eight exceed their targets" was
  more valuable than the original claim.
- Do not spawn subagents for work that can be done inline.

---

## 13. Git conventions

- **Never add `Co-Authored-By`, "Generated with", or any model attribution** to
  commit messages or PR bodies. Describe the change only. This is about log
  signal-to-noise, not about hiding tooling — the agents files stay in-repo.
  (Subject matter is fine: "using local models" is a description of the project,
  not an attribution.)
- Commit messages explain *why*, not just what. Record the failure a fix
  addresses.
- **Inspect a remote before any force push.** The remote here already held a
  `LICENSE`; force-pushing would have destroyed it. Rebasing preserved it.
- **Review what a broad `git add` staged** before committing, and scan for
  secrets before pushing — this repo is public.
- Keep out of version control: session transcripts (`sessions/`), vendored docs
  (`corpus/docs/`), build outputs (`build/`), publishing assets
  (`publish/assets/`), and harness debug dumps.

---

## 14. Known state

Check `documentation/03-gaps-and-mitigations.md` for the ranked list. The three
that matter most:

1. **No local model has ever run.** Every execution so far has been mock or
   replay. Whether a local model can produce publishable prose is the central
   untested assumption.
2. **`voice/exemplars.md` is placeholder text.**
3. **`build/` mixes one real chapter with seven mock placeholders**, and
   `opencode-book status` calls them all `ok` — a valid fingerprint says nothing about
   which backend produced it. Clear the directory when switching backends.

---

## 15. Interoperability standards

The goal is that someone can move between Claude Code, opencode, and other
harnesses without rewriting configuration. Most of that is now settled by open
standards — do not invent local conventions where one already exists.

| Layer | Standard | Governance |
|---|---|---|
| Instructions | **AGENTS.md** — <https://agents.md> | Linux Foundation / Agentic AI Foundation |
| Skills | **Agent Skills** (`SKILL.md`) — <https://agentskills.io> | Anthropic-originated, open spec |
| Packaging | **Agent Plugins 1.0** — <https://github.com/agentplugins/agent-plugins-spec> | AAIF (Amazon, Cursor, Microsoft, OpenAI, Vercel) |
| Tools | **MCP** | AAIF |
| Subagents | *none* | — |

### The distinction that causes confusion

**Agent Skills standardizes the skill *format*, not the *discovery location*.**
The spec defines the folder layout and frontmatter; it says nothing about where
clients look. That is why opencode searches six paths and Claude Code searches
one, and why a neutral directory plus a symlink is a real fix rather than a
workaround. Expect the same split in any future "standard": check whether it
covers format, location, or both.

`SKILL.md` frontmatter, per the spec:

| Field | Required | Notes |
|---|---|---|
| `name` | yes | ≤64 chars, lowercase/digits/hyphens, must match the parent directory name |
| `description` | yes | ≤1024 chars; state what it does *and* when to use it |
| `license` | no | name or bundled file reference |
| `compatibility` | no | ≤500 chars; environment requirements |
| `metadata` | no | arbitrary string map |
| `allowed-tools` | no | space-separated; experimental, support varies |

Keep `SKILL.md` under ~500 lines and push detail into `references/` — agents load
skills progressively (name + description at startup, body on activation,
resources on demand), so a bloated `SKILL.md` costs context on every task.

### Subagents have no standard

Both tools use markdown with YAML frontmatter, but the schemas differ:

| | Claude Code | opencode |
|---|---|---|
| Fields | `name`, `description`, `tools`, `model`, `permissionMode`, `maxTurns`, `skills` | `description`, `mode`, `model`, `permission`, `temperature` |

Agent Plugins 1.0 standardizes exactly two component types — Agent Skills and
MCP servers — and deliberately leaves subagents out. Treat that as the
ecosystem's current answer, not an oversight to route around.

**Rule: write subagent definitions to the intersection.** `description` and
`model` mean the same thing in both. Stick to those and symlink one directory to
the other. Accept that per-tool tuning (`tools` vs `permission`) does not
transfer, and do not build a translation layer for a format that is still
moving.

### Caveats

- **Portable is not verified.** A skill that loads everywhere does not behave
  identically everywhere. Test against each harness you claim to support.
- **Agent Plugins 1.0 has no security model** — no permissions, sandboxing,
  signature checks, or secrets handling. All listed as future work. Fine for
  distributing your own work; a real consideration before installing others'.
- **Re-check this section periodically.** Every standard in the table postdates
  mid-2025, and two of them shipped within the last nine months.

---

## Layout note

Instruction files, skills, and agent definitions live in **three different
places**. Conflating them is an easy mistake — an `AGENTS.md` tucked inside a
folder is read by nothing.

### This file

Root-level, and the single source of truth:

```
AGENTS.md            <- the real file, edit this   (opencode)
CLAUDE.md            -> AGENTS.md                  (Claude Code)
```

opencode finds `AGENTS.md` by walking up from the working directory to the git
worktree. Claude Code reads `CLAUDE.md`. One symlink keeps them identical.

### Skills

opencode searches six locations, one of which is tool-neutral:

```
.opencode/skills/<name>/SKILL.md     opencode-specific
.claude/skills/<name>/SKILL.md       Claude-compatible
.agents/skills/<name>/SKILL.md       agent-compatible   <- prefer this
```

(plus `~/.config/opencode/`, `~/.claude/` and `~/.agents/` globals.)

Put skills in **`.agents/skills/<name>/SKILL.md`** — note the leading dot.
opencode reads that natively, so no symlink is needed for it. Claude Code only
looks in `.claude/skills/`, so that path symlinks back:

```
.agents/skills/         <- the real directory
.claude/skills          -> ../.agents/skills
```

### Agent definitions

A third location again, and the one case with **no `.agents/` equivalent**:

| Tool | Project | Global |
|---|---|---|
| Claude Code | `.claude/agents/` | `~/.claude/agents/` |
| opencode | `.opencode/agents/` | `~/.config/opencode/agents/` |

Both take markdown with YAML frontmatter, and both let the filename or a `name`
field become the agent name — but the frontmatter schemas differ (Claude Code
uses `name`/`description`/`tools`/`model`; opencode uses
`description`/`mode`/`model`/`permission`). They are **not** blindly
interchangeable, so symlink one directory to the other only if the definitions
you write stay within the fields both understand.

Claude Code resolves conflicts by precedence: managed settings, then `--agents`
CLI flag, then `.claude/agents/`, then `~/.claude/agents/`, then plugin
directories. Nested project dirs are allowed and the definition closest to the
working directory wins.

None exist yet. `prompts/` holds the pipeline's stage templates, which are not
agent definitions — they are inputs to `opencode-book`, not files any tool discovers.
