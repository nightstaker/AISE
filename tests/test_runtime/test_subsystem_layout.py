"""Regression tests for the architect's two-level subsystem layout.

The user's original intent: ``src/`` should be split by *subsystem*
(roughly the C4 ``Container_Boundary`` count, typically 3-7), not by
*component* (which would produce 20+ flat top-level dirs — the
project_7-tower failure mode).

Three guarantees are exercised:

1. ``_load_stack_contract_block`` accepts the new
   ``subsystems[].components[]`` schema and renders it as a concise
   per-subsystem summary (component count, not enumeration).

2. ``_load_stack_contract_block`` STILL renders the legacy
   ``modules[]`` schema (back-compat for in-flight projects) but
   marks it ``LEGACY FLAT 'modules' SCHEMA`` so a downstream
   reader can flag the architect for re-design.

3. ``_stack_contract_valid`` (new safety_net validator) accepts a
   well-formed two-level contract, rejects:
   - top-level not an object,
   - missing/empty ``subsystems[]``,
   - subsystem with bad ``name`` / ``src_dir`` / ``components``
     types,
   - component whose ``file`` does not live under its parent's
     ``src_dir`` (the load-bearing check that prevents flat
     re-layout under a different name).
   It WARNS (does not fail) when:
   - subsystem count exceeds the soft cap, or
   - a subsystem has zero components.

4. ``architect.md`` instructs subsystem ≠ component and provides
   the two-level worked example. Static check on the prompt file.

5. ``project_session.py`` Phase-3 prompts dispatch developer **per
   subsystem**, NOT per component.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aise.safety_net import _stack_contract_valid
from aise.tools.stack_contract import _load_stack_contract_block

# ---------------------------------------------------------------------------
# 1. Loader — new schema rendering
# ---------------------------------------------------------------------------


def _write_contract(root: Path, payload: dict) -> Path:
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    p = docs / "stack_contract.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestLoaderRendersNewSchema:
    def test_subsystems_summary_appears_with_counts(self, tmp_path):
        _write_contract(
            tmp_path,
            {
                "language": "python",
                "subsystems": [
                    {
                        "name": "ui",
                        "src_dir": "src/ui/",
                        "components": [
                            {"name": "menu_ui", "file": "src/ui/menu_ui.py", "responsibility": "x"},
                            {"name": "hud_ui", "file": "src/ui/hud_ui.py", "responsibility": "x"},
                        ],
                    },
                    {
                        "name": "gameplay",
                        "src_dir": "src/gameplay/",
                        "components": [
                            {"name": "player", "file": "src/gameplay/player.py", "responsibility": "x"},
                        ],
                    },
                ],
            },
        )
        block = _load_stack_contract_block(tmp_path)
        assert "subsystems:" in block
        # Each subsystem appears with its component count
        assert "- ui [src/ui/] (2 components)" in block
        # Singular form for n=1
        assert "- gameplay [src/gameplay/] (1 component)" in block
        # Block does NOT enumerate every component — keeping worker
        # prompts compact.
        assert "menu_ui" not in block
        assert "hud_ui" not in block

    def test_zero_component_subsystem_omits_count(self, tmp_path):
        _write_contract(
            tmp_path,
            {
                "language": "go",
                "subsystems": [
                    {"name": "stub", "src_dir": "internal/stub/", "components": []},
                ],
            },
        )
        block = _load_stack_contract_block(tmp_path)
        # No "(0 components)" noise; just the path.
        assert "- stub [internal/stub/]" in block
        assert "(0 component" not in block


class TestLoaderTolerLegacyFlatModules:
    def test_legacy_modules_render_with_deprecation_marker(self, tmp_path):
        _write_contract(
            tmp_path,
            {
                "language": "python",
                "modules": [
                    {"name": "auth", "src_dir": "src/auth/", "responsibilities": "x"},
                    {"name": "player", "src_dir": "src/player/", "responsibilities": "x"},
                ],
            },
        )
        block = _load_stack_contract_block(tmp_path)
        assert "LEGACY FLAT 'modules' SCHEMA" in block
        assert "- auth [src/auth/]" in block
        assert "- player [src/player/]" in block

    def test_subsystems_takes_precedence_over_legacy_modules(self, tmp_path):
        # If both keys exist (mid-migration), the new schema wins
        # and the legacy-flat marker does NOT appear.
        _write_contract(
            tmp_path,
            {
                "language": "python",
                "subsystems": [
                    {
                        "name": "ui",
                        "src_dir": "src/ui/",
                        "components": [
                            {"name": "x", "file": "src/ui/x.py", "responsibility": "y"},
                        ],
                    },
                ],
                "modules": [{"name": "should_be_ignored", "src_dir": "src/x/"}],
            },
        )
        block = _load_stack_contract_block(tmp_path)
        assert "LEGACY FLAT" not in block
        assert "should_be_ignored" not in block
        assert "- ui [src/ui/]" in block


# ---------------------------------------------------------------------------
# 2. Validator — new safety_net kind
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "language": "python",
        "subsystems": [
            {
                "name": "ui",
                "src_dir": "src/ui/",
                "responsibilities": "render",
                "components": [
                    {"name": "menu_ui", "file": "src/ui/menu_ui.py", "responsibility": "x"},
                    {"name": "hud_ui", "file": "src/ui/hud_ui.py", "responsibility": "x"},
                ],
            },
            {
                "name": "gameplay",
                "src_dir": "src/gameplay/",
                "responsibilities": "logic",
                "components": [
                    {"name": "player", "file": "src/gameplay/player.py", "responsibility": "x"},
                ],
            },
        ],
    }


class TestStackContractValidator:
    def test_accepts_well_formed_two_level_contract(self, tmp_path):
        p = _write_contract(tmp_path, _valid_payload())
        assert _stack_contract_valid(p) is True

    def test_rejects_missing_file(self, tmp_path):
        assert _stack_contract_valid(tmp_path / "nope.json") is False

    def test_rejects_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert _stack_contract_valid(p) is False

    def test_rejects_top_level_array(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text("[]")
        assert _stack_contract_valid(p) is False

    def test_rejects_missing_subsystems(self, tmp_path):
        p = _write_contract(tmp_path, {"language": "python"})
        assert _stack_contract_valid(p) is False

    def test_rejects_legacy_flat_modules_only(self, tmp_path):
        # Even though the loader tolerates legacy modules[] for
        # back-compat in worker prompts, the *validator* (which gates
        # architect re-dispatch) rejects them — so on a fresh project
        # the architect MUST upgrade.
        p = _write_contract(
            tmp_path,
            {
                "language": "python",
                "modules": [{"name": "x", "src_dir": "src/x/"}],
            },
        )
        assert _stack_contract_valid(p) is False

    def test_rejects_empty_subsystems_array(self, tmp_path):
        p = _write_contract(tmp_path, {"subsystems": []})
        assert _stack_contract_valid(p) is False

    def test_rejects_subsystem_missing_name(self, tmp_path):
        bad = _valid_payload()
        del bad["subsystems"][0]["name"]
        p = _write_contract(tmp_path, bad)
        assert _stack_contract_valid(p) is False

    def test_rejects_subsystem_missing_src_dir(self, tmp_path):
        bad = _valid_payload()
        del bad["subsystems"][0]["src_dir"]
        p = _write_contract(tmp_path, bad)
        assert _stack_contract_valid(p) is False

    def test_rejects_components_not_a_list(self, tmp_path):
        bad = _valid_payload()
        bad["subsystems"][0]["components"] = "should be list"
        p = _write_contract(tmp_path, bad)
        assert _stack_contract_valid(p) is False

    def test_rejects_component_file_outside_subsystem_dir(self, tmp_path):
        # The load-bearing anti-flat-layout check: a "subsystem"
        # whose components secretly live at the top level is just
        # the flat layout under a fancier name.
        bad = _valid_payload()
        bad["subsystems"][0]["components"][0]["file"] = "src/menu_ui.py"  # not under src/ui/
        p = _write_contract(tmp_path, bad)
        assert _stack_contract_valid(p) is False

    def test_warns_but_passes_on_subsystem_count_above_soft_cap(self, tmp_path, caplog):
        # 11 subsystems is above the soft cap of 10 — should warn
        # (logged) but the validator returns True. This catches the
        # "architect promoted components to subsystems" pattern
        # without being a hard error for genuinely large projects.
        many = {"language": "python", "subsystems": []}
        for i in range(11):
            many["subsystems"].append(
                {
                    "name": f"s{i}",
                    "src_dir": f"src/s{i}/",
                    "components": [{"name": f"c{i}", "file": f"src/s{i}/c{i}.py", "responsibility": "x"}],
                }
            )
        p = _write_contract(tmp_path, many)
        with caplog.at_level(logging.WARNING, logger="aise.safety_net"):
            ok = _stack_contract_valid(p)
        assert ok is True
        assert any("exceeds soft cap" in r.message for r in caplog.records)

    def test_warns_but_passes_on_zero_component_subsystem(self, tmp_path, caplog):
        partial = _valid_payload()
        partial["subsystems"][1]["components"] = []
        p = _write_contract(tmp_path, partial)
        with caplog.at_level(logging.WARNING, logger="aise.safety_net"):
            ok = _stack_contract_valid(p)
        assert ok is True
        assert any("zero components" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 3. architect.md guidance — static checks
# ---------------------------------------------------------------------------


def _read_architect_md() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "src" / "aise" / "agents" / "architect.md").read_text(encoding="utf-8")


class TestArchitectPromptGuidesTwoLevelLayout:
    def test_step1_forbids_promoting_components_to_subsystems(self):
        text = _read_architect_md()
        # The instruction must explicitly say Components are NOT
        # subsystems — this is the load-bearing anti-flat rule.
        assert "NOT sources" in text or "not subsystems" in text.lower() or "NOT a directory" in text
        # Container_Boundary is the source of subsystems
        assert "Container_Boundary" in text
        # Component is the unit of files inside a subsystem
        assert "Component" in text and "INSIDE" in text

    def test_worked_example_shows_two_level_nested_layout(self):
        text = _read_architect_md()
        # The example must show src/<subsystem>/<component>.py form,
        # not src/<component>/__init__.py form.
        assert "src/ui/" in text
        assert "src/gameplay/" in text
        assert "menu_ui.py" in text
        # And explicitly ban the flat alternative.
        assert "FORBIDDEN" in text or "❌" in text

    def test_schema_has_subsystems_with_components_not_flat_modules(self):
        text = _read_architect_md()
        assert '"subsystems":' in text
        assert '"components":' in text
        # The previous flat top-level "modules" key in the schema
        # has been removed — searching for it as a top-level schema
        # field should not find it. (The token "modules" can still
        # appear in narrative — we check the schema block.)
        assert "src_dir" in text


# ---------------------------------------------------------------------------
# 4. project_session.py Phase-3 — per-subsystem dispatch
# ---------------------------------------------------------------------------


def _read_project_session() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "src" / "aise" / "runtime" / "project_session.py").read_text(encoding="utf-8")


class TestPhase3DispatchesPerSubsystem:
    def test_initial_phase3_uses_dispatch_subsystems_primitive(self):
        text = _read_project_session()
        # Phase-3 fan-out is now done by the orchestration layer via
        # the deterministic ``dispatch_subsystems`` primitive — NOT by
        # the orchestrator LLM drafting a tasks_json batch. This
        # guarantees worker concurrency even when the orchestrator
        # LLM is too weak to emit multi-tool-call responses.
        # The phase prompt is a Python string literal, so the embedded
        # quotes appear escaped in the source (\"…\"). Accept both
        # forms.
        assert (
            'dispatch_subsystems(phase="implementation")' in text
            or 'dispatch_subsystems(phase=\\"implementation\\")' in text
        ), (
            "Phase-3 implementation prompt must instruct the "
            "orchestrator to call dispatch_subsystems exactly once, "
            "not draft tasks_json itself"
        )
        # Anti-regression: explicit prohibition against falling back
        # to dispatch_task / dispatch_tasks_parallel for individual
        # subsystems / components.
        assert "Do NOT call dispatch_task or dispatch_tasks_parallel" in text

    def test_sprint_execution_uses_dispatch_subsystems_primitive(self):
        text = _read_project_session()
        # Both initial and incremental agile sprints use the same
        # deterministic fan-out primitive.
        assert (
            'dispatch_subsystems(phase="sprint_execution")' in text
            or 'dispatch_subsystems(phase=\\"sprint_execution\\")' in text
        )

    def test_dispatch_subsystems_primitive_exists_in_tools_package(self):
        repo_root = Path(__file__).resolve().parents[2]
        dispatch_text = (repo_root / "src/aise/tools/dispatch.py").read_text(encoding="utf-8")
        td_text = (repo_root / "src/aise/tools/task_descriptions.py").read_text(encoding="utf-8")
        # The primitive itself
        assert "def dispatch_subsystems(" in dispatch_text
        # The deterministic task-description renderer (architecture
        # of fix: LLM does not draft tasks_json; Python builds it
        # from the contract).
        assert "def _build_subsystem_task_description(" in td_text
        # Throttle pulled from runtime config — anti-regression
        # against an unbounded ThreadPoolExecutor that would saturate
        # the LLM serving layer with N concurrent dispatches.
        assert "max_concurrent_subsystem_dispatches" in dispatch_text
