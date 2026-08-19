"""Chapter discovery, staleness checks, and the build loop."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .corpus import Corpus
from .fingerprint import fingerprint, read_stamp, write_stamped
from .llm import Models
from .pipeline import Pipeline

PROMPT_FILES = [
    "extract", "extract_user",
    "draft", "draft_user",
    "verify", "verify_user",
    "revise", "revise_user",
    "voice", "voice_user",
]

PIPELINE_ROLES = ["extract", "draft", "verify", "voice"]


class ChapterNotFound(Exception):
    """Raised for an unknown or ambiguous chapter slug.

    Deliberately not KeyError: its __str__ returns repr(arg), which escapes the
    newlines in a multi-line "did you mean" listing.
    """


class Project:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.corpus = Corpus(self.root / "corpus")
        self.models = Models(self.root / "models.yaml")
        self.book = yaml.safe_load((self.root / "book.yaml").read_text()) or {}
        self.out_dir = self.root / "build"

    # ---------------------------------------------------------------- inputs

    def prompts(self) -> dict[str, str]:
        d = {}
        for name in PROMPT_FILES:
            p = self.root / "prompts" / f"{name}.md"
            if not p.exists():
                raise FileNotFoundError(f"Missing prompt template: {p}")
            d[name] = p.read_text(encoding="utf-8")
        return d

    def voice_exemplars(self) -> str:
        p = self.root / "voice" / "exemplars.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def chapters(self) -> list[tuple[str, dict]]:
        """Chapter specs in book order (directory names sort as the reading order)."""
        out = []
        for d in sorted((self.root / "chapters").iterdir()):
            spec_path = d / "chapter.yaml"
            if d.is_dir() and spec_path.exists():
                spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
                out.append((d.name, spec))
        return out

    def chapter(self, slug: str) -> tuple[str, dict]:
        chapters = self.chapters()

        # Exact directory name or declared id wins outright.
        for name, spec in chapters:
            if name == slug or spec.get("id") == slug:
                return name, spec

        # Otherwise accept any unambiguous partial: "05", "agents", "05-agents".
        matches = [
            (name, spec)
            for name, spec in chapters
            if slug in name or slug in str(spec.get("id", ""))
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(n for n, _ in matches)
            raise ChapterNotFound(f"{slug!r} is ambiguous — matches: {names}")

        known = "\n  ".join(n for n, _ in chapters)
        raise ChapterNotFound(f"No chapter matching {slug!r}. Known:\n  {known}")

    # ------------------------------------------------------------ build unit

    def _inputs(self, spec: dict) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        prompts = self.prompts()
        refs = spec.get("sources", []) or []
        excerpts = {}
        for ref in refs:
            # Raises a helpful KeyError listing valid anchors if the ref is bad.
            excerpts[ref] = self.corpus.resolve(ref).full_text
        model_ids = {r: self.models.spec(r).id for r in PIPELINE_ROLES if r in self.models.specs}
        return prompts, excerpts, model_ids

    def status(self) -> list[dict]:
        rows = []
        for name, spec in self.chapters():
            try:
                prompts, excerpts, model_ids = self._inputs(spec)
                fp = fingerprint(
                    spec=spec, prompts=prompts, excerpts=excerpts, model_ids=model_ids
                )
                err = None
            except KeyError as e:
                fp, err = None, str(e).split("\n")[0].strip('"')
            out = self.out_dir / f"{name}.md"
            stamp = read_stamp(out)
            state = (
                "error" if err
                else "missing" if stamp is None
                else "current" if stamp.get("fingerprint") == fp
                else "stale"
            )
            rows.append(
                {
                    "chapter": name,
                    "title": spec.get("title", ""),
                    "sources": len(spec.get("sources", []) or []),
                    "state": state,
                    "error": err,
                }
            )
        return rows

    def _pipeline(self) -> Pipeline:
        return Pipeline(
            corpus=self.corpus,
            models=self.models,
            prompts=self.prompts(),
            book=self.book,
            voice_exemplars=self.voice_exemplars(),
        )

    def _stamp(self, spec: dict, fp: str, res: dict, model_ids: dict) -> dict:
        return {
            "fingerprint": fp,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "corpus_commit": self.corpus.lock["commit"],
            "models": model_ids,
            "claims_used": len(res["claims"]),
            "claims_rejected": len(res["rejected"]),
        }

    def _write(self, name: str, suffix: str, stamp: dict, res: dict) -> Path:
        out_path = self.out_dir / f"{name}{suffix}.md"
        write_stamped(out_path, stamp, res["markdown"])
        side = self.out_dir / f"{name}{suffix}.claims.json"
        side.write_text(
            json.dumps(
                {
                    "claims": res["claims"],
                    "rejected": res["rejected"],
                    "issues": res["issues"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return out_path

    def build_many(
        self,
        targets: list[tuple[str, dict]],
        *,
        force: bool = False,
        skip_voice: bool = False,
        log=print,
    ) -> list[dict]:
        """Build several chapters stage-major: all extracts, then all drafts, ...

        Chapter-major order (whole pipeline per chapter) makes every role change
        a model change, so with distinct models per role a run reloads weights
        once per stage *per chapter*. Since the role models cannot all stay
        resident in 64 GB, that thrash dominates wall-clock time -- often past
        the inference itself.

        Going stage-major collapses that to one load per stage for the whole
        run. With a single shared model it changes nothing; with differentiated
        roles it is the difference between 4 loads and 4x(chapters) loads.
        """
        pipe = self._pipeline()
        max_revisions = int(self.book.get("max_revisions", 1))

        # ---- plan: skip chapters already current
        pending: list[dict] = []
        results: list[dict] = []
        for name, spec in targets:
            try:
                prompts, excerpts, model_ids = self._inputs(spec)
            except KeyError as e:
                log(f"{name}: ERROR - {str(e).splitlines()[0]}")
                results.append({"chapter": name, "state": "error", "error": str(e)})
                continue
            fp = fingerprint(
                spec=spec, prompts=prompts, excerpts=excerpts, model_ids=model_ids
            )
            out_path = self.out_dir / f"{name}.md"
            stamp = read_stamp(out_path)
            if not force and stamp and stamp.get("fingerprint") == fp:
                log(f"{name}: current (skip)")
                results.append({"chapter": name, "state": "current"})
                continue
            pending.append(
                {"name": name, "spec": spec, "fp": fp, "model_ids": model_ids}
            )

        if not pending:
            return results

        def survivors() -> list[dict]:
            return [c for c in pending if not c.get("failed")]

        def guard(chapter: dict, stage: str, fn):
            try:
                return fn()
            except Exception as e:
                log(f"  {chapter['name']}: FAILED in {stage} - {e}")
                chapter["failed"] = str(e)
                return None

        # ---- stage 1: extract (the only stage that reads raw sources)
        log(f"\n== extract == ({len(pending)} chapters)")
        for c in pending:
            def run(c=c):
                return pipe.extract(c["spec"], c["spec"].get("sources", []) or [], log=lambda *_: None)
            got = guard(c, "extract", run)
            if got is None:
                continue
            result, raw = got
            c["result"] = result
            log(f"  {c['name']}: {result.summary()}")
            for cl, why in result.rejected:
                log(f"    rejected [{cl.id}]: {why}")
            if not result.accepted:
                log(f"  {c['name']}: FAILED - no claims survived validation")
                c["failed"] = "no claims survived validation"

        # ---- stage 2: draft
        log(f"\n== draft == ({len(survivors())} chapters)")
        for c in survivors():
            body = guard(c, "draft", lambda c=c: pipe.draft(c["spec"], c["result"].accepted))
            if body is None:
                continue
            c["body"] = body
            log(f"  {c['name']}: {len(body.split())} words")

        # ---- stage 3: verify (+ bounded revision, same model as draft)
        log(f"\n== verify == ({len(survivors())} chapters)")
        for c in survivors():
            for attempt in range(max_revisions + 1):
                issues = guard(
                    c, "verify", lambda c=c: pipe.verify(c["body"], c["result"].accepted)
                )
                if issues is None:
                    break
                c["issues"] = issues
                bad = [i for i in issues if str(i.get("verdict", "")).lower() != "supported"]
                log(f"  {c['name']}: {len(bad)} unsupported")
                if not bad or attempt == max_revisions:
                    break
                fixed = guard(
                    c,
                    "revise",
                    lambda c=c, bad=bad: pipe.revise(c["body"], bad),
                )
                if fixed is None:
                    break
                c["body"] = fixed

        # ---- stage 4: voice
        if not skip_voice:
            log(f"\n== voice == ({len(survivors())} chapters)")
            for c in survivors():
                edited = guard(c, "voice", lambda c=c: pipe.voice(c["spec"], c["body"]))
                if edited is None:
                    continue
                c["body"] = edited
                log(f"  {c['name']}: {len(edited.split())} words")

        # ---- write
        log("")
        for c in pending:
            if c.get("failed"):
                results.append(
                    {"chapter": c["name"], "state": "failed", "error": c["failed"]}
                )
                continue
            res = pipe.finish(c["body"], c["result"], c.get("issues", []))
            stamp = self._stamp(c["spec"], c["fp"], res, c["model_ids"])
            path = self._write(c["name"], "", stamp, res)
            log(f"{c['name']}: wrote {path}")
            results.append({"chapter": c["name"], "state": "built", "path": str(path)})

        return results

    def build_chapter(
        self,
        name: str,
        spec: dict,
        *,
        force: bool = False,
        skip_voice: bool = False,
        suffix: str = "",
        log=print,
    ) -> dict:
        prompts, excerpts, model_ids = self._inputs(spec)
        fp = fingerprint(spec=spec, prompts=prompts, excerpts=excerpts, model_ids=model_ids)

        out_path = self.out_dir / f"{name}{suffix}.md"
        stamp = read_stamp(out_path)
        if not force and stamp and stamp.get("fingerprint") == fp:
            log(f"{name}: current (skip)")
            return {"chapter": name, "state": "current", "path": str(out_path)}

        log(f"{name}: building ({len(spec.get('sources', []))} sources)")
        pipe = Pipeline(
            corpus=self.corpus,
            models=self.models,
            prompts=prompts,
            book=self.book,
            voice_exemplars=self.voice_exemplars(),
        )
        res = pipe.run(
            spec,
            spec.get("sources", []) or [],
            skip_voice=skip_voice,
            max_revisions=int(self.book.get("max_revisions", 1)),
            log=log,
        )

        new_stamp = {
            "fingerprint": fp,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "corpus_commit": self.corpus.lock["commit"],
            "models": model_ids,
            "claims_used": len(res["claims"]),
            "claims_rejected": len(res["rejected"]),
        }
        write_stamped(out_path, new_stamp, res["markdown"])

        side = self.out_dir / f"{name}{suffix}.claims.json"
        side.write_text(
            json.dumps(
                {"claims": res["claims"], "rejected": res["rejected"], "issues": res["issues"]},
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"{name}: wrote {out_path}")
        return {"chapter": name, "state": "built", "path": str(out_path), **new_stamp}
