# Releases

How editions of the book are versioned, changelogged, and distributed.

> **Personal-workflow document.** This describes one person's release process
> rather than how the generator works. If the project grows or the process
> changes, this file can be deleted without affecting anything else — the
> workflow, `CHANGELOG.md`, and `scripts/changelog.py` are self-contained.

---

## The model: GitHub Releases on git tags

Tag an edition, attach the built artifacts to a GitHub Release. That is the
native equivalent of "built from source, with a changelog and downloads":
permanent URLs, download counts, and — importantly — the binaries stay **out of
git history**.

An EPUB and PDF run ~14 MB together. Committing those per edition would bloat
the repository permanently and irreversibly. Releases exist precisely to avoid
that.

```
manuscript/*.md   committed   text, diffable, the release source
build/            gitignored  scratch output
*.epub / *.pdf    release     attached to the tag, never committed
```

---

## Two versions that must not be conflated

| What | Where | Moves when |
|---|---|---|
| The **generator** | `pyproject.toml` `version` | code changes |
| The **book edition** | git tags (`v0.1.0`) | chapters change |

These are independent. An upstream docs change produces a new edition with zero
code change; a prompt edit changes the code *and* every chapter. One number for
both would mean nothing in either direction.

Git tags track editions. `pyproject.toml` tracks the tool.

### What the numbers mean

For the book, semver maps reasonably:

| Bump | When |
|---|---|
| **major** | structure changes — chapters reordered, added, or removed |
| **minor** | a chapter is added or substantially rewritten |
| **patch** | corrections, or regeneration with no structural change |

Because the book is derived from a moving upstream, **provenance matters more
than the number.** Every release states the opencode commit it was built from,
and `corpus-lock.json` is attached as an asset so the exact source is
recoverable.

---

## Why generation is not in CI

The `extract → draft → verify → voice` pipeline needs a local model. GitHub
runners have neither the weights nor the memory, and pushing generation to a
hosted API would change what the book is.

The split is clean because the second half is deterministic:

| Stage | Where | Why |
|---|---|---|
| Generate chapters | local | needs a model |
| Sync to `manuscript/` | local | a deliberate "this is worth shipping" decision |
| Assemble + package | CI | pure, reproducible |
| EPUB / PDF | CI *(gated)* | pandoc only, no model — see below |

This is why `manuscript/` is committed while `build/` is not. `build/` is
scratch, overwritten constantly and full of experiments. `manuscript/` is a
decision. Because chapters are text, `git diff v0.1.0..v0.2.0 -- manuscript/`
shows exactly how the prose changed when upstream docs moved — which is
genuinely useful review material.

---

## The changelog writes most of itself

Every generated chapter carries a build stamp:

```json
{ "corpus_commit": "040b8561…", "fingerprint": "80b90c83…",
  "claims_used": 30, "claims_rejected": 0, "models": { … } }
```

`scripts/changelog.py` diffs those stamps between two tags and attributes each
change to a cause:

```
### Changed
- 05-agents-and-subagents — upstream docs 9f2a1c4d → 040b8561; 30 → 34 claims; +180 words
- 08-mcp-servers — prompt or chapter spec changed; -40 words

### Unchanged
- 6 chapters (identical fingerprints): 01-…, 02-…, 03-…, 04-…, 06-…, 07-…
```

Commit messages cannot say that. The fingerprint already computes it; the
script only surfaces it. Treat the output as a **proposal** — paste it into
`CHANGELOG.md` and write a human summary on top.

### The placeholder guard

The script flags any chapter under `--min-words` (default 400) and **exits
non-zero**:

```
WARNING: 7 chapter(s) below 400 words — probable placeholder output, not real prose:
  01-why-harnesses: 25 words
```

Mock runs produce ~25-word chapters. Without this, a release could quietly ship
mock output as a finished book — a real risk, since `opencode-book status`
reports mock and real chapters identically (a valid fingerprint says nothing
about which backend produced it — gap G7).

In CI the check is advisory: it emits a warning rather than failing, because a
placeholder edition is legitimate when labelled as one. v0.1.0 is exactly that.

---

## Cutting a release

```bash
# 1. generate locally (needs a model server on :1234)
opencode-book build
opencode-book assemble

# 2. promote what's worth shipping
scripts/sync-manuscript.sh

# 3. propose the changelog entry, then edit CHANGELOG.md by hand
./.venv/bin/python scripts/changelog.py --version v0.2.0

# 4. tag and push — CI packages and publishes the release
git add manuscript CHANGELOG.md
git commit -m "Book v0.2.0"
git tag v0.2.0
git push --follow-tags
```

`.github/workflows/release.yml` then assembles `manuscript.md`, extracts the
matching `CHANGELOG.md` section as release notes, and attaches:

- `manuscript.md` — the full book as one markdown file
- `corpus-lock.json` — which opencode commit it was built from

`workflow_dispatch` can re-package an existing tag without re-tagging.

### Local alternative

`gh` is not installed here (`brew install gh` fixes that). With it, a release
can be cut without CI:

```bash
gh release create v0.2.0 build/manuscript.md corpus/lock.json \
  --title "opencode-book v0.2.0" --notes-file <(sed -n '/## v0.2.0/,/^## /p' CHANGELOG.md)
```

---

## EPUB and PDF: the pathway, not yet enabled

The `publish` job exists in the workflow with `if: false` and a comment
explaining why.

`publish/` has never been run end to end against generated chapters (gap G5).
Debugging pandoc through CI logs is considerably worse than debugging it in a
local container, and the seven recorded gotchas in `publish/README.md` will all
surface on first run.

**To enable:** run `publish/build.sh` locally, fix what breaks, then change
`if: false` to `needs: package` in the workflow. The steps are already written.

Sequencing this way means v0.1.0 ships something provable today — a markdown
edition with real provenance — instead of blocking on a stage that has never
worked.

---

## v0.1.0, honestly

The first edition is a **proof of concept**: seven placeholder chapters from
the mock server, one real chapter written by hand and served through the replay
harness. It proves the release pathway, not the book.

`CHANGELOG.md` states this in the entry itself rather than in a footnote,
because a release artifact outlives the context it was cut in. Someone finding
that tag in six months should be able to tell immediately that it is not a
book.
