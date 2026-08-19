## Two kinds of agent, and why the split matters

There are two types of agents in opencode: primary agents and subagents. That
distinction sounds like taxonomy, but it's really about who is driving.

Primary agents are the main assistants you interact with directly. You cycle
through them with the **Tab** key, or whatever you've bound `switch_agent` to.
When you type into opencode, you're typing at a primary agent.

Subagents are specialized assistants that primary agents can invoke for specific
tasks. You can also invoke one yourself by **@ mentioning** it. So a subagent
either gets pulled in by the agent you're already talking to, or you summon it
deliberately.

The practical consequence: primary agents are where you set your default working
posture, and subagents are where you put specialized, bounded jobs. A primary
agent that can do everything is convenient and occasionally alarming. A subagent
that can only read files is neither.

## The five you already have

opencode ships with two built-in primary agents, **Build** and **Plan**, and
three built-in subagents, **General**, **Explore**, and **Scout**. You get all
five without configuring anything, and for a while they're enough.

**Build** is the default primary agent, with all tools enabled. It's the
standard agent for development work where you need full access to file
operations and system commands. This is the one you'll spend most of your time
in, and it's the one that will happily edit your working tree.

**Plan** is the restrained sibling: a restricted agent designed for planning and
analysis, using a permission system to give you more control and prevent
unintended changes. By default it sets things to `ask` rather than doing them, so
it can look at everything and change nothing without checking first.

Reach for Plan when you want an opinion rather than a patch. "Why is this test
flaky" is a Plan question. "Fix this flaky test" is a Build question. Getting in
the habit of switching deliberately is worth more than any config you'll write
later.

Of the subagents, **General** is the generalist: a general-purpose agent for
researching complex questions and executing multi-step tasks, with full tool
access except `todo`, so it can make file changes when needed. It's the one to
use when you want several units of work running in parallel.

**Explore** is fast and read-only. It cannot modify files. That constraint is
the feature — you can throw it at an unfamiliar codebase without wondering what
it touched.

**Scout** is also read-only, aimed at external docs and dependency research.
When the question is "what does this library actually do upstream," Scout is the
one that goes and looks.

## Switching without thinking about it

For primary agents, use the **Tab** key to cycle through them during a session.
That's the whole interaction. There's no mode to enter and no command to
remember.

It's worth building the reflex early: Tab to Plan before you ask an open
question, Tab back to Build when you've decided what you want. The cost of
switching is a keystroke, and the cost of *not* switching is occasionally
discovering that your exploratory question turned into eleven modified files.

## Writing your own

You can customize the built-in agents or create your own through configuration,
and there are two ways to do it. Which one you pick is mostly about how much
prose the agent needs.

The first is JSON, in your `opencode.json` config file. Each agent nests under
an `agent` key, with its settings inside:

```json
{
  "agent": {
    "plan": {
      "model": "anthropic/claude-haiku-4-20250514"
    }
  }
}
```

That's the shape for everything that follows — `model`, `prompt`, `permission`,
`steps` all sit inside an agent's block.

The second way is markdown files. You can also define agents using markdown
files, placed in a directory opencode looks in. The markdown file name
becomes the agent name: `review.md` creates a `review` agent. No registration
step, no index to update — drop the file in and it exists.

A markdown agent puts its settings in YAML frontmatter and its system prompt in
the body:

```markdown
---
description: Reviews code for quality and best practices
mode: subagent
model: anthropic/claude-sonnet-4-20250514
temperature: 0.1
permission:
  edit: deny
  bash: deny
---

You are in code review mode. Focus on:

- Code quality and best practices
- Potential bugs and edge cases
- Performance implications
- Security considerations

Provide constructive feedback without making direct changes.
```

This is the format to prefer once an agent has anything to say for itself. A
system prompt is prose, and prose in JSON is a string with escaped newlines in
it — technically fine, miserable to edit. The markdown form lets the prompt be
what it actually is: a document.

Note what that example does with `permission`. It denies edits and bash
outright, which makes the agent structurally incapable of the thing its own
prompt tells it not to do. Instructions are a suggestion; permissions are a
wall. When both are available, use the wall.

## Giving each agent the right model

Use the `model` config to override the model for an agent. This is useful for
running different models optimized for different tasks — a cheaper, faster model
where you want quick turnaround, a more capable one where you want care.

Model IDs use a `provider/model-id` format, so you're always naming both halves
explicitly. That's a small thing that saves confusion later when the same model
name exists on two providers.

The pairing that tends to make sense: a fast model on Plan, where you're going
to iterate on the conversation several times and latency compounds, and your
best model on Build, where a wrong edit costs more than a slow one. Subagents
that do bounded, mechanical work — searching, summarizing — can usually run on
something small.

## Giving each agent its own instructions

Specify a custom system prompt file for an agent with the `prompt` config. The
prompt file should contain instructions specific to that agent's purpose.

The path resolves relative to where the config file lives, which means it works
the same way for both the global config and a project-specific one. A project
can carry its own prompt files in-repo, and they travel with the project rather
than living in someone's home directory.

That's the detail that makes prompts shareable. An agent defined in your global
config is yours alone; an agent defined in the project, pointing at a prompt
file in the project, is something the whole team gets by cloning.

## Permissions: the part worth slowing down for

You can configure permissions to control what an agent is allowed to do. Each
permission key takes one of three values: `ask`, `allow`, or `deny`.

The three-way split is more useful than it first looks. `deny` is a wall.
`allow` is a blank cheque. `ask` is the interesting one — it keeps the agent
moving while putting you in the loop at exactly the moments that matter. Most
well-tuned setups are mostly `ask` with a handful of deliberate `allow`s for
things you've watched enough times to trust.

Permissions set globally can be overridden per agent, which is what makes the
built-in split between Build and Plan work in the first place. You can be
permissive by default and strict for one agent, or the reverse.

Bash permissions can go finer than a single value: instead of one action, you
give a map of pattern to action.

```json
"bash": {
          "*": "ask",
          "git status *": "allow"
        }
```

There's an ordering rule here that will bite you if you skip it. The last
matching rule takes precedence, so put the `*` wildcard first and the specific
rules after. Written the other way around, the wildcard swallows everything
below it and your carefully-scoped exceptions quietly stop applying. Nothing
errors. It just silently behaves like you wrote a much blunter rule.

The pattern that works: start with `"*": "ask"`, then promote individual
commands to `allow` as you get tired of approving them. That way the default is
always the safe one, and every loosening is a decision you made on purpose
rather than a gap you left open.

## Putting a ceiling on iterations

An agent left alone will keep going. The `steps` key controls the maximum number
of agentic iterations an agent can perform before being forced to respond with
text only.

If you don't set it, the agent will continue to iterate until the model chooses
to stop or you interrupt the session. That's usually what you want from Build,
where the task genuinely takes as long as it takes. It's less obviously what you
want from a subagent you invoke fifty times a day.

```json
{
  "agent": {
    "quick-thinker": {
      "description": "Fast reasoning with limited iterations",
      "prompt": "You are a quick thinker. Solve problems with minimal steps.",
      "steps": 5
    }
  }
}
```

A `steps` ceiling is a budget, not a safety mechanism — permissions are the
safety mechanism. What it buys you is predictability on agents whose job should
be small. If a summarizing subagent is on its twentieth tool call, something has
gone sideways, and you'd rather it hand back what it has than keep spending.

One deprecation to know about: the legacy `maxSteps` field is deprecated, and
`steps` is the current spelling. If you're copying config off an older blog
post, that's the line to update.
