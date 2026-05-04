# Changelog

## Unreleased

### waterfall_v2 phase-executor PR (branch: `feat/waterfall-v2-phase-executor`)

Replaces the hand-coded 7-phase tuple list in `project_session.py`
(`_build_initial_phase_prompts`) with a process.md-driven runner that
walks each phase through a strict PRODUCE / AUTO_GATE / REVIEWER /
DECISION state machine.

#### Why

The 4-hour stuck run on `project_1-tower` exposed three structural
issues in the previous flow:

1. The `process_type="waterfall"` knob loaded
   `waterfall.process.md` only as documentation — the actual phase
   sequence was hard-coded in Python and silently included BDD/TDD
   phases (`scenario_implementation`) that the markdown spec never
   declared.
2. There was no per-phase review gate; the only feedback signal
   was per-task `expected_artifacts` string-match, and even that
   silently emitted `status="completed"` regardless of whether
   shortfalls remained after retries.
3. Per-language Python dictionaries (`_LANGUAGE_TOOLCHAIN`,
   `_INTERFACE_FILENAME`, `_LANGUAGE_TEST_EXT`) silently fell back
   to Python conventions for unknown languages — Unity (csharp) got
   `__init__.py` artifacts and `pytest` test paths in a `dotnet`
   project tree.

#### What's new

* **`src/aise/processes/waterfall_v2.process.md`** — the new spec.
  Six phases with explicit `producer` / `reviewer` assignments,
  structured `acceptance:` predicates, declared fanout (subsystem_dag,
  scenario_parallel), and `mode_when_runner_unavailable` for
  sandbox-degraded verification.
* **`src/aise/schemas/*.schema.json`** — process spec, requirement
  contract, stack contract, behavioral contract; all validated by
  the hand-rolled `aise.runtime.json_schema_lite`.
* **`src/aise/runtime/waterfall_v2_loader.py`** — `load_waterfall_v2`
  parses the markdown frontmatter and returns a strictly-typed
  `WaterfallV2Spec` dataclass tree.
* **`src/aise/runtime/predicates.py`** — registry of acceptance
  predicates: `file_exists`, `min_bytes`, `contains_sections`,
  `regex_count`, `schema`, `language_supported`, `min_scenarios`,
  `contains_all_lifecycle_inits`, `prior_phases_summarized`,
  `mermaid_validates_via_skill`, `language_idiomatic_check`. Skipped
  predicates count as PASS for ALL_PASS gating.
* **`src/aise/tools/dispatch.py`** — bumped per-task retries 1 → 3
  and added the post-retry shortfall check that emits
  `status="incomplete"` (was unconditionally `"completed"`).
  `dispatch_tasks_parallel` now reports `incomplete` count alongside
  `completed` / `failed`.
* **`src/aise/runtime/concurrent_executor.py`** — `run_parallel`,
  `run_grouped`, `run_dag` for fanout stages with strict ALL_PASS
  join. Same-group tasks serialize; cross-group tasks parallelize up
  to the worker cap. No early cancellation: failed siblings still
  collect their results so one resume invocation can address all
  failures.
* **`src/aise/runtime/reviewer.py`** — `run_review_loop` with
  Decision 1 (revise_budget=3, on_revise_exhausted=continue_with_marker)
  and Decision 2 (feedback prepended verbatim to producer prompt).
  Reviewer dispatch goes through caller-provided callable so model
  selection follows `agent_model_selection` config.
* **`src/aise/runtime/phase_executor.py`** — `PhaseExecutor` ties
  c1/c2/c5/c6/c7 together. Single-writer phases pass derived paths
  to the producer; fanout phases use ConcurrentExecutor with strict
  ALL_PASS. AUTO_GATE re-evaluates after producer returns, with a
  3-attempt budget that re-prompts on each failure.
* **`src/aise/runtime/waterfall_v2_driver.py`** — `WaterfallV2Driver`
  walks all 6 phases, re-loads contracts before each phase, saves
  halt state on producer hard fail, supports resume.
