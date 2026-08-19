# manuscript

The generated chapters, committed. This is the **release source**: what a tagged
edition is built from, and what CI turns into an EPUB/PDF once that stage is
proven.

Why committed, when `build/` is gitignored:

- `build/` is scratch — it is overwritten constantly and mixes experiments.
- `manuscript/` is deliberate. Each sync is a decision that this output is worth
  releasing, and because the chapters are text, `git diff` between tags shows
  exactly how the prose changed when upstream docs moved.

Binaries never live here. EPUB and PDF are attached to GitHub Releases so they
stay out of git history.

## Syncing

```bash
opencode-book build          # generate into build/
scripts/sync-manuscript.sh   # copy build/*.md here
```

The build stamp at the top of each file records the corpus commit, fingerprint,
and claim counts. `scripts/changelog.py` diffs those between tags to explain
what changed and why.
