"""
Corpus: fetch, pin, and slice the opencode documentation.

The whole canonical English doc set is ~50k words (~70k tokens), so there is
no retrieval layer here on purpose -- chapters name their sources explicitly
and we read those files directly. That keeps provenance exact: every excerpt
handed to a model is traceable to a file, a heading anchor, and an upstream
commit.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO = "anomalyco/opencode"
DOCS_PATH = "packages/web/src/content/docs"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}/{name}"
API_COMMIT = "https://api.github.com/repos/{repo}/commits/{ref}"
API_TREE = "https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"

# Public docs site, used to build reader-facing footnote links.
SITE = "https://opencode.ai/docs"

HEADING_RE = re.compile(r"^(?P<hashes>#{1,4})\s+(?P<text>.+?)\s*$", re.M)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def slugify(text: str) -> str:
    """Mirror the anchor slugs Astro/Starlight generates for headings."""
    text = text.strip().lower()
    text = re.sub(r"[`*_~]", "", text)          # strip inline md formatting
    text = re.sub(r"[^\w\s-]", "", text)        # drop punctuation
    text = re.sub(r"[\s_]+", "-", text)         # spaces -> dashes
    return text.strip("-")


@dataclass
class Section:
    """One heading-delimited slice of a doc -- the unit chapters cite."""
    doc: str          # "agents.mdx"
    anchor: str       # "primary-agents"
    title: str        # "Primary agents"
    level: int        # 2 for ##, 3 for ###
    text: str         # body text under this heading (excludes subsections)
    full_text: str    # body text including nested subsections

    @property
    def ref(self) -> str:
        return f"{self.doc}#{self.anchor}" if self.anchor else self.doc

    @property
    def site_url(self) -> str:
        page = self.doc.removesuffix(".mdx")
        base = SITE if page == "index" else f"{SITE}/{page}"
        return f"{base}#{self.anchor}" if self.anchor else base


class Corpus:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.docs_dir = self.root / "docs"
        self.lock_path = self.root / "lock.json"
        self._sections: dict[str, Section] | None = None

    # ---------------------------------------------------------------- sync

    def sync(self, ref: str = "dev") -> dict:
        """Download canonical English docs at `ref` and write lock.json.

        Only top-level .mdx files are canonical English; everything one level
        deeper is a locale translation (ar/, ja/, zh-cn/, ...) and is skipped.
        """
        self.docs_dir.mkdir(parents=True, exist_ok=True)

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            commit = client.get(API_COMMIT.format(repo=REPO, ref=ref))
            commit.raise_for_status()
            sha = commit.json()["sha"]

            tree = client.get(API_TREE.format(repo=REPO, ref=sha))
            tree.raise_for_status()
            names = sorted(
                p[len(DOCS_PATH) + 1:]
                for p in (t["path"] for t in tree.json()["tree"] if t["type"] == "blob")
                if p.startswith(DOCS_PATH + "/")
                and p.endswith(".mdx")
                and "/" not in p[len(DOCS_PATH) + 1:]
            )

            files = {}
            for name in names:
                url = RAW.format(repo=REPO, ref=sha, path=DOCS_PATH, name=name)
                resp = client.get(url)
                resp.raise_for_status()
                body = resp.text
                (self.docs_dir / name).write_text(body, encoding="utf-8")
                files[name] = {
                    "sha256": hashlib.sha256(body.encode()).hexdigest(),
                    "bytes": len(body.encode()),
                    "words": len(body.split()),
                    "url": url,
                }

        lock = {
            "repo": REPO,
            "ref": ref,
            "commit": sha,
            "docs_path": DOCS_PATH,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file_count": len(files),
            "total_words": sum(f["words"] for f in files.values()),
            "files": files,
        }
        self.lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        self._sections = None
        return lock

    # ---------------------------------------------------------------- read

    @property
    def lock(self) -> dict:
        if not self.lock_path.exists():
            raise FileNotFoundError(
                f"No corpus lock at {self.lock_path}. Run: obook sync"
            )
        return json.loads(self.lock_path.read_text(encoding="utf-8"))

    def doc_text(self, doc: str) -> str:
        path = self.docs_dir / doc
        if not path.exists():
            raise FileNotFoundError(f"Doc not in corpus: {doc}. Run: obook sync")
        return path.read_text(encoding="utf-8")

    def sections(self) -> dict[str, Section]:
        """Parse every doc into heading-delimited sections keyed by 'doc#anchor'."""
        if self._sections is not None:
            return self._sections

        out: dict[str, Section] = {}
        for path in sorted(self.docs_dir.glob("*.mdx")):
            doc = path.name
            raw = path.read_text(encoding="utf-8")

            # Strip frontmatter but remember the title for the doc-level anchor.
            fm = FRONTMATTER_RE.match(raw)
            body = raw[fm.end():] if fm else raw
            doc_title = doc.removesuffix(".mdx")
            if fm:
                m = re.search(r"^title:\s*(.+)$", fm.group(1), re.M)
                if m:
                    doc_title = m.group(1).strip().strip("\"'")

            matches = list(HEADING_RE.finditer(body))

            # Whole-document pseudo-section, cited as "agents.mdx" with no anchor.
            out[doc] = Section(
                doc=doc,
                anchor="",
                title=doc_title,
                level=1,
                text=body[: matches[0].start()].strip() if matches else body.strip(),
                full_text=body.strip(),
            )

            for i, m in enumerate(matches):
                level = len(m.group("hashes"))
                title = m.group("text").strip()
                anchor = slugify(title)
                start = m.end()

                # `text` stops at the next heading of any level.
                nxt = matches[i + 1].start() if i + 1 < len(matches) else len(body)
                text = body[start:nxt].strip()

                # `full_text` runs until the next heading of the same or higher
                # rank, so citing "## Configure" includes its ### subsections.
                end = len(body)
                for j in range(i + 1, len(matches)):
                    if len(matches[j].group("hashes")) <= level:
                        end = matches[j].start()
                        break
                full_text = body[start:end].strip()

                key = f"{doc}#{anchor}"
                if key not in out:  # first heading wins on duplicate slugs
                    out[key] = Section(
                        doc=doc,
                        anchor=anchor,
                        title=title,
                        level=level,
                        text=text,
                        full_text=full_text,
                    )

        self._sections = out
        return out

    def resolve(self, ref: str) -> Section:
        """Resolve a chapter source ref like 'agents.mdx#configure'."""
        secs = self.sections()
        if ref in secs:
            return secs[ref]
        doc, _, anchor = ref.partition("#")
        available = sorted(
            s.anchor for s in secs.values() if s.doc == doc and s.anchor
        )
        if not available:
            raise KeyError(f"Unknown doc in source ref: {ref!r}")
        raise KeyError(
            f"Unknown anchor {anchor!r} in {doc}. Available anchors:\n  "
            + "\n  ".join(available)
        )

    def excerpt(self, ref: str) -> str:
        """Source text for a ref, formatted for a prompt with its citation key."""
        s = self.resolve(ref)
        return f"<source ref=\"{s.ref}\" title=\"{s.title}\">\n{s.full_text}\n</source>"
