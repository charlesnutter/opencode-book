"""
The per-chapter pipeline.

    extract  -> claims + verbatim quotes          (fast model)
    validate -> literal substring check           (NO model -- see validate.py)
    draft    -> prose from validated claims only  (primary model)
    verify   -> independent support check         (DIFFERENT model)
    voice    -> style pass against exemplars      (voice model)

Correctness and voice are deliberately separate passes. Asking one call to be
simultaneously accurate and charming tends to degrade both, and it makes
failures hard to attribute.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .corpus import Corpus
from .llm import Models
from .validate import (
    Claim,
    ValidationResult,
    validate_claims,
    footnotes,
    source_list,
)

# Roughly 1.35 tokens per word for English prose with code blocks. Only used to
# decide when to split extraction into batches, so approximate is fine.
WORDS_TO_TOKENS = 1.35


@dataclass
class StageOutput:
    name: str
    text: str
    meta: dict


def render(template: str, **vars: str) -> str:
    """Minimal {{name}} substitution -- prompts stay readable as plain markdown."""
    out = template
    for k, v in vars.items():
        out = out.replace("{{" + k + "}}", v)
    return out


class Pipeline:
    def __init__(
        self,
        corpus: Corpus,
        models: Models,
        prompts: dict[str, str],
        book: dict,
        voice_exemplars: str,
    ):
        self.corpus = corpus
        self.models = models
        self.prompts = prompts
        self.book = book
        self.voice_exemplars = voice_exemplars

    # ------------------------------------------------------------- helpers

    def _sources_blob(self, refs: list[str]) -> str:
        return "\n\n".join(self.corpus.excerpt(r) for r in refs)

    def _citation_instruction(self) -> str:
        """How the drafter should mark sources -- presentation only.

        Grounding is enforced upstream by the validator either way; this just
        decides whether the reader sees inline markers or a chapter-end list.
        """
        if str(self.book.get("citation_style", "chapter")).lower() == "inline":
            return (
                "Mark every factual statement with its claim's footnote marker, "
                "e.g. `... runs in a sandbox[^agents-sandbox].` Use the claim id "
                "exactly as given."
            )
        return (
            "Do NOT put citation markers in the prose. Sources are listed once at "
            "the end of the chapter, so the text should read cleanly without "
            "brackets or footnote markers. You must still assert only what the "
            "claims support."
        )

    def _spec_blob(self, spec: dict) -> str:
        objectives = "\n".join(f"- {o}" for o in spec.get("objectives", []))
        return (
            f"Chapter title: {spec.get('title','')}\n"
            f"Audience: {self.book.get('audience','working developers')}\n"
            f"Target length: {spec.get('target_words', 1800)} words\n"
            f"Learning objectives:\n{objectives}"
        )

    # -------------------------------------------------------------- stages

    def batch_refs(self, refs: list[str]) -> list[list[str]]:
        """Split sources into groups that each fit the extraction budget.

        Extraction is the only stage that reads raw sources, and it is
        embarrassingly parallel across them -- so a corpus far larger than any
        context window is handled by batching here. Drafting is unaffected: it
        consumes validated claims, which are compact regardless of corpus size.
        """
        budget = int(self.book.get("max_source_words", 12000))
        batches: list[list[str]] = []
        cur: list[str] = []
        cur_words = 0

        for ref in refs:
            words = len(self.corpus.resolve(ref).full_text.split())
            if words > budget:
                # A single oversized section: give it its own batch and warn
                # via the caller. Better handled by citing finer anchors.
                if cur:
                    batches.append(cur)
                    cur, cur_words = [], 0
                batches.append([ref])
                continue
            if cur and cur_words + words > budget:
                batches.append(cur)
                cur, cur_words = [], 0
            cur.append(ref)
            cur_words += words

        if cur:
            batches.append(cur)
        return batches or [[]]

    def extract(
        self, spec: dict, refs: list[str], log=print
    ) -> tuple[ValidationResult, list[dict]]:
        """Pull claims with verbatim quotes, then validate them in code."""
        system = self.prompts["extract"]
        batches = self.batch_refs(refs)
        if len(batches) > 1:
            log(f"  extract:  {len(refs)} sources -> {len(batches)} batches")

        raw_all: list[dict] = []
        for i, batch in enumerate(batches):
            if not batch:
                continue
            user = render(
                self.prompts["extract_user"],
                spec=self._spec_blob(spec),
                sources=self._sources_blob(batch),
                refs="\n".join(f"- {r}" for r in batch),
            )
            raw = self.models.complete_json("extract", system, user)
            if isinstance(raw, dict):
                raw = raw.get("claims", [])
            if isinstance(raw, list):
                raw_all.extend(x for x in raw if isinstance(x, dict))
            if len(batches) > 1:
                log(f"    batch {i + 1}/{len(batches)}: {len(raw_all)} claims so far")

        # Validate against the full permitted ref set, not just one batch.
        return validate_claims(raw_all, self.corpus, refs), raw_all

    def draft(self, spec: dict, claims: list[Claim]) -> str:
        claim_block = "\n".join(
            f'[{c.id}] {c.claim}\n    evidence: "{c.quote}"\n    source: {c.ref}'
            for c in claims
        )
        system = render(
            self.prompts["draft"],
            voice=self.voice_exemplars,
            citation_instruction=self._citation_instruction(),
        )
        user = render(
            self.prompts["draft_user"],
            spec=self._spec_blob(spec),
            claims=claim_block,
        )
        return self.models.complete("draft", system, user)

    def verify(self, draft_text: str, claims: list[Claim]) -> list[dict]:
        """Independent check that each cited paragraph is actually supported."""
        claim_block = "\n".join(
            f'[{c.id}] {c.claim}\n    evidence: "{c.quote}"' for c in claims
        )
        system = self.prompts["verify"]
        user = render(
            self.prompts["verify_user"], draft=draft_text, claims=claim_block
        )
        out = self.models.complete_json("verify", system, user)
        if isinstance(out, dict):
            out = out.get("issues", [])
        return out if isinstance(out, list) else []

    def voice(self, spec: dict, draft_text: str) -> str:
        system = render(
            self.prompts["voice"],
            voice=self.voice_exemplars,
            banned="\n".join(f"- {b}" for b in self.book.get("banned_phrases", [])),
        )
        user = render(self.prompts["voice_user"], spec=self._spec_blob(spec), draft=draft_text)
        return self.models.complete("voice", system, user)

    # ---------------------------------------------------------------- runner

    def run(
        self,
        spec: dict,
        refs: list[str],
        *,
        skip_voice: bool = False,
        max_revisions: int = 1,
        log=print,
    ) -> dict:
        result, raw_claims = self.extract(spec, refs, log=log)
        log(f"  extract:  {result.summary()}")
        for c, why in result.rejected:
            log(f"    rejected [{c.id}]: {why}")

        if not result.accepted:
            raise RuntimeError(
                "No claims survived validation -- nothing can be written without "
                "grounded sources. Check that the model returns verbatim quotes."
            )

        body = self.draft(spec, result.accepted)
        log(f"  draft:    {len(body.split())} words")

        issues: list[dict] = []
        for attempt in range(max_revisions + 1):
            issues = self.verify(body, result.accepted)
            unsupported = [i for i in issues if str(i.get("verdict", "")).lower() != "supported"]
            log(f"  verify:   {len(unsupported)} unsupported passage(s)")
            if not unsupported or attempt == max_revisions:
                break
            log("  revising unsupported passages...")
            fix_user = render(
                self.prompts["revise_user"],
                draft=body,
                issues=json.dumps(unsupported, indent=2),
            )
            body = self.models.complete("draft", self.prompts["revise"], fix_user)

        if not skip_voice:
            body = self.voice(spec, body)
            log(f"  voice:    {len(body.split())} words")

        commit = self.corpus.lock["commit"]
        if str(self.book.get("citation_style", "chapter")).lower() == "inline":
            notes = footnotes(result.accepted, self.corpus, commit)
        else:
            notes = source_list(result.accepted, self.corpus, commit)
        markdown = f"{body.strip()}\n\n---\n\n## Sources\n\n{notes}\n"

        return {
            "markdown": markdown,
            "claims": [c.__dict__ for c in result.accepted],
            "rejected": [{"claim": c.__dict__, "reason": w} for c, w in result.rejected],
            "issues": issues,
            "raw_claim_count": len(raw_claims),
        }
