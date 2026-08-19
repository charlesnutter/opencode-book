"""opencode-book -- build a book from opencode's documentation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import ChapterNotFound, Project
from .corpus import Corpus


def cmd_sync(args) -> int:
    corpus = Corpus(Path(args.root) / "corpus")
    lock = corpus.sync(ref=args.ref)
    print(f"synced {lock['file_count']} docs ({lock['total_words']:,} words)")
    print(f"  repo:   {lock['repo']}@{lock['ref']}")
    print(f"  commit: {lock['commit']}")
    print(f"  lock:   {corpus.lock_path}")
    return 0


def cmd_anchors(args) -> int:
    corpus = Corpus(Path(args.root) / "corpus")
    secs = corpus.sections()
    if args.doc:
        secs = {k: v for k, v in secs.items() if v.doc == args.doc}
        if not secs:
            print(f"No such doc: {args.doc}", file=sys.stderr)
            return 1
    by_doc: dict[str, list] = {}
    for s in secs.values():
        by_doc.setdefault(s.doc, []).append(s)
    for doc in sorted(by_doc):
        print(f"\n{doc}")
        for s in sorted(by_doc[doc], key=lambda x: (x.level, x.anchor)):
            if not s.anchor:
                continue
            words = len(s.full_text.split())
            print(f"  {'  ' * (s.level - 2)}{s.ref:<52} {words:>5}w  {s.title}")
    return 0


def cmd_status(args) -> int:
    proj = Project(Path(args.root))
    rows = proj.status()
    if not rows:
        print("No chapters found in chapters/")
        return 0
    width = max(len(r["chapter"]) for r in rows)
    marks = {"current": "ok", "stale": "STALE", "missing": "MISSING", "error": "ERROR"}
    for r in rows:
        line = f"{r['chapter']:<{width}}  {marks[r['state']]:<8} {r['sources']:>2} src  {r['title']}"
        print(line)
        if r["error"]:
            print(f"{'':<{width}}  -> {r['error']}")
    stale = sum(1 for r in rows if r["state"] in ("stale", "missing"))
    print(f"\n{len(rows)} chapters, {stale} need building")
    return 0


def cmd_build(args) -> int:
    proj = Project(Path(args.root))
    try:
        targets = [proj.chapter(args.chapter)] if args.chapter else proj.chapters()
    except ChapterNotFound as e:
        print(e, file=sys.stderr)
        return 1
    if not targets:
        print("No chapters to build.", file=sys.stderr)
        return 1

    # Stage-major: every chapter through extract, then every chapter through
    # draft, and so on. With differentiated role models this loads each model
    # once per run instead of once per chapter. A single chapter has nothing to
    # reorder, so it takes the simpler per-chapter path.
    if len(targets) == 1 and not args.chapter_major:
        name, spec = targets[0]
        try:
            proj.build_chapter(name, spec, force=args.force, skip_voice=args.skip_voice)
        except Exception as e:
            print(f"{name}: FAILED - {e}", file=sys.stderr)
            return 1
        return 0

    if args.chapter_major:
        failures = []
        for name, spec in targets:
            try:
                proj.build_chapter(
                    name, spec, force=args.force, skip_voice=args.skip_voice
                )
            except Exception as e:
                print(f"{name}: FAILED - {e}", file=sys.stderr)
                failures.append(name)
        results = [{"chapter": n, "state": "failed"} for n in failures]
    else:
        results = proj.build_many(
            targets, force=args.force, skip_voice=args.skip_voice
        )

    failed = [r for r in results if r.get("state") in ("failed", "error")]
    built = [r for r in results if r.get("state") == "built"]
    print(f"\n{len(built)} built, {len(failed)} failed")
    if failed:
        for r in failed:
            print(f"  {r['chapter']}: {r.get('error', 'failed')}", file=sys.stderr)
        return 1
    return 0


def cmd_bakeoff(args) -> int:
    """Generate one chapter with several draft models for side-by-side reading."""
    proj = Project(Path(args.root))
    name, spec = proj.chapter(args.chapter)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    print(f"bakeoff: {name} across {len(models)} model(s)\n")
    for m in models:
        proj.models.override("draft", m)
        safe = m.replace("/", "_").replace(":", "_")
        print(f"--- {m} ---")
        try:
            proj.build_chapter(
                name, spec, force=True, skip_voice=args.skip_voice,
                suffix=f".{safe}",
            )
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
        print()
    print("Compare outputs in build/ and pick the voice you'd actually publish.")
    return 0


def cmd_assemble(args) -> int:
    """Concatenate built chapters into a single manuscript."""
    from .fingerprint import strip_stamp

    proj = Project(Path(args.root))
    parts, missing = [], []
    for name, spec in proj.chapters():
        p = proj.out_dir / f"{name}.md"
        if not p.exists():
            missing.append(name)
            continue
        body = strip_stamp(p.read_text(encoding="utf-8"))
        parts.append(f"# {spec.get('title', name)}\n\n{body.strip()}")
    if missing:
        print(f"warning: {len(missing)} chapter(s) not built: {', '.join(missing)}",
              file=sys.stderr)
    if not parts:
        print("Nothing to assemble.", file=sys.stderr)
        return 1
    out = proj.out_dir / "manuscript.md"
    title = proj.book.get("title", "The opencode Book")
    out.write_text(f"# {title}\n\n" + "\n\n---\n\n".join(parts) + "\n", encoding="utf-8")
    words = len(out.read_text().split())
    print(f"assembled {len(parts)} chapters -> {out} ({words:,} words)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="opencode-book", description=__doc__)
    p.add_argument("--root", default=".", help="project root (default: cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="fetch and pin the opencode docs corpus")
    s.add_argument("--ref", default="dev", help="git ref to pin (default: dev)")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("anchors", help="list citable source anchors")
    s.add_argument("--doc", help="limit to one doc, e.g. agents.mdx")
    s.set_defaults(func=cmd_anchors)

    s = sub.add_parser("status", help="show which chapters are stale")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("build", help="build chapters (incremental by default)")
    s.add_argument("chapter", nargs="?", help="chapter slug; omit to build all")
    s.add_argument("--force", action="store_true", help="rebuild even if current")
    s.add_argument("--skip-voice", action="store_true", help="stop after verify")
    s.add_argument(
        "--chapter-major",
        action="store_true",
        help="run each chapter through all stages before the next "
        "(slower with per-role models; useful for debugging one chapter at a time)",
    )
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("bakeoff", help="draft one chapter with several models")
    s.add_argument("chapter")
    s.add_argument("--models", required=True, help="comma-separated model ids")
    s.add_argument("--skip-voice", action="store_true", default=True)
    s.set_defaults(func=cmd_bakeoff)

    s = sub.add_parser("assemble", help="concatenate built chapters")
    s.set_defaults(func=cmd_assemble)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
