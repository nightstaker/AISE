"""Regression tests for the architect-defined stack contract that
gates the rest of the pipeline.

Three guarantees are exercised:

1. ``_load_stack_contract_block`` — the helper that turns
   ``docs/stack_contract.json`` into a ``=== STACK CONTRACT ===``
   block prepended to every worker dispatch. Missing / malformed
   files must return ``""`` (back-compat with old projects). Valid
   contracts must produce a deterministic, key-ordered block.

2. ``dispatch_task`` — when the project root contains a stack
   contract, the worker prompt MUST start with both the user
   requirement block and the contract block (contract first, then
   requirement, then the orchestrator-drafted task description).
   Without the project root or contract, the task description must
   pass through unchanged.

3. ``safety_net`` — the new ``architecture_expectations()`` and
   ``qa_expectations()`` helpers must list the structured artifacts
   their phase produces, so a missing contract / report triggers a
   re-dispatch.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from aise.runtime.models import AgentState
from aise.runtime.runtime_config import RuntimeConfig
from aise.runtime.safety_net import (
    REPAIR_ACTIONS,
    ExpectedArtifact,
    _artifact_present,
    architecture_expectations,
    qa_expectations,
    scaffolding_expectations,
)
from aise.runtime.tool_primitives import (
    ToolContext,
    WorkflowState,
    _load_stack_contract_block,
    build_orchestrator_tools,
)

# ---------------------------------------------------------------------------
# 1. Contract loader
# ---------------------------------------------------------------------------


class TestLoadStackContractBlock:
    def test_returns_empty_when_project_root_is_none(self):
        assert _load_stack_contract_block(None) == ""

    def test_returns_empty_when_file_missing(self, tmp_path):
        assert _load_stack_contract_block(tmp_path) == ""

    def test_returns_empty_for_malformed_json(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text("{not valid")
        assert _load_stack_contract_block(tmp_path) == ""

    def test_returns_empty_when_top_level_is_not_object(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text("[]")
        assert _load_stack_contract_block(tmp_path) == ""

    def test_renders_known_keys_in_canonical_order(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps(
                {
                    # Provide keys in scrambled order to confirm output
                    # follows the canonical _STACK_CONTRACT_KEYS ordering.
                    "ui_kind": "phaser",
                    "language": "typescript",
                    "test_runner": "vitest",
                    "framework_backend": "fastify",
                    "static_analyzer": ["npx tsc --noEmit", "eslint ."],
                    "entry_point": "src/index.ts",
                    "ui_required": True,
                    "framework_frontend": "phaser",
                    "package_manager": "npm",
                    "project_config_file": "package.json",
                    "run_command": "npm run dev",
                    "runtime": "node",
                }
            )
        )
        block = _load_stack_contract_block(tmp_path)
        # Sentinel header + footer
        assert "=== STACK CONTRACT" in block
        assert "=== END STACK CONTRACT ===" in block
        # Each key appears on its own line — and "language" precedes
        # "ui_kind" because the canonical order puts language first.
        lang_idx = block.index("language: typescript")
        uikind_idx = block.index("ui_kind: phaser")
        assert lang_idx < uikind_idx, (
            "block must follow canonical key ordering, not the JSON object's serialization order"
        )
        # Lists are joined with ", " so the orchestrator sees a single
        # readable line per field.
        assert "static_analyzer: npx tsc --noEmit, eslint ." in block

    def test_unknown_keys_are_silently_ignored(self, tmp_path):
        """A future architect might add extra fields. The loader must
        not crash or expose them in the prompt — only the canonical
        keys round-trip."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps(
                {
                    "language": "go",
                    "novel_field_from_the_future": "should not appear in block",
                }
            )
        )
        block = _load_stack_contract_block(tmp_path)
        assert "language: go" in block
        assert "novel_field_from_the_future" not in block


# ---------------------------------------------------------------------------
# 2. dispatch_task injection behaviour
# ---------------------------------------------------------------------------


def _build_ctx(root: Path | None, *, requirement: str = "") -> ToolContext:
    """Construct a ToolContext with a single mocked-out worker
    runtime called ``developer`` (returns ``"ok"`` from
    ``handle_message``)."""
    fake_rt = MagicMock()
    fake_rt._state = AgentState.ACTIVE
    fake_rt.handle_message.return_value = "ok"
    fake_rt.definition.role = "developer"
    fake_rt.definition.metadata = {}

    manager = MagicMock()
    manager.runtimes = {"developer": fake_rt}
    manager.get_runtime = lambda n: fake_rt if n == "developer" else None

    return ToolContext(
        manager=manager,
        project_root=root,
        config=RuntimeConfig(),
        workflow_state=WorkflowState(),
        original_requirement=requirement,
    )


