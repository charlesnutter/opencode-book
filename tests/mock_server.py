"""
A fake OpenAI-compatible server for exercising the pipeline without a model.

It returns real verbatim quotes pulled from the corpus, so the validator has
something genuine to accept -- plus one deliberately fabricated claim, so the
rejection path is exercised on every test run.

    python tests/mock_server.py &
    obook build 07-skills-and-commands --force
"""
from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from obook.corpus import Corpus  # noqa: E402

CORPUS = Corpus(Path(__file__).resolve().parents[1] / "corpus")
SOURCE_RE = re.compile(r'<source ref="([^"]+)"', re.M)


def make_claims(user: str) -> str:
    """Build claims whose quotes really do appear in the cited sources."""
    refs = SOURCE_RE.findall(user)
    claims = []
    for i, ref in enumerate(refs[:6]):
        try:
            text = CORPUS.resolve(ref).full_text
        except KeyError:
            continue
        words = text.split()
        if len(words) < 10:
            continue
        quote = " ".join(words[:16])
        claims.append(
            {
                "id": f"c{i + 1}",
                "claim": f"Documented behaviour drawn from {ref}.",
                "quote": quote,
                "ref": ref,
            }
        )
    # One fabrication, so the validator's reject path runs every time.
    if refs:
        claims.append(
            {
                "id": "bogus",
                "claim": "Fabricated claim that should never survive validation.",
                "quote": "opencode requires an annual license key issued by the foundation.",
                "ref": refs[0],
            }
        )
    return json.dumps(claims)


def respond(system: str, user: str) -> str:
    s = system.lower()
    if "extract verifiable claims" in s:
        return make_claims(user)
    if "audit a draft chapter" in s:
        return json.dumps(
            [{"passage": "sample", "cited": "c1", "verdict": "supported", "note": ""}]
        )
    if "line editor" in s:
        return user.split("Chapter to edit:", 1)[-1].strip() or "edited"
    if "repair specific passages" in s:
        return user.split("Draft:", 1)[-1].strip() or "repaired"
    # draft stage
    return (
        "## A Worked Example\n\n"
        "This paragraph stands in for generated prose so the pipeline can be "
        "exercised without a live model.\n\n"
        "```bash\nopencode --help\n```\n"
    )


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = {m["role"]: m["content"] for m in body["messages"]}
        content = respond(msgs.get("system", ""), msgs.get("user", ""))
        payload = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": content}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
    print(f"mock model server on :{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
