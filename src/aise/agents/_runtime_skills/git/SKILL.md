---
name: git
description: Project version control — you are responsible for ``git init``, per-phase commits, phase tags, and ``git log`` summaries. Runtime does NOT commit for you.
---

# Git Skill

## Runtime model (AI-First)

Every AISE project is its own local git repo. **You** (the
product-manager agent) own every git operation — the runtime does
not auto-commit. You do:

- ``git init`` during SCAFFOLDING, on a fresh project root
- stage + commit the scaffold with a clear subject
- ``git add -A && git commit`` once per successful phase
- ``git tag phase_<N>_<name>`` once a phase is cleanly done
- ``git log --oneline <prev_tag>..HEAD`` when you need a phase summary

Other agents (architect, developer, qa_engineer) **write files only**;
you drive the history. That keeps the commit log clean (one entry per
phase) and makes ``git diff`` between tags the authoritative answer
to "what changed in phase N?".

## When this runs

### 1. SCAFFOLDING phase (one-shot)

You receive a ``SCAFFOLDING TASK`` prompt at project creation. Do in
order:

```bash
# Create the standard subdirs
mkdir -p docs src tests scripts config artifacts trace

# Initialize the repo
git init --quiet
git config user.name  "AISE Orchestrator"
git config user.email "orchestrator@aise.local"
```

Write ``.gitignore`` with this baseline (secret patterns included to
stop keys / credentials from leaking into history):

```
# AISE runtime artefacts
runs/trace/
runs/plans/
analytics_events.jsonl

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.coverage
coverage.xml
htmlcov/
.mypy_cache/
.ruff_cache/

# Node / JS
node_modules/
dist/
build/

# OS / IDE
.DS_Store
.vscode/
.idea/

# Secrets / credentials — never commit these
.env
.env.*
*.pem
*.key
*_secret*
*credentials*
```

Then commit:

```bash
git add -A
git commit --quiet -m "project_manager(scaffold): initialize project layout"
```

Respond to the orchestrator with a one-line summary
(``Initialized project layout: 7 subdirs, git repo, .gitignore``).
**Do not draft any documentation in this task** — that is phase 1's
job.

### 2. End of each phase (N ≥ 1)

After you finalize a phase's deliverable (yours or another agent's),
commit and tag:

```bash
git add -A
git commit --quiet -m "<agent>(phase_<N>_<name>): <short summary>"
git tag phase_<N>_<name>
```

Skip the tag on failure — we want a diff between successful phases,
not a tag cemetery. If the working tree is clean (a read-only phase
produced no files), skip the commit AND the tag silently.

### 3. Phase summary

When the orchestrator asks for a "what changed this phase?" summary
or when you're writing the delivery report:

```bash
git log --oneline phase_<N-1>_<name>..HEAD
git diff --stat phase_<N-1>_<name>..HEAD
git diff --name-only phase_<N-1>_<name>..HEAD
```

Use the output as ground truth. Do not paraphrase from memory — cite
the actual file list.

## Read-only queries (anyone may run)

Any agent may query git via ``execute_shell`` for context:

```bash
git status --porcelain          # clean tree? what's uncommitted?
git log --oneline -10           # recent history
git show HEAD:docs/requirement.md   # file contents at HEAD
git diff HEAD~1                 # what changed in the previous commit
git diff --name-only HEAD~1     # file names only
```

These never mutate state — safe anywhere.

## Commit subject format

```
<agent>(<scope>): <verb phrase, ≤50 chars of body>
```

Where ``<scope>`` is ``scaffold`` for project init, or
``phase_<N>_<name>`` for phase work. Examples:

```
product_manager(scaffold): initialize project layout
product_manager(phase_1_requirements): PRD + 8 use-case diagrams
architect(phase_2_architecture): C4 system context + container views
developer(phase_3_implementation): game engine + 12 tests passing
qa_engineer(phase_5_integration_testing): 124/124 tests, coverage 82%
product_manager(phase_6_delivery): delivery report with metrics
```

Keep the subject ≤72 chars total (git convention). The first line of
your response to the orchestrator can BE the commit subject verbatim
— informative and terse.

## Anti-patterns to avoid

- **Don't commit on read-only phases**. If an agent only did
  ``read_file`` / ``execute``, ``git status --porcelain`` is empty —
  skip the commit and the tag silently.
- **Don't run ``git reset --hard`` / ``git clean -fd`` /
  ``git checkout --``**. They destroy uncommitted work from the
  current phase. If you need to undo, revert the specific files with
  ``git checkout HEAD -- <path>``.
- **Don't create branches**. The project repo stays on one branch
  (usually ``master``). There is no reviewer to merge a side branch.
- **Don't ``git push`` or add remotes**. The project repo has no
  remote — these commands either fail or reach out to the wrong
  place.
- **Don't edit ``.git/`` directly**. Ever.
- **Don't double-tag a phase**. Tags are created once per phase on
  success. If you need to move a tag (genuine retry), delete the old
  one first: ``git tag -d phase_N_name && git tag phase_N_name``.
