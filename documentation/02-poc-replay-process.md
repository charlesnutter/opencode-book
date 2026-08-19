# The POC: replay walkthrough

How chapter 05 was generated end to end without a local model, what it proved,
and how to reproduce it.

## What this was

Every pipeline stage talks to an OpenAI-compatible HTTP endpoint. That makes the
model backend swappable — including for a backend that isn't a model at all.

The walkthrough pointed `models.yaml` at a **replay server** that returns
hand-authored stage responses. The pipeline code was not modified, mocked, or
bypassed. Real corpus loading, real prompt rendering, real validation, real
fingerprinting, real source-list generation, real output writing.

```
obook build 05-agents ──HTTP──► tools/replay/server.py ──► hand-authored responses
```

The point was to test the *machinery* while removing the model as a variable. If
the validator was going to reject a badly-copied quote, it needed a chance to do
so against genuinely hand-copied quotes.

## Why chapter 05

`05-agents-and-subagents`: 13 refs, 1,872 words of source. The best available
candidate. Chapters 04 (611 words) and 07 (355 words) would have looked like
pipeline failures when the real problem is source-material shortage.

---

## Step 1 — Dump the source sections

```bash
./.venv/bin/python -c "
import yaml
from pathlib import Path
from obook.corpus import Corpus
c = Corpus(Path('corpus'))
spec = yaml.safe_load(Path('chapters/05-agents-and-subagents/chapter.yaml').read_text())
for r in spec['sources']:
    s = c.resolve(r)
    print('='*70); print('REF:', s.ref, '| TITLE:', s.title); print('='*70)
    print(s.full_text); print()
" > /tmp/ch05_sources.txt
```

535 lines. This is exactly what the `extract` stage would receive.

## Step 2 — Author the extract response by hand

26 claims written into `tools/replay/extract.json`, each with a quote copied
character-by-character from the dump:

```json
{
  "id": "primary-direct",
  "claim": "Primary agents are the ones you talk to directly, and you switch between them with Tab or the switch_agent keybind.",
  "quote": "Primary agents are the main assistants you interact with directly. You can cycle through them using the **Tab** key, or your configured `switch_agent` keybind.",
  "ref": "agents.mdx#primary-agents"
}
```

The transcription hazards here are real: opencode's docs contain em-dashes,
curly apostrophes, and inline backticks. Any of those silently altered fails the
substring check.

## Step 3 — Validate before drafting

```bash
./.venv/bin/python -c "
import json, yaml
from pathlib import Path
from obook.corpus import Corpus
from obook.validate import validate_claims
c = Corpus(Path('corpus'))
spec = yaml.safe_load(Path('chapters/05-agents-and-subagents/chapter.yaml').read_text())
r = validate_claims(json.load(open('tools/replay/extract.json')), c, spec['sources'])
print(r.summary())
for cl, why in r.rejected:
    print('REJECT', cl.id, '-', why)
"
```

```
26/26 claims validated (100%)
```

All 26 quotes were genuinely verbatim. That number only means something because
the check would have caught any that weren't.

## Step 4 — Fix a real gap: no code examples

The 26 claims contained **zero code blocks**. A drafter obeying its own rules —
*"do NOT introduce facts absent from the claims"* — therefore could not write a
single config snippet without inventing JSON structure. For a how-to book that
is fatal.

The fix is to extract code blocks as claims too. Done programmatically to
guarantee the quotes are exact:

```bash
./.venv/bin/python - <<'PY'
import json, sys
sys.path.insert(0, '.')
from pathlib import Path
from obook.corpus import Corpus
c = Corpus(Path('corpus'))

def block(ref, start, end=None):
    t = c.resolve(ref).full_text
    i = t.index(start)
    j = t.index(end, i) + len(end) if end else len(t)
    return t[i:j]

extra = [{
    "id": "json-example",
    "claim": "A JSON agent block nests each agent under an agent key, with its settings inside.",
    "quote": block("agents.mdx#model", '{\n  "agent": {\n    "plan"', '}\n}'),
    "ref": "agents.mdx#model",
}]
claims = json.load(open('tools/replay/extract.json'))
claims.extend(extra)
json.dump(claims, open('tools/replay/extract.json','w'), indent=2)
PY
```

