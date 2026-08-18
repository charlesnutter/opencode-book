#!/usr/bin/env python3
"""
Export a Claude Code session transcript to readable markdown.

Claude Code stores each session as JSONL under
~/.claude/projects/<slugified-cwd>/<session-id>.jsonl. That file is the real
record -- this converts it to something a human can read, rather than
reconstructing the conversation from memory.

Usage:
    export_session.py                      # newest session for this project
    export_session.py --session <uuid>
    export_session.py --project -Users-me-dev-foo
    export_session.py --thinking           # include reasoning blocks

Tool results are truncated (they include multi-megabyte directory listings and
base64 images); the conversation text is kept in full.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"

TOOL_RESULT_LIMIT = 1500
TOOL_INPUT_LIMIT = 800

# Harness-injected noise that isn't part of the conversation.
NOISE_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>"
    r"|<local-command-caveat>.*?</local-command-caveat>"
    r"|<command-message>.*?</command-message>"
    r"|<command-args>.*?</command-args>",
    re.S,
)

# Slash-command invocations and their local output -- UI chatter, not dialogue.
SLASH_RE = re.compile(
    r"\A\s*(<command-name>.*?</command-name>|<local-command-stdout>.*?</local-command-stdout>)\s*\Z",
    re.S,
)


def clean(text: str) -> str:
    return NOISE_RE.sub("", text).strip()


def truncate(text: str, limit: int) -> str:
    text = text.rstrip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit:,} more chars]"


def find_transcript(project: str | None, session: str | None) -> Path:
    if project:
        d = PROJECTS / project
    else:
        # Newest project dir that has any transcript in it.
        candidates = [p for p in PROJECTS.iterdir() if p.is_dir()]
        d = max(candidates, key=lambda p: p.stat().st_mtime)
    if session:
        p = d / f"{session}.jsonl"
        if not p.exists():
            raise SystemExit(f"No transcript at {p}")
        return p
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No .jsonl transcripts in {d}")
    return files[-1]


def blocks(msg) -> list:
    c = msg.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return c if isinstance(c, list) else []


def render(path: Path, include_thinking: bool) -> str:
    out: list[str] = []
    first_ts = last_ts = None
    models: set[str] = set()
    counts = {"user": 0, "assistant": 0, "tools": 0}

    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = d.get("type")
            if kind not in ("user", "assistant"):
                continue
            if d.get("isMeta"):
                continue

            ts = d.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts

            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue
            if kind == "assistant" and msg.get("model"):
                models.add(msg["model"])

            parts: list[str] = []
            only_tool_result = True  # user-role messages carrying tool output
            for b in blocks(msg):
                btype = b.get("type")
                if btype != "tool_result":
                    only_tool_result = False

                if btype == "text":
                    t = clean(b.get("text", ""))
                    if SLASH_RE.match(t):
                        continue
                    if t:
                        parts.append(t)

                elif btype == "thinking" and include_thinking:
                    t = b.get("thinking", "").strip()
                    if t:
                        parts.append(
                            "<details><summary>reasoning</summary>\n\n"
                            f"{t}\n\n</details>"
                        )

                elif btype == "tool_use":
                    counts["tools"] += 1
                    name = b.get("name", "?")
                    raw = json.dumps(b.get("input", {}), indent=2, ensure_ascii=False)
                    parts.append(
                        f"**→ {name}**\n\n```json\n{truncate(raw, TOOL_INPUT_LIMIT)}\n```"
                    )

                elif btype == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        text = "\n".join(
                            x.get("text", "[image]")
                            for x in c
                            if isinstance(x, dict)
                        )
                    else:
                        text = str(c)
                    text = clean(text)
                    if text:
                        parts.append(
                            f"```\n{truncate(text, TOOL_RESULT_LIMIT)}\n```"
                        )

            body = "\n\n".join(p for p in parts if p).strip()
            if not body:
                continue

            # Tool output comes back on user-role messages; labelling those
            # "User" makes the transcript read as if the human pasted it.
            if kind == "user" and only_tool_result:
                out.append(f"\n<sub>tool result</sub>\n\n{body}\n")
                continue

            counts[kind] += 1
            speaker = "User" if kind == "user" else "Claude"
            stamp = f" · {ts[:19].replace('T', ' ')}" if ts else ""
            out.append(f"\n## {speaker}{stamp}\n\n{body}\n")

    header = [
        "# Session transcript",
        "",
        f"- **Source**: `{path}`",
        f"- **Exported**: {datetime.now().isoformat(timespec='seconds')}",
    ]
    if first_ts:
        header.append(f"- **Span**: {first_ts[:19]} → {last_ts[:19]} UTC")
    if models:
        header.append(f"- **Models**: {', '.join(sorted(models))}")
    header.append(
        f"- **Turns**: {counts['user']} user, {counts['assistant']} assistant, "
        f"{counts['tools']} tool calls"
    )
    if not include_thinking:
        header.append("- **Note**: reasoning blocks omitted (`--thinking` to include)")
    header += ["- **Note**: tool output truncated for readability", "", "---"]

    return "\n".join(header) + "\n" + "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session", help="session uuid")
    ap.add_argument("--project", help="project dir name under ~/.claude/projects")
    ap.add_argument("--thinking", action="store_true", help="include reasoning blocks")
    ap.add_argument("-o", "--out", help="output path")
    args = ap.parse_args()

    src = find_transcript(args.project, args.session)
    md = render(src, args.thinking)

    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[1] / "sessions" / f"{src.stem}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out} ({len(md):,} chars from {src.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
