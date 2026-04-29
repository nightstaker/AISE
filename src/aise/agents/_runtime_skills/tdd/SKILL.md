---
name: tdd
description: Test-Driven Development workflow that enforces 1:1 mapping between source files and test files
---

# TDD (Test-Driven Development) Skill

## When to Use

Use this skill whenever you are asked to implement source code. Every implementation task MUST follow this workflow.

## Core Rule: 1:1 File Mapping

Every source file MUST have a corresponding test file at the location
the language's test runner expects. Naming and directory layout depend
on the project's language — pick the row that matches your stack and
follow the example. Do **not** default to Python conventions when the
project is in another language.

| Language | Source File | Test File |
| -------- | ----------- | --------- |
| Python (pytest) | `src/entities.py` | `tests/test_entities.py` |
| Python (pytest, nested package) | `src/core/snake.py` | `tests/test_core_snake.py` |
| TypeScript (vitest) | `src/entities.ts` | `tests/entities.test.ts` |
| TypeScript (jest, co-located) | `src/entities.ts` | `src/entities.test.ts` |
| JavaScript (vitest / jest) | `src/entities.js` | `tests/entities.test.js` |
| Go | `internal/entities/entities.go` | `internal/entities/entities_test.go` |
| Rust (separate test) | `src/entities.rs` | `tests/entities.rs` |
| Rust (in-file test module) | `src/entities.rs` | `#[cfg(test)] mod tests { ... }` block in the same file |
| Java (Maven / Gradle) | `src/main/java/com/x/Entities.java` | `src/test/java/com/x/EntitiesTest.java` |
| Kotlin | `src/main/kotlin/com/x/Entities.kt` | `src/test/kotlin/com/x/EntitiesTest.kt` |
| C# / .NET | `src/Entities.cs` | `tests/EntitiesTests.cs` |

**NEVER put all tests into a single file.** Each test file tests
exactly one source module.

## Workflow: Module-by-Module TDD

For each module you need to implement, execute this cycle **one
module at a time**.

### Step 1 — RED: Write the test file FIRST

Use the test path matching your language and runner (see the table above).

```
# Python
write_file("tests/test_<module>.py", <test code>)
# TypeScript (vitest)
write_file("tests/<module>.test.ts", <test code>)
# Go
write_file("internal/<pkg>/<module>_test.go", <test code>)
# Rust
write_file("tests/<module>.rs", <test code>)
# Java
write_file("src/test/java/.../<Module>Test.java", <test code>)
```

The test file must:
- Import from / reference the corresponding source file
- Cover the public API: constructors, methods, properties
- Include edge cases and error conditions
- Be runnable with the project's test runner (pytest / vitest /
  jest / `go test` / `cargo test` / `mvn test` / `dotnet test` …)

### Step 2 — GREEN: Write the source file

Use the source path matching your language (see the table above).

```
# Python
write_file("src/<module>.py", <implementation>)
# TypeScript
write_file("src/<module>.ts", <implementation>)
# Go
write_file("internal/<pkg>/<module>.go", <implementation>)
# Rust
write_file("src/<module>.rs", <implementation>)
# Java
write_file("src/main/java/.../<Module>.java", <implementation>)
```

The source file must:
- Implement exactly what the tests expect
- Be complete, runnable code — not stubs or TODOs

### Step 3 — Move to the next module

**Do NOT go back and rewrite previous files.** Move forward:

```
Module 1: tests/<entities-test> → src/<entities-source>    ✓ done, move on
Module 2: tests/<collision-test> → src/<collision-source>  ✓ done, move on
Module 3: tests/<scoring-test> → src/<scoring-source>      ✓ done, move on
...
```

## Execution Order

When given multiple modules to implement, follow this order:

1. **Data models / entities first** (classes with no dependencies on other source modules)
2. **Utility modules next** (collision detection, scoring, input handling)
3. **Integration / engine last** (the module that wires everything together)

For each module, always write the test file BEFORE the source file.

## Anti-Patterns to Avoid

- **Single test file**: NEVER collapse all tests into one file (e.g.
  `tests/test_game.py`, `tests/all.test.ts`, `internal/all_test.go`).
  Split by module.
- **Rewriting completed files**: Once a module pair (test + source) is
  written, do NOT rewrite it. Move on.
- **Skipping tests**: NEVER write source code without its test
  counterpart first.
- **Runner scripts**: NEVER create wrapper scripts (e.g.
  `run_pytest.py`, `run_tests.sh`, `test_runner.js`, `runtests.go`,
  `RunAllTests.java`). The orchestrator runs the tests directly.
- **Stubs / TODOs**: Every file must be complete, working code. No
  `pass` / `# TODO` (Python), `// TODO` (TS / Go / Java),
  `panic!("todo")` (Rust), `throw new Error("not implemented")`
  (TS / Java) placeholders.
- **"Silent no-op when uninitialized" tests**: NEVER write a test
  asserting that calling `render()` / `update()` / a request
  handler / etc. on an *uninitialized* instance is "a graceful
  no-op". That test codifies a wiring bug as desired behaviour —
  it lets the integration phase ship a half-constructed object
  whose unit tests pass while the runtime UI is blank. The correct
  test for "render before initialize" is
  `pytest.raises(RuntimeError)` (or the language equivalent),
  matching the loud-failure pattern the `entry_point_wiring` skill
  mandates in the source.
- **Mocking the display surface in integration tests**: For
  UI-required projects (`stack_contract.ui_required == true`),
  integration tests MUST run against a real headless surface
  (`SDL_VIDEODRIVER=dummy` + real `pygame.Surface`,
  `QT_QPA_PLATFORM=offscreen` + real `QImage`, headless Chromium
  via Playwright for web stacks). `MagicMock`-ing the screen makes
  every blit/draw call succeed against a fake — wiring bugs that
  the integration test exists to catch then sail through. At least
  one integration test must assert a pixel-level invariant on the
  real surface.

## Example Session

Task: "Implement entities, collision, and game_engine modules"
(language inferred from project config — example below shows Python;
the same shape applies to other languages with paths swapped).

```
Step 1: write_file("tests/test_entities.py", ...)     # RED
Step 2: write_file("src/entities.py", ...)             # GREEN
Step 3: write_file("tests/test_collision.py", ...)     # RED
Step 4: write_file("src/collision.py", ...)            # GREEN
Step 5: write_file("tests/test_game_engine.py", ...)   # RED
Step 6: write_file("src/game_engine.py", ...)          # GREEN
Step 7: Respond with a summary of what was created.    # DONE
```

Total: 6 files written (3 test + 3 source), then STOP.

For TypeScript / Go / Rust / Java, the structure is identical — only
the file paths and extensions change (see the table at the top).
