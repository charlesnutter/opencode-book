"""Replay server: serves hand-authored stage responses over the OpenAI API shape.

Lets the real obook pipeline run end to end -- real corpus load, real prompt
render, real validation, real fingerprint, real output write -- with a human
(or a chat model) standing in for the local model.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent


def read(name: str) -> str:
    p = HERE / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


_verify_calls = 0


def respond(system: str, user: str) -> str:
    global _verify_calls
    s = system.lower()
    if "extract verifiable claims" in s:
        return read("extract.json")
    if "audit a draft chapter" in s:
        # First audit flags the overreaches; second runs against the revision.
        _verify_calls += 1
        return read("verify.json" if _verify_calls == 1 else "verify2.json") or "[]"
    if "repair specific passages" in s:
        return read("revise.md") or user.split("Draft:", 1)[-1].strip()
    if "line editor" in s:
        return read("voice.md") or user.split("Chapter to edit:", 1)[-1].strip()
    return read("draft.md")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = {m["role"]: m["content"] for m in body["messages"]}
        system, user = msgs.get("system", ""), msgs.get("user", "")

        # Log what each stage actually received, so the run is inspectable.
        stage = (
            "extract" if "extract verifiable claims" in system.lower()
            else "verify" if "audit a draft chapter" in system.lower()
            else "revise" if "repair specific passages" in system.lower()
            else "voice" if "line editor" in system.lower()
            else "draft"
        )
        print(f"[{stage}] system={len(system)}c user={len(user)}c", flush=True)
        (HERE / f"seen_{stage}_user.txt").write_text(user, encoding="utf-8")

        content = respond(system, user)
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
    print(f"replay server on :{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