class TestDispatchTaskInjectsContract:
    def _capture_worker_prompt(self, ctx: ToolContext, task: str) -> str:
        """Helper: invoke dispatch_task, return the exact prompt the
        worker's handle_message received."""
        target = ctx.manager.get_runtime("developer")
        captured = {}
        original_handle = target.handle_message

        def _capture(prompt, **kw):
            captured["prompt"] = prompt
            return original_handle(prompt, **kw)

        target.handle_message = _capture
        tools = build_orchestrator_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        dispatch.invoke({"agent_name": "developer", "task_description": task})
        return captured["prompt"]

    def test_no_contract_no_requirement_passes_task_through(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = _build_ctx(Path(d))
            prompt = self._capture_worker_prompt(ctx, "raw task")
            assert prompt == "raw task"

    def test_requirement_only_prefixes_requirement_block(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = _build_ctx(Path(d), requirement="创建一个贪吃蛇游戏")
            prompt = self._capture_worker_prompt(ctx, "Implement X")
            assert "=== ORIGINAL USER REQUIREMENT" in prompt
            assert "创建一个贪吃蛇游戏" in prompt
            assert "Implement X" in prompt
            # No contract block when the file is absent.
            assert "=== STACK CONTRACT" not in prompt

    def test_contract_present_prepends_block_before_requirement(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            (root / "docs" / "stack_contract.json").write_text(
                json.dumps(
                    {
                        "language": "typescript",
                        "framework_backend": "fastify",
                        "test_runner": "vitest",
                        "entry_point": "src/index.ts",
                        "run_command": "npm run dev",
                        "ui_required": False,
                        "ui_kind": "",
                    }
                )
            )
            ctx = _build_ctx(root, requirement="Build a tower defense game")
            prompt = self._capture_worker_prompt(ctx, "Implement auth module")
            # All three blocks present
            assert "=== STACK CONTRACT" in prompt
            assert "=== ORIGINAL USER REQUIREMENT" in prompt
            assert "Implement auth module" in prompt
            # Order: STACK CONTRACT first, then user requirement, then task
            stack_idx = prompt.index("=== STACK CONTRACT")
            req_idx = prompt.index("=== ORIGINAL USER REQUIREMENT")
            task_idx = prompt.index("Implement auth module")
            assert stack_idx < req_idx < task_idx, (
                f"prompt ordering wrong: stack={stack_idx} req={req_idx} task={task_idx}"
            )
            # Specific stack values reach the worker
            assert "language: typescript" in prompt
            assert "framework_backend: fastify" in prompt

    def test_contract_alone_without_requirement_still_prepends(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            (root / "docs" / "stack_contract.json").write_text(
                json.dumps(
                    {
                        "language": "go",
                        "test_runner": "go test",
                    }
                )
            )
            ctx = _build_ctx(root)  # empty requirement
            prompt = self._capture_worker_prompt(ctx, "do thing")
            assert "=== STACK CONTRACT" in prompt
            assert "language: go" in prompt
            # No ORIGINAL USER REQUIREMENT (nothing to prepend)
            assert "=== ORIGINAL USER REQUIREMENT" not in prompt
            assert "do thing" in prompt


# ---------------------------------------------------------------------------
# 3. safety_net expectations
# ---------------------------------------------------------------------------


class TestArchitectureExpectations:
    def test_lists_architecture_md_and_stack_contract(self):
        exps = architecture_expectations()
        paths = {(e.path, e.kind) for e in exps}
        assert ("docs/architecture.md", "file") in paths
        # docs/stack_contract.json uses the dedicated ``stack_contract``
        # validator kind, not generic json_file. The validator enforces
        # the two-level subsystems[].components[] schema instead of just
        # checking JSON parseability.
        assert ("docs/stack_contract.json", "stack_contract") in paths

    def test_qa_expectations_list_qa_report(self):
        exps = qa_expectations()
        paths = {(e.path, e.kind) for e in exps}
        assert ("docs/qa_report.json", "json_file") in paths


class TestJsonFileArtifact:
    def test_missing_file_fails(self, tmp_path):
        art = ExpectedArtifact(path="docs/x.json", kind="json_file", non_empty=True)
        assert _artifact_present(tmp_path, art) is False

    def test_invalid_json_fails(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.json").write_text("{not json")
        art = ExpectedArtifact(path="docs/x.json", kind="json_file", non_empty=True)
        assert _artifact_present(tmp_path, art) is False

    def test_valid_json_passes(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.json").write_text(json.dumps({"a": 1}))
        art = ExpectedArtifact(path="docs/x.json", kind="json_file", non_empty=True)
        assert _artifact_present(tmp_path, art) is True


class TestMustNotExistArtifact:
    def test_missing_file_passes(self, tmp_path):
        art = ExpectedArtifact(path="package.json", kind="must_not_exist")
        assert _artifact_present(tmp_path, art) is True

    def test_present_file_fails(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        art = ExpectedArtifact(path="package.json", kind="must_not_exist")
        assert _artifact_present(tmp_path, art) is False

    def test_repair_removes_leftover(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        REPAIR_ACTIONS["leftover_file"](tmp_path, {"path": "package.json"})
        assert not (tmp_path / "package.json").exists()

    def test_repair_refuses_path_outside_root(self, tmp_path, caplog):
        # Should be a no-op; no exception, but file outside root is preserved.
        sentinel = tmp_path.parent / "should-not-be-deleted"
        sentinel.write_text("preserve me")
        try:
            REPAIR_ACTIONS["leftover_file"](tmp_path, {"path": "../should-not-be-deleted"})
            assert sentinel.exists(), "repair must not delete files outside the project root"
        finally:
            sentinel.unlink(missing_ok=True)

    def test_repair_refuses_absolute_path(self, tmp_path):
        # Absolute path → no-op, no exception
        REPAIR_ACTIONS["leftover_file"](tmp_path, {"path": "/etc/passwd"})
        # If we reach here without raising, the safeguard worked


class TestScaffoldingMustNotExist:
    def test_scaffolding_lists_common_leftover_files(self):
        exps = scaffolding_expectations()
        leftover_paths = {e.path for e in exps if e.kind == "must_not_exist"}
        # Each is a known carryover-pollution risk we observed in
        # project_5 / project_7 runs.
        for expected in (
            "package.json",
            "node_modules",
            "Cargo.toml",
            "go.mod",
            "pyproject.toml",
            ".coverage",
        ):
            assert expected in leftover_paths, (
                f"scaffolding_expectations should guard against leftover {expected!r} from prior runs"
            )
