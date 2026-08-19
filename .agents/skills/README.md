# Skills

Skills live here, one folder per skill, each containing a `SKILL.md`:

```
.agents/skills/<name>/SKILL.md
```

## Why this directory

opencode searches six locations for skills, and `.agents/` is the tool-neutral
one:

```
.opencode/skills/<name>/SKILL.md     opencode-specific
.claude/skills/<name>/SKILL.md       Claude-compatible
.agents/skills/<name>/SKILL.md       agent-compatible   <- this one
```

(plus the `~/.config/opencode/`, `~/.claude/` and `~/.agents/` globals.)

Because opencode reads `.agents/skills/` natively, nothing needs to be
symlinked for it. Claude Code only looks in `.claude/skills/`, so that path is
a symlink back here:

```
.claude/skills -> ../.agents/skills
```

One real directory, both tools satisfied, no copies to drift.

## Not to be confused with

- **`AGENTS.md`** (repo root) — the instruction file. Found by walking up to the
  git worktree; it does not live in a folder. `CLAUDE.md` symlinks to it.
- **Agent definitions** (markdown subagents) — a third location again, and one
  that has no `.agents/` equivalent:
  - Claude Code: `.claude/agents/` (project), `~/.claude/agents/` (user)
  - opencode: `.opencode/agents/` (project), `~/.config/opencode/agents/` (global)

  To single-source those, make one the real directory and symlink the other.
- **`prompts/`** — the obook pipeline's stage templates. Inputs to the build,
  not files any agent tool discovers.

## Nothing here yet

This directory is empty apart from this README. Delete the README once real
skills land.
