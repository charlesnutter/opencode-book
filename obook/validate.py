"""
Claim validation -- pure code, no model in the loop.

This is the highest-leverage component in the pipeline. The extract stage is
required to return, for every claim, a *verbatim* quote plus the source ref it
came from. Here we assert that quote genuinely appears in that source file.

Because the check is a string comparison rather than a model judgement, it
cannot itself hallucinate. Published citation-hallucination rates for LLMs run
roughly 11-57%; a literal substring assertion collapses the fabricated-citation
class to approximately zero, and does it in microseconds.

Whitespace is normalised (models reflow line breaks in long quotes), but
nothing else is: no fuzzy matching, no edit-distance thresholds, no
"close enough". A quote either exists in the source or the claim is rejected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .corpus import Corpus

WS_RE = re.compile(r"\s+")

MIN_QUOTE_CHARS = 12


def normalize(text: str) -> str:
    """Collapse whitespace so reflowed quotes still match; change nothing else."""
    return WS_RE.sub(" ", text).strip()


@dataclass
class Claim:
    id: str
    claim: str
    quote: str
    ref: str

    @classmethod
    def from_obj(cls, obj: dict, index: int) -> "Claim":
        return cls(
            id=str(obj.get("id") or f"c{index + 1}"),
            claim=str(obj.get("claim", "")).strip(),
            quote=str(obj.get("quote", "")).strip(),
            ref=str(obj.get("ref", "")).strip(),
        )


@dataclass
class ValidationResult:
    accepted: list[Claim] = field(default_factory=list)
    rejected: list[tuple[Claim, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected

    def summary(self) -> str:
        total = len(self.accepted) + len(self.rejected)
        if not total:
            return "no claims returned"
        pct = 100.0 * len(self.accepted) / total
        return f"{len(self.accepted)}/{total} claims validated ({pct:.0f}%)"


def validate_claims(
    claims_raw: list[dict],
    corpus: Corpus,
    allowed_refs: list[str],
) -> ValidationResult:
    """Accept only claims whose quote is literally present in a cited source."""
    result = ValidationResult()
    allowed = set(allowed_refs)

    # Pre-normalise each permitted source once.
    source_text: dict[str, str] = {}
    for ref in allowed_refs:
        try:
            source_text[ref] = normalize(corpus.resolve(ref).full_text)
        except KeyError:
            # A bad ref in the chapter spec is a config error, surfaced by build.
            source_text[ref] = ""

    seen_ids: set[str] = set()

    for i, obj in enumerate(claims_raw if isinstance(claims_raw, list) else []):
        if not isinstance(obj, dict):
            continue
        c = Claim.from_obj(obj, i)

        if not c.claim:
            result.rejected.append((c, "empty claim"))
            continue
        if not c.quote:
            result.rejected.append((c, "empty quote"))
            continue
        if len(normalize(c.quote)) < MIN_QUOTE_CHARS:
            result.rejected.append(
                (c, f"quote shorter than {MIN_QUOTE_CHARS} chars (too weak to verify)")
            )
            continue
        if c.ref not in allowed:
            result.rejected.append(
                (c, f"ref {c.ref!r} is not among this chapter's declared sources")
            )
            continue

        needle = normalize(c.quote)
        haystack = source_text.get(c.ref, "")

        if needle in haystack:
            if c.id in seen_ids:
                c.id = f"{c.id}-{i}"
            seen_ids.add(c.id)
            result.accepted.append(c)
            continue

        # Not in the cited source. Report if it came from a different one --
        # a miscited real quote is a different bug from an invented one.
        found_in = next(
            (r for r, t in source_text.items() if r != c.ref and needle in t),
            None,
        )
        reason = (
            f"quote not found in {c.ref} (it appears in {found_in} -- miscited)"
            if found_in
            else f"quote not found verbatim in {c.ref} (fabricated or paraphrased)"
        )
        result.rejected.append((c, reason))

    return result


def footnotes(claims: list[Claim], corpus: Corpus, commit: str) -> str:
    """Per-claim footnotes, for citation_style: inline."""
    lock_repo = corpus.lock["repo"]
    docs_path = corpus.lock["docs_path"]
    lines = []
    for c in claims:
        s = corpus.resolve(c.ref)
        pin = f"https://github.com/{lock_repo}/blob/{commit}/{docs_path}/{s.doc}"
        lines.append(
            f"[^{c.id}]: {s.title} — [{s.site_url}]({s.site_url}) "
            f"([pinned source]({pin}))"
        )
    return "\n".join(lines)


def source_list(claims: list[Claim], corpus: Corpus, commit: str) -> str:
    """Chapter-level source list, for citation_style: chapter (the default).

    Groups the validated claims by document and lists each document once with
    the specific sections drawn on. Verification still happens per claim -- this
    only changes what the reader sees.
    """
    lock_repo = corpus.lock["repo"]
    docs_path = corpus.lock["docs_path"]

    by_doc: dict[str, list[Claim]] = {}
    for c in claims:
        by_doc.setdefault(corpus.resolve(c.ref).doc, []).append(c)

    lines = []
    for doc in sorted(by_doc):
        doc_sec = corpus.sections()[doc]
        pin = f"https://github.com/{lock_repo}/blob/{commit}/{docs_path}/{doc}"

        seen, sections = set(), []
        for c in by_doc[doc]:
            s = corpus.resolve(c.ref)
            if s.anchor and s.anchor not in seen:
                seen.add(s.anchor)
                sections.append(f"[{s.title}]({s.site_url})")

        lines.append(f"- **{doc_sec.title}** — [{doc_sec.site_url}]({doc_sec.site_url})")
        if sections:
            lines.append(f"  - Sections: {', '.join(sections)}")
        lines.append(f"  - Pinned at commit [`{commit[:8]}`]({pin})")

    return "\n".join(lines)