Four code-block claims added → **30 claims total**. This gap is now
[G2](03-gaps-and-mitigations.md#g2-extract-prompt-does-not-ask-for-code-blocks).

## Step 5 — Author draft, verify, and revision responses

- `draft.md` — the chapter, written from the 30 validated claims only, following
  `prompts/draft.md` rules: no `h1`, `##` subheads, no preamble or summary
  paragraph, no inline citation markers (`citation_style: chapter`).
- `verify.json` — the audit. Two passages flagged `unsupported` (below).
- `revise.md` — the draft with those two passages weakened.
- `verify2.json` — the second audit, clean.
- `voice.md` — the polished final.

### What the audit caught

Two genuine overreaches in prose I had written myself:

| Draft said | Evidence actually said | Verdict |
|---|---|---|
| "By default it sets **file edits and bash commands** to `ask`" | "By default, all of the following are set to `ask`:" — the items are not in the quote | unsupported |
| "placed **either globally or per project**, in an agents directory" | "You can also define agents using markdown files. Place them in:" — quote stops before the paths | unsupported |

Both claims had passed validation, because their *quotes* were real. The claim
*text* overreached what the quote established. This is the limitation the verify
stage exists to catch, and it did.

## Step 6 — The replay server

`tools/replay/server.py` dispatches on the system prompt and logs what each
stage received:

```python
if "extract verifiable claims" in s:  return read("extract.json")
if "audit a draft chapter" in s:
    _verify_calls += 1
    return read("verify.json" if _verify_calls == 1 else "verify2.json")
if "repair specific passages" in s:   return read("revise.md")
if "line editor" in s:                return read("voice.md")
return read("draft.md")
```

The verify counter is **stateful across runs**. Restart the server before each
replay or the second pass serves `verify2.json` immediately and the revision
loop appears not to fire. This bit during testing.

## Step 7 — Run it

```bash
lsof -ti:1234 | xargs kill -9 2>/dev/null       # ensure a clean server
./.venv/bin/python tools/replay/server.py 1234 &
rm -f build/05-agents-and-subagents.*
./.venv/bin/obook build 05-agents --force
```

```
05-agents-and-subagents: building (13 sources)
  extract:  30/30 claims validated (100%)
  draft:    1557 words
  verify:   2 unsupported passage(s)
  revising unsupported passages...
  verify:   0 unsupported passage(s)
  voice:    1556 words
05-agents-and-subagents: wrote build/05-agents-and-subagents.md
```

Server log, with real payload sizes per stage:

```
[extract] system=1325c user=16434c
[draft]   system=3333c user=8193c
[verify]  system=960c  user=16058c
[revise]  system=548c  user=10151c
[verify]  system=960c  user=16048c
```

Note the shape: `extract` gets 16 KB of raw source; `draft` gets 8 KB of
*claims*. That asymmetry is what lets the corpus grow without the drafter caring.

## What came out

`build/05-agents-and-subagents.md` — ~1,560 words, with a build stamp:

```json
{
  "corpus_commit": "040b8561400fcbe84eaf8d045ede46fc014e2d00",
  "claims_used": 30,
  "claims_rejected": 0,
  "fingerprint": "80b90c83..."
}
```

and a chapter-level source list:

```markdown
## Sources

- **Agents** — https://opencode.ai/docs/agents
  - Sections: Types, Primary agents, Subagents, Built-in, Usage, Configure,
    JSON, Markdown, Model, Prompt, Permissions, Max steps
  - Pinned at commit `040b8561`
```

Both revisions are present in the final artifact, and `obook status` reports the
chapter `ok`.

---

## What this proved, and what it did not

**Proved:**

- The validator works, and distinguishes fabricated from miscited quotes.
- The verify → revise → re-verify loop fires and its corrections persist.
- Fingerprinting, staleness, and the chapter-level source list all work.
- Code examples flow through correctly *once extracted as claims*.

**Did not prove:**

- That a local model can produce publishable prose. I wrote the draft. This is
  the central untested assumption of the whole project.
- That a local model can return strict JSON reliably, or copy quotes verbatim
  under pressure. My 100% extract rate says nothing about a 30B model's rate.
- That the publish stage works at all.

## Reproducing

Everything needed is committed under `tools/replay/`. Restart the server first —
the verify counter is stateful.

```bash
lsof -ti:1234 | xargs kill -9 2>/dev/null
./.venv/bin/python tools/replay/server.py 1234 &
./.venv/bin/obook build 05-agents --force
lsof -ti:1234 | xargs kill -9
```
