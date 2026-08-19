# Documentation

How this project generates a book from opencode's documentation, what has
actually been run, and what has not.

| Document | What it covers |
|---|---|
| [01-build-process.md](01-build-process.md) | The production pipeline: sync → build → assemble → publish |
| [02-poc-replay-process.md](02-poc-replay-process.md) | The replay walkthrough used to prove the pipeline without a local model |
| [03-gaps-and-mitigations.md](03-gaps-and-mitigations.md) | Known gaps, ranked, with recommended fixes |
| [04-next-steps.md](04-next-steps.md) | Ordered next actions |

## The two processes, and how they relate

It's worth being precise about this, because it's easy to remember it wrong.

**There is one build process.** The POC did not fork it or replace it. The
pipeline code that ran during the walkthrough is the same code that will run in
production — same corpus loader, same validator, same fingerprinting, same
output writer.

What changed for the POC was **the model backend**. Every stage talks to an
OpenAI-compatible HTTP endpoint, so the walkthrough pointed that endpoint at a
*replay server* serving hand-authored responses instead of at a local model.
From the pipeline's perspective nothing was different.

```
                          ┌─ production:  MLX / LM Studio / Ollama / hosted API
opencode-book build ──HTTP──────► │
                          └─ POC:         tools/replay/server.py
```

Two changes *were* made permanently, and they are part of the production
process now — they were motivated by POC economics but are not POC-only:

1. **One model for all four roles.** The differentiated setup named three models
   totalling ~69 GB against a 64 GB ceiling, so they could never all stay
   resident. See [01](01-build-process.md#models) and
   [03](03-gaps-and-mitigations.md#g3-shared-model-weakens-the-verify-stage).
2. **Stage-major builds.** Every chapter through `extract`, then every chapter
   through `draft`, rather than each chapter through the whole pipeline in turn.
   Cuts model loads from 4×chapters to 4 per run.

## Status at a glance

| Stage | State |
|---|---|
| Corpus sync | Working. 36 docs, 49,468 words, pinned at `040b8561` |
| Chapter specs | 8 written, all source refs verified to resolve |
| extract → validate → draft → verify → voice | Working. Proven end to end on chapter 05 |
| Publish (EPUB/PDF) | **Not run.** Documented approach only — see `publish/README.md` |
| Real local model | **Never used.** Every run so far has been mock or replay |

The single largest untested assumption is that a local model can produce prose
you would actually publish. Nothing here has tested that yet.
