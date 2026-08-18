"""
Staleness detection.

A chapter's output is a pure function of four inputs:

    chapter spec  +  prompt templates  +  source excerpts  +  model identity

Hash all four into a fingerprint and store it in the artifact. On the next
build, recompute: unchanged means skip. That single mechanism covers every
iteration the project needs --

  * upstream docs change      -> excerpt hash moves -> only affected chapters
  * you edit a prompt         -> prompt hash moves  -> every chapter
  * you swap a model          -> model id moves     -> every chapter, diffable
  * you retune one chapter    -> spec hash moves    -> that chapter only
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _h(*parts: str) -> str:
    d = hashlib.sha256()
    for p in parts:
        d.update(p.encode("utf-8"))
        d.update(b"\x00")
    return d.hexdigest()


def fingerprint(
    *,
    spec: dict,
    prompts: dict[str, str],
    excerpts: dict[str, str],
    model_ids: dict[str, str],
) -> str:
    """Order-independent fingerprint of everything that shapes the output."""
    return _h(
        json.dumps(spec, sort_keys=True, ensure_ascii=False),
        json.dumps({k: _h(v) for k, v in sorted(prompts.items())}, sort_keys=True),
        json.dumps({k: _h(v) for k, v in sorted(excerpts.items())}, sort_keys=True),
        json.dumps(model_ids, sort_keys=True),
    )


FM_OPEN = "<!--obook\n"
FM_CLOSE = "\n-->\n"


def read_stamp(path: Path) -> dict | None:
    """Read the build stamp embedded at the top of a generated artifact."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FM_OPEN):
        return None
    end = text.find(FM_CLOSE)
    if end == -1:
        return None
    try:
        return json.loads(text[len(FM_OPEN) : end])
    except json.JSONDecodeError:
        return None


def write_stamped(path: Path, stamp: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = FM_OPEN + json.dumps(stamp, indent=2, sort_keys=True) + FM_CLOSE + body
    path.write_text(blob, encoding="utf-8")


def strip_stamp(text: str) -> str:
    if not text.startswith(FM_OPEN):
        return text
    end = text.find(FM_CLOSE)
    return text[end + len(FM_CLOSE) :] if end != -1 else text
