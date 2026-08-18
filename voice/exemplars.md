<!--
REPLACE THESE WITH YOUR OWN WRITING. This file does more to control tone than
any instruction in prompts/ does.

Models match demonstrated rhythm far better than they follow described rhythm.
"Be conversational" produces the generic assistant register; three paragraphs
you actually wrote produce your voice. Three to five is plenty.

The samples below are placeholders, written to show the register -- direct,
second person, willing to say when something is annoying, no throat-clearing.
Swap them out before your first real build.
-->

## Sample 1 — explaining a concept

Every coding agent is really two things bolted together: a model, and all the
scaffolding around it. The model is the part everyone argues about online. The
scaffolding is the part that decides whether the thing is actually useful on
your codebase, on a Tuesday, under deadline.

That scaffolding has a name — the harness — and it's most of what you'll spend
your time on. Which files the agent can see. What it's allowed to run without
asking. What it remembers between sessions. Swapping models is a config change;
getting the harness right is the actual work.

## Sample 2 — walking through a task

Start with something small enough that you can check the result by reading it.
Ask a question about code you already understand. You're not testing whether
the agent is smart, you're calibrating how it phrases things and how much it
assumes.

Then let it touch a file. One file, in a repo with a clean git status, so
`git diff` tells you the whole story. This sounds overly cautious for about ten
minutes, right up until the first time an agent confidently refactors something
you didn't ask it to.

## Sample 3 — a warning worth heeding

Permissions are the setting people skip and then regret. The default posture
asks before anything destructive, which feels tedious on day one and looks like
excellent judgment on day forty when a shell command goes sideways in a repo
with uncommitted work.

Turn the guardrails down deliberately, one at a time, once you know what a
given agent actually does. Don't turn them all off because a prompt got
interrupted and you were in a hurry.
