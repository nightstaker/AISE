---
name: git
description: Local version control conventions — each project is its own git repo, commits happen automatically per dispatch, agents read history but do not commit directly
---

# Git Skill

## Runtime model

Every project created by AISE is initialized as its **own local git
repo** at the project root. This happens during project scaffolding,
before any agent runs. As a result:

- `execute_shell('git status')` runs against the PROJECT's repo, not
  the host machine's repo. Delta queries (`git diff`, `git log`) are
  meaningful.
- `HEAD` after scaffolding points to a single "project scaffold"
  commit whose tree is the empty baseline. Every subsequent commit is
  produced by the runtime per successful dispatch.
- `.gitignore` is seeded with the sensible defaults (trace JSONs,
  `__pycache__/`, `.pytest_cache/`, `.coverage`, `node_modules/`, ...)
  so commits capture the real deliverables — source, tests, docs,
  delivery report — and nothing else.

## Commits: handled by the runtime, NOT by the agent

After every successful dispatch, the runtime automatically runs:

```
git add -A
git commit -m "<agent>(<step_id or phase>): <first line of your response>"
```

This means agents **must not** run `git commit` themselves. Doing so
duplicates the runtime's commit and pollutes the log with two
entries per task. Specifically:

- Do NOT call `execute_shell('git commit ...')`.
- Do NOT call `execute_shell('git add ...')` with the intention of
  staging for a later commit — the runtime adds everything anyway.
- Do NOT edit `.gitignore` unless the task explicitly asks for it.
- Do NOT create or rewrite `.git/` directly.

If your dispatch wrote nothing (read-only task — e.g. reviewer,
report compiler), the runtime detects a clean working tree and
skips the commit silently. No action needed.

## Reads are fine

Agents are encouraged to use git as a **read-only** tool whenever it
answers a question cheaper than re-reading files:

- `execute_shell('git log --oneline -10')` — recent history.
- `execute_shell('git diff HEAD~1')` — what changed in the previous
  dispatch.
- `execute_shell('git diff --name-only HEAD~1')` — names of files
  touched last dispatch (useful for incremental architects / QA to
  scope their work).
- `execute_shell('git show HEAD:src/foo.py')` — view a file at HEAD
  without editing the working tree.
- `execute_shell('git status --porcelain')` — whether the current
  tree is clean.

All of these run against the project repo from the project root —
no need to `cd` anywhere.

## Commit messages

Runtime commit messages follow a fixed shape:

```
<agent>(<step_id or phase>): <truncated first line of response>
```

Examples produced by the runtime:

```
developer(impl_game_engine): Wrote tests/test_game_engine.py + src/game_engine.py
architect(phase2_architecture): docs/architecture.md with 3 C4 diagrams
qa_engineer(phase5_integration_testing): All 124 tests pass, coverage 82%
```

The first line of your response IS the commit subject. Keep it
informative — it will show up in `git log` forever.

## When incremental mode runs

In incremental mode (a new requirement against a project with a
baseline run), the architect, developer, and QA agents can rely on
git to see exactly what each prior phase produced:

```
git log --oneline                 # full history
git diff <prior-run-tag> HEAD     # all changes since last run
git diff --name-only HEAD~1       # files changed in the last dispatch
```

Use these to scope incremental work precisely — don't re-read every
file when `git diff --name-only` tells you which three changed.

## Anti-patterns to avoid

- **Manual commits**: `execute_shell('git commit -am ...')` — redundant
  with the runtime commit and produces double entries.
- **Force operations**: `git reset --hard`, `git clean -fd`,
  `git checkout --` — these destroy uncommitted work from the current
  dispatch (which hasn't been committed yet) and other dispatches.
  Never run them.
- **Branching**: the local repo stays on one branch (usually
  `master`). Don't create branches — there's no reviewer to merge
  them.
- **Pushing to a remote**: the project repo has no remote. Don't try
  `git push` / `git remote add` — they either fail or reach out to
  the wrong place.
- **Editing `.git/`** directly: never.
