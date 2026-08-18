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
        for name, spec in self.chapters():
            if name == slug or name.endswith(slug) or spec.get("id") == slug:
                return name, spec
        known = ", ".join(n for n, _ in self.chapters())
        raise KeyError(f"No chapter matching {slug!r}. Known: {known}")

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