* **`src/aise/runtime/halt_resume.py`** — halt-state persistence
  (`<project_root>/runs/HALTED.json`) and resume planning. No
  rollback (Decision 4): halts stop in place, user inspects, resume
  picks up at the failed phase's PRODUCE.
* **`src/aise/runtime/observability.py`** — process-global
  `TaskRegistry` with `register_task` / `record_llm_call` /
  `mark_completed` / `request_abort`. Without budget caps (Decision
  1: no wall-clock), the operator's only signal is `elapsed_seconds`
  + `llm_call_count` + `loop_detector_hits`. The registry surfaces
  these to the web UI; `check_abort` lets tasks raise `AbortRequested`
  on operator command.
* **`src/aise/runtime/runner_probe.py`** — probes
  `stack_contract.test_cmd` for sandbox availability so the
  verification phase can degrade to `write_only` mode when the
  declared runner isn't installed (the project_1-tower failure
  mode: dotnet not on PATH, so the developer's TDD loop in
  qwen3.6-35b couldn't ever converge).
* **`src/aise/runtime/agent_acl.py`** — per-role write whitelist.
  Architect can write `docs/**` only; developer owns `src/**` /
  `lib/**` / `Assets/**` / `tests/**`. Closes the project_1-tower
  regression where the architect agent wrote 248 `.cs` files into
  `Assets/Scripts/` during a phase 2 retry.
* **`src/aise/runtime/stack_strict.py`** — strict accessors that
  raise `UnsupportedLanguageError` on unknown language instead of
  silently falling back to Python. Replaces three `.get(lang,
  ...["python"])` call sites in the legacy dispatch flow once it's
  retired.
* **`src/aise/runtime/policy_backend.py`** — extends loop_detector
  to `read_file` / `ls` / `execute` (5 identical calls in a row →
  `LOOP_DETECTED` error). Catches the `read_file` 7× / `execute`
  4× / `ls` 9× patterns observed during project_1-tower.

#### Decisions baked in

| Decision | Where |
|---|---|
| 1. ALL_PASS reviewer + revise_budget=3, continue_with_marker on exhaustion | `waterfall_v2.process.md` + `reviewer.py` |
| 2. Reviewer feedback prepended verbatim to producer prompt | `reviewer.prepend_reviewer_feedback` |
| 3. Producer per-task 3-retry; ALL_PASS fanout halts on any sub-task fail | `dispatch.py` + `concurrent_executor.py` |
| 4. No rollback; halt + resume only | `halt_resume.py` + `waterfall_v2_driver.py` |
| 5. No budget caps (no wall-clock, no max_dispatches) | absent from spec; observability + abort_task instead |
| 6. Reviewer model from `agent_model_selection` config | `reviewer.py` (LLM-agnostic dispatcher) |

#### Migration path

* New projects with `process_type="waterfall_v2"` use the new flow
  via `WaterfallV2Driver`.
* Existing projects with `process_type="waterfall"` keep the legacy
  `_build_initial_phase_prompts` flow until the user opts in.
* The legacy `_LANGUAGE_TOOLCHAIN.get(lang, ...["python"])` call
  sites in `aise.tools.dispatch` and `aise.tools.task_descriptions`
  remain in place to keep the legacy flow working; they go away in
  a follow-up cleanup commit once all callers (web app, CLI, tests)
  have migrated.

#### Test count by commit

| commit | added tests |
|---|---:|
| c1 process spec + loader | 25 |
| c2 acceptance predicates | 35 |
| c5 dispatch retry+gate | 7 |
| c6 ConcurrentExecutor | 15 |
| c7 Reviewer | 26 |
| c3 PhaseExecutor | 10 |
| c8 loop_detector ext | 7 |
| c10 runner_probe | 13 |
| c13 agent_acl | 18 |
| c12 stack_strict | 18 |
| c11 halt + resume | 18 |
| c9 observability | 17 |
| c4 WaterfallV2Driver | 6 |
| c14 e2e + this CHANGELOG | 9 |
| **total** | **~224** |
