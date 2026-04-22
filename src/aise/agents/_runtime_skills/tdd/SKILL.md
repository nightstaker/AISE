---
name: tdd
description: Test-Driven Development workflow that enforces 1:1 mapping between source files and test files
---

# TDD (Test-Driven Development) Skill

## When to Use

Use this skill whenever you are asked to implement source code. Every implementation task MUST follow this workflow.

## Core Rule: 1:1 File Mapping

Every source file under `src/` MUST have a corresponding test file under `tests/`:

| Source File | Test File |
|---|---|
| `src/entities.py` | `tests/test_entities.py` |
| `src/game_engine.py` | `tests/test_game_engine.py` |
| `src/collision.py` | `tests/test_collision.py` |
| `src/scoring.py` | `tests/test_scoring.py` |
| `src/core/snake.py` | `tests/test_core_snake.py` |

**NEVER put all tests into a single file.** Each test file tests exactly one source module.

## Workflow: Module-by-Module TDD

For each module you need to implement, execute this cycle **one module at a time**:

### Step 1 — RED: Write the test file FIRST

```
write_file("tests/test_<module>.py", <test code>)
```

The test file must:
- Import from the corresponding `src/<module>.py`
- Cover the public API: constructors, methods, properties
- Include edge cases and error conditions
- Be runnable with `pytest`

### Step 2 — GREEN: Write the source file

```
write_file("src/<module>.py", <implementation>)
```

The source file must:
- Implement exactly what the tests expect
- Be complete, runnable Python — not stubs or TODOs

### Step 3 — Move to the next module

**Do NOT go back and rewrite previous files.** Move forward:

```
Module 1: tests/test_entities.py → src/entities.py    ✓ done, move on
Module 2: tests/test_collision.py → src/collision.py   ✓ done, move on
Module 3: tests/test_scoring.py → src/scoring.py       ✓ done, move on
...
```

## Execution Order

When given multiple modules to implement, follow this order:

1. **Data models / entities first** (classes with no dependencies on other src modules)
2. **Utility modules next** (collision detection, scoring, input handling)
3. **Integration / engine last** (the module that wires everything together)

For each module, always write `tests/test_<name>.py` BEFORE `src/<name>.py`.

## Anti-Patterns to Avoid

- **Single test file**: NEVER write all tests into one `tests/test_game.py`. Split by module.
- **Rewriting completed files**: Once a module pair (test + src) is written, do NOT rewrite it. Move on.
- **Skipping tests**: NEVER write `src/` code without its `tests/` counterpart first.
- **Runner scripts**: NEVER create `run_pytest.py`, `test_runner.py`, etc. The orchestrator runs tests.
- **Stubs/TODOs**: Every file must be complete, working code. No `pass` or `# TODO` placeholders.

## Tests That Touch the Filesystem

When a test needs a temporary directory or file on disk (config stores,
cache files, SQLite databases, downloaded fixtures, etc.), use pytest's
built-in `tmp_path` / `tmp_path_factory` fixtures — NEVER create a
directory next to the test file.

**Forbidden** (leaks junk into `tests/` on every run and has no
cleanup):

```python
# WRONG — leaves tests/temp_settings/, tests/temp_settings2/, … on disk
def _create_manager(self):
    temp_dir = os.path.join(os.path.dirname(__file__), "temp_settings")
    os.makedirs(temp_dir, exist_ok=True)
    return SettingsManager(storage_path=os.path.join(temp_dir, "settings.json"))
```

**Correct**:

```python
# RIGHT — pytest auto-cleans tmp_path after the test
def test_defaults(tmp_path):
    mgr = SettingsManager(storage_path=str(tmp_path / "settings.json"))
    assert mgr.get_setting("audio_master") == 0.8
```

For class-based tests, accept `tmp_path` as a normal test-method
parameter (pytest injects it) or share one via `tmp_path_factory` on a
fixture:

```python
@pytest.fixture
def settings_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("settings")
```

If `tmp_path` is genuinely unavailable for some reason, fall back to
`tempfile.TemporaryDirectory()` used as a context manager so the dir
is removed on exit. NEVER write to
`os.path.dirname(__file__) + "/<anything>"` — that's the test file's
own directory and anything you create there is permanent state.

**No numeric suffixes to avoid collisions.** If you find yourself
reaching for `temp_settings2`, `temp_settings3`, `temp_settings_v2`,
etc., stop: you're working around a bug. Use `tmp_path` instead and
each test automatically gets its own isolated directory.

## Example Session

Task: "Implement entities.py, collision.py, and game_engine.py"

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
