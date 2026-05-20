# tests/fixtures

## `v2_phase_io/` — frozen LLM-output snapshots

Each scenario directory under `v2_phase_io/<scenario>/<phase>/input/` holds
artifacts that an LLM produced during a successful waterfall_v2 end-to-end
run, committed verbatim. Phase-contract tests
(`tests/test_runtime/test_waterfall_v2_*.py` and
`src/aise/testing/phase_test.py`) replay these inputs to validate that the
auto-gate predicates and reviewer flow still accept what we have previously
shipped.

### Do not

- Reformat them. They are excluded from `ruff format` and `ruff check` via
  `tool.ruff.extend-exclude` in `pyproject.toml`; preserving exact bytes is
  the point of a snapshot.
- Hand-edit individual files to make a failing test pass. If a phase
  contract changes, refresh the snapshot from a fresh e2e run instead —
  hand-editing risks producing input that no real LLM would have produced,
  invalidating the test as evidence.
- Pytest-collect them. The `test_*.py` files inside `delivery/`,
  `verification/`, and `main_entry/` are *fixtures* (snapshots of LLM-written
  test files), not real tests. The collection skip is configured in
  `pyproject.toml` via `addopts = "--ignore=tests/fixtures"`.

### How to refresh a scenario

1. Run a clean e2e for the scenario (`aise run …` against a fresh project
   root) using the same model selection / process spec as the test pipeline.
2. Copy the resulting per-phase `input/` directories into
   `tests/fixtures/v2_phase_io/<scenario>/<phase>/input/`.
3. Re-run `pytest tests/test_runtime/test_waterfall_v2_phase_contract.py` and
   confirm it passes against the new snapshot.
4. Commit with a message that names the scenario, the model, and the e2e
   commit/log it came from, so the snapshot is reproducible.

### Adding a new scenario

Follow the existing scenarios as templates (`python_cli_hello_world` is the
most complete; `cpp_wc_cli` is the latest, added with C++ support in #142).
A scenario directory must contain one subdirectory per phase declared in
`waterfall_v2.process.md`. Update `phase_test.py` to register the new
scenario so the matrix picks it up.
