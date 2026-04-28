---
name: entry_point_wiring
description: Wire the runnable entry point so every subsystem with a public initialize()/setup()/start() method is actually invoked at boot, and forbid silent-noop guards that hide wiring bugs
---

# Entry-Point Wiring Skill

## When to Use

Use this skill whenever the task is to write the project's main entry
file (`src/main.py`, `src/index.ts`, `cmd/<app>/main.go`,
`src/main.rs`, `src/main/java/.../App.java`, `src/Program.cs`, etc.) —
i.e. the file that boots the whole application.

This skill is the bridge between the per-component code the developer
already wrote (each module is unit-tested in isolation) and the
running application a human will actually launch. It exists because
"construct every subsystem in `__init__`" is **NOT** the same as
"initialise every subsystem" — many components use a two-phase
construct/initialize pattern (constructors are cheap, `initialize()`
loads fonts, opens sockets, allocates GPU resources, etc.).
Forgetting the second phase is the single most common reason a
project's tests pass 100% yet the deployed application shows a blank
window or returns 500 on every request.

## Core Contract — 4 mandatory steps in the entry file

For each subsystem listed in `docs/stack_contract.json#/subsystems[]`,
the entry file MUST execute the following four steps **in this exact
order**. Skipping any step is a wiring bug; doing them out of order
is a wiring bug.

### Step A — CONSTRUCT every subsystem instance

Instantiate every component listed under
`stack_contract.json#/subsystems[].components[]` using its public
constructor. Constructors should be cheap and side-effect-free; they
are NOT the place to load resources.

```python
self.menu = MenuUI()
self.hud  = HUDUI()
self.snake = SnakeEngine(grid_size=(40, 30))
# ...one line per component...
```

### Step B — call every LIFECYCLE INIT

Read the architect's lifecycle list from `docs/stack_contract.json`:

```json
"lifecycle_inits": [
  {"attr": "menu",  "method": "initialize"},
  {"attr": "hud",   "method": "initialize"},
  {"attr": "scene", "method": "initialize"},
  {"attr": "snake", "method": "initialize"}
]
```

Iterate it deterministically. Do **NOT** copy-paste a hand-picked
subset; the loop is the contract.

```python
for entry in stack_contract["lifecycle_inits"]:
    target = getattr(self, entry["attr"])
    method = getattr(target, entry["method"])
    method()
```

If your stack does not yet declare `lifecycle_inits[]`, scan your own
component code and call `<obj>.initialize()` on every component that
exposes a public `initialize()` / `setup()` / `start()` /
`bootstrap()` method whose body is more than `pass`. Then add the
list to `stack_contract.json` and notify the architect — a missing
`lifecycle_inits[]` is a contract gap, not a developer freedom.

### Step C — enter the FRAMEWORK MAIN LOOP

Hand control to the framework's native run/exec/listen call:

| Stack | Main-loop call |
| ----- | -------------- |
| pygame | `while running: handle_events(); update(); render(); pygame.display.flip(); clock.tick(fps)` |
| Qt (PyQt / PySide) | `app.exec()` |
| arcade | `arcade.run()` |
| FastAPI / Flask / Express | `uvicorn.run(app, ...)` / `app.run(...)` / `app.listen(port)` |
| React / Vue / Svelte | `ReactDOM.createRoot(el).render(...)` / `createApp(App).mount(el)` / `new App({ target: el })` |
| Phaser / pixi.js | `new Phaser.Game(config)` / `new PIXI.Application({...})` |
| Bevy | `App::new().add_plugins(...).run()` |
| Spring Boot | `SpringApplication.run(App.class, args)` |

A simulated loop that prints status lines (`while True: print(...);
time.sleep(...)`) is **NOT** a main loop. If your framework does not
have one of the above patterns, reread the architecture doc — the
framework choice was probably wrong.

### Step D — SELF-CHECK assertion

Before `if __name__ == "__main__":` (or the language's equivalent
top-level guard), add a self-check that walks the lifecycle list and
asserts every entry was reached. The assertion is the developer's
last line of defence against forgetting Step B.

```python
def _self_check_lifecycle(self) -> None:
    """Fail fast if any subsystem skipped its initialize() call."""
    for entry in stack_contract["lifecycle_inits"]:
        target = getattr(self, entry["attr"])
        # Each subsystem with a public initialize() MUST also expose
        # a public is_initialized() or _initialized flag set by
        # initialize(). The architect's interface contract requires it.
        if not getattr(target, "_initialized", False):
            raise RuntimeError(
                f"lifecycle wiring bug: {entry['attr']}."
                f"{entry['method']}() never reached"
            )
```

Call `_self_check_lifecycle()` immediately after Step B and again
once the main loop has rendered the first frame (when applicable).

## Banned anti-pattern: silent-noop guards

A defensive guard like the following in a `render` / `update` /
`handle_*` method **is forbidden**:

```python
def render(self, screen):
    if self._font is None:        # BANNED — silent no-op
        return
    ...
```

Why it is banned: the guard converts a wiring bug ("Step B was
skipped") into invisible product behaviour ("the game ships with a
blank screen"). The bug becomes visible only to the end user; CI,
unit tests, integration tests, and process-survival smoke checks
all pass.

The correct pattern is to **fail loudly** at the first call:

```python
def render(self, screen):
    if self._font is None:
        raise RuntimeError(
            f"{type(self).__name__}.render() called before initialize()"
        )
    ...
```

If a unit test legitimately needs to call `render()` on an
uninitialized instance (e.g. to verify the guard itself), the test
must use `pytest.raises(RuntimeError)` (or the language equivalent).
A test that asserts "render-without-initialize is a graceful no-op"
is itself a wiring bug — see `tdd` skill anti-patterns.

## Required RUN: line

Entry-point tasks MUST end with a single line:

```
RUN: <command to launch the app from project root>
```

This is the same line documented in `developer.md`'s Entry Point
Files section — keep it. The QA agent's UI Validation step needs it
to drive the pixel-smoke check.

## Self-verify before reporting done

Before closing the entry-point task, run the following sanity sweep
in your final response:

1. Count `getattr(self, ...)` /  member assignments in `__init__`
   and confirm every `subsystems[].components[]` has a matching
   member.
2. Count lifecycle-init invocations (the loop in Step B) and confirm
   it matches the length of `stack_contract.lifecycle_inits[]`.
3. Confirm `_self_check_lifecycle` is called on the boot path.
4. Confirm no `if self._<x> is None: return` exists inside any
   `render` / `update` / `handle_*` method you can grep for. If you
   find one in a component you authored, fix it now — do not defer.

Report each of the four counts in your final summary so QA can
cross-check them against the contract.
