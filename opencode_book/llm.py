"""
Model access, by role.

Every stage asks for a *role* ("extract", "draft", "verify", "voice"), never a
model name. models.yaml maps roles to endpoints, so swapping a model -- or
pointing a role at a hosted API instead of local MLX -- is a config edit.

Everything speaks the OpenAI chat-completions shape, which MLX server,
LM Studio, Ollama, llama.cpp and the hosted APIs all provide.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml


@dataclass
class ModelSpec:
    role: str
    base_url: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 4096
    api_key_env: str | None = None
    timeout: float = 600.0

    @property
    def id(self) -> str:
        """Stable identity for fingerprinting -- changes force a rebuild."""
        return f"{self.model}@{self.base_url}?t={self.temperature}"


class Models:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        defaults = raw.get("defaults", {}) or {}
        self.specs: dict[str, ModelSpec] = {}
        for role, cfg in (raw.get("roles") or {}).items():
            merged = {**defaults, **(cfg or {})}
            self.specs[role] = ModelSpec(role=role, **merged)

    def spec(self, role: str) -> ModelSpec:
        if role not in self.specs:
            raise KeyError(
                f"No model configured for role {role!r}. "
                f"Known roles: {sorted(self.specs)}"
            )
        return self.specs[role]

    def override(self, role: str, model: str) -> None:
        """Point one role at a different model (used by `opencode-book bakeoff`)."""
        base = self.spec(role)
        self.specs[role] = ModelSpec(
            role=role,
            base_url=base.base_url,
            model=model,
            temperature=base.temperature,
            max_tokens=base.max_tokens,
            api_key_env=base.api_key_env,
            timeout=base.timeout,
        )

    def complete(self, role: str, system: str, user: str) -> str:
        spec = self.spec(role)
        headers = {"Content-Type": "application/json"}
        if spec.api_key_env:
            key = os.environ.get(spec.api_key_env)
            if not key:
                raise RuntimeError(
                    f"Role {role!r} needs env var {spec.api_key_env}, which is unset."
                )
            headers["Authorization"] = f"Bearer {key}"

        payload = {
            "model": spec.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
        }

        url = spec.base_url.rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=spec.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"{role} ({spec.model}) returned {resp.status_code}: {resp.text[:400]}"
                )
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    def complete_json(self, role: str, system: str, user: str) -> object:
        """Complete and parse JSON, tolerating code fences and prose padding.

        Local models routinely wrap JSON in ```json fences or add a sentence
        before it, so we salvage rather than fail on the first stray token.
        """
        raw = self.complete(role, system, user)
        return parse_json_loose(raw)


FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_loose(raw: str) -> object:
    candidates: list[str] = []
    stripped = raw.strip()
    candidates.append(stripped)

    for m in FENCE_RE.finditer(raw):
        candidates.append(m.group(1).strip())

    # Fall back to the outermost bracketed span.
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = stripped.find(opener), stripped.rfind(closer)
        if start != -1 and end > start:
            candidates.append(stripped[start : end + 1])

    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not parse JSON from model output:\n{raw[:800]}")
