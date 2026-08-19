#!/usr/bin/env python3
"""
Propose a CHANGELOG entry by diffing chapter build stamps between editions.

Each generated chapter carries a stamp recording the corpus commit it was built
from, a fingerprint over (spec + prompts + sources + model), and claim counts.
Diffing two editions' stamps says *why* a chapter changed -- upstream docs
moved, a prompt was edited, a model was swapped -- which commit messages
cannot.

    scripts/changelog.py                    # vs the latest tag
    scripts/changelog.py --since v0.1.0
    scripts/changelog.py --version v0.2.0   # write a dated header

Chapters below --min-words are flagged as probable placeholder output, so a
release cannot quietly ship mock content.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path

STAMP_OPEN = "<!--opencode-book\n"
STAMP_CLOSE = "\n-->\n"

# Mock runs produce ~70-word chapters; anything this short is not real prose.
DEFAULT_MIN_WORDS = 400


def read_stamp(text: str) -> dict | None:
    if not text.startswith(STAMP_OPEN):
        return None
    end = text.find(STAMP_CLOSE)
    if end == -1:
        return None
    try:
        return json.loads(text[len(STAMP_OPEN):end])
    except json.JSONDecodeError:
        return None


def body_words(text: str) -> int:
    if text.startswith(STAMP_OPEN):
        end = text.find(STAMP_CLOSE)
        if end != -1:
            text = text[end + len(STAMP_CLOSE):]
    # Drop the generated Sources block so it doesn't inflate the count.
    text = re.split(r"\n---\n\n## Sources\n", text)[0]
    return len(text.split())


def git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return None


def latest_tag() -> str | None:
    out = git("describe", "--tags", "--abbrev=0")
    return out.strip() if out else None


def load_current(manuscript: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(manuscript.glob("*.md")):
        if p.name in ("manuscript.md", "README.md"):
            continue
        text = p.read_text(encoding="utf-8")
        out[p.stem] = {"stamp": read_stamp(text) or {}, "words": body_words(text)}
    return out


def load_tagged(manuscript: Path, tag: str) -> dict[str, dict]:
    listing = git("ls-tree", "--name-only", f"{tag}:{manuscript.name}")
    if listing is None:
        return {}
    out = {}
    for name in listing.split():
        if not name.endswith(".md") or name in ("manuscript.md", "README.md"):
            continue
        text = git("show", f"{tag}:{manuscript.name}/{name}")
        if text is None:
            continue
        out[Path(name).stem] = {
            "stamp": read_stamp(text) or {},
            "words": body_words(text),
        }
    return out


def why_changed(old: dict, new: dict) -> str:
    """Attribute a fingerprint change to its most likely cause."""
    o, n = old.get("stamp", {}), new.get("stamp", {})
    reasons = []
    if o.get("corpus_commit") != n.get("corpus_commit"):
        reasons.append(
            f"upstream docs {str(o.get('corpus_commit'))[:8]} → "
            f"{str(n.get('corpus_commit'))[:8]}"
        )
    if o.get("models") != n.get("models"):
        reasons.append("model changed")
    if not reasons:
        # Same sources and models, different fingerprint: prompts or the
        # chapter spec moved. The stamp cannot tell which.
        reasons.append("prompt or chapter spec changed")

    oc, nc = o.get("claims_used"), n.get("claims_used")
    if oc is not None and nc is not None and oc != nc:
        reasons.append(f"{oc} → {nc} claims")

    dw = new["words"] - old["words"]
    if abs(dw) >= 50:
        reasons.append(f"{dw:+d} words")

    return "; ".join(reasons)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manuscript", default="manuscript", type=Path)
    ap.add_argument("--since", help="tag to compare against (default: latest)")
    ap.add_argument("--version", help="version header to emit, e.g. v0.2.0")
    ap.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS)
    args = ap.parse_args()

    if not args.manuscript.exists():
        print(f"No {args.manuscript}/ -- run the release sync first.")
        return 1

    current = load_current(args.manuscript)
    if not current:
        print(f"No chapters in {args.manuscript}/.")
        return 1

    since = args.since or latest_tag()
    previous = load_tagged(args.manuscript, since) if since else {}

    added, changed, unchanged = [], [], []
    for name, new in current.items():
        old = previous.get(name)
        if old is None:
            added.append(name)
        elif old.get("stamp", {}).get("fingerprint") != new.get("stamp", {}).get("fingerprint"):
            changed.append((name, why_changed(old, new)))
        else:
            unchanged.append(name)
    removed = [n for n in previous if n not in current]

    commit = next(
        (c["stamp"].get("corpus_commit") for c in current.values()
         if c["stamp"].get("corpus_commit")),
        None,
    )

    lines = []
    header = args.version or "Unreleased"
    lines.append(f"## {header} — {date.today().isoformat()}")
    lines.append("")
    if commit:
        prev_commit = next(
            (c["stamp"].get("corpus_commit") for c in previous.values()
             if c["stamp"].get("corpus_commit")),
            None,
        )
        note = f"Built from opencode docs @ `{commit[:8]}`"
        if prev_commit and prev_commit != commit:
            note += f" (was `{prev_commit[:8]}`)"
        lines.append(note)
        lines.append("")
    if since:
        lines.append(f"Compared against `{since}`.")
        lines.append("")

    if added:
        lines.append("### Added")
        for n in added:
            lines.append(f"- {n} ({current[n]['words']:,} words)")
        lines.append("")
    if changed:
        lines.append("### Changed")
        for n, why in changed:
            lines.append(f"- {n} — {why}")
        lines.append("")
    if removed:
        lines.append("### Removed")
        for n in removed:
            lines.append(f"- {n}")
        lines.append("")
    if unchanged:
        lines.append(f"### Unchanged\n\n- {len(unchanged)} chapters "
                     f"(identical fingerprints): {', '.join(sorted(unchanged))}")
        lines.append("")

    total = sum(c["words"] for c in current.values())
    lines.append(f"**Total:** {len(current)} chapters, {total:,} words.")
    lines.append("")

    print("\n".join(lines))

    short = [(n, c["words"]) for n, c in sorted(current.items())
             if c["words"] < args.min_words]
    if short:
        print("---")
        print(f"WARNING: {len(short)} chapter(s) below {args.min_words} words — "
              "probable placeholder output, not real prose:")
        for n, w in short:
            print(f"  {n}: {w} words")
        print("Do not publish these as a finished edition without saying so.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
