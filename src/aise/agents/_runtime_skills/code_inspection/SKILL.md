---
name: code_inspection
description: Run a language-appropriate static analyzer on every source file you write and fix every finding before the module is considered done
---

# Code Inspection Skill

## When to Use

Use this skill whenever you write or modify source code. After the
module's unit tests go green, run the static analyzer for that
language, fix every finding it reports, and re-run the analyzer until
it is clean.

## Workflow (per module)

1. **Write / edit the source file** (following whatever methodology
   the task requires — TDD, bug fix, refactor, etc.).
2. **Run the language-appropriate static analyzer** via the `execute`
   tool against the specific file you just changed. Do NOT scan the
   whole repo — scan only the file(s) you just modified so the
   findings are attributable to your work.
3. **Read every finding**. Treat errors and warnings identically —
   both must be resolved. Do not silence findings with `# noqa`,
   `# type: ignore`, `// eslint-disable`, `//nolint`, or equivalent
   unless the original task or the error message itself explicitly
   requests it. A silenced warning is technical debt, not a fix.
4. **Fix the code**, re-run the analyzer, iterate until the file has
   zero findings.
5. Only then proceed to the next module (or to reporting the module
   complete).

## Language → Toolset

Pick the toolset whose file-extension matches the file you wrote.
Run each tool in the listed order; stop fixing only when both pass
with zero findings. The tools below are all on the shell allowlist.

| Language   | Files                 | Commands                                    |
|------------|-----------------------|---------------------------------------------|
| Python     | `*.py`                | `ruff check <file>` + `mypy <file>`         |
| JavaScript | `*.js` / `*.mjs`      | `eslint <file>`                             |
| TypeScript | `*.ts` / `*.tsx`      | `eslint <file>` + `tsc --noEmit <file>`     |
| Go         | `*.go`                | `go vet ./...` + `gofmt -l <file>`          |
| Rust       | `*.rs`                | `cargo clippy -- -D warnings` + `cargo check` |

If the language of the file is not in this table, skip the inspection
step for that file but note the skip in your response summary. Do NOT
invent a tool that is not on the shell allowlist.

If a tool is not installed on the host, the `execute` call will
return `exit_code != 0` with an error like `command not found`.
Treat that specific failure as "tool unavailable, skip" and say so
in your summary — do NOT retry or bikeshed.

## Typical command shapes

Run these from the project root — `execute_shell` sets the cwd
automatically, so do not prepend `cd`.

```
execute_shell(command="ruff check src/game_engine.py")
execute_shell(command="mypy src/game_engine.py")
execute_shell(command="eslint src/client/app.ts")
execute_shell(command="tsc --noEmit src/client/app.ts")
execute_shell(command="go vet ./internal/game")
execute_shell(command="gofmt -l internal/game/engine.go")
execute_shell(command="cargo clippy -- -D warnings")
```

## Reporting

In the summary you return to the orchestrator, include one line per
file showing the final inspection result:

```
Inspection:
- src/game_engine.py: ruff OK, mypy OK
- src/collision.py:   ruff OK, mypy OK
- src/scoring.py:     ruff OK, mypy skipped (not installed)
```

This lets the orchestrator see at a glance that the module is both
tested AND statically clean.
