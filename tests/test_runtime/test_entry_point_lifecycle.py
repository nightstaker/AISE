"""Tests for the safety_net entry-point lifecycle validator and the
ui_smoke handler.

These tests cover the new layer-B contract introduced to prevent the
"100% test pass + blank UI" failure mode (project_0-tower regression).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aise.safety_net.entry_point import (
    _entry_point_valid,
    _python_entry_calls,
    _python_has_lifecycle_loop,
)
from aise.safety_net.types import ExpectedArtifact
from aise.safety_net.ui_smoke import _kind_ui_smoke_frame

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


class TestPythonEntryCalls:
    def test_finds_self_attr_method_pairs(self) -> None:
        src = """
class App:
    def __init__(self):
        self.menu = MenuUI()
        self.menu.initialize()
        self.snake.start()
"""
        pairs = _python_entry_calls(src)
        assert ("menu", "initialize") in pairs
        assert ("snake", "start") in pairs

    def test_finds_bare_local_calls(self) -> None:
        src = """
def main():
    menu = MenuUI()
    menu.initialize()
"""
        pairs = _python_entry_calls(src)
        assert ("menu", "initialize") in pairs

    def test_handles_syntax_errors_safely(self) -> None:
        assert _python_entry_calls("def broken(") == set()


class TestPythonHasLifecycleLoop:
    def test_detects_for_loop_over_lifecycle_inits(self) -> None:
        src = """
for entry in stack_contract["lifecycle_inits"]:
    getattr(self, entry["attr"]).initialize()
"""
        assert _python_has_lifecycle_loop(src) is True

    def test_returns_false_when_keyword_absent(self) -> None:
        src = "for x in items: x.do()"
        assert _python_has_lifecycle_loop(src) is False

    def test_returns_false_for_keyword_in_string_only(self) -> None:
        # Keyword is in a docstring/comment but no for-loop iterates it.
        src = '"""mentions lifecycle_inits"""\nx = 1'
        assert _python_has_lifecycle_loop(src) is False


# ---------------------------------------------------------------------------
# Full validator
# ---------------------------------------------------------------------------


def _make_project(
    tmp_path: Path,
    *,
    entry_text: str,
    lifecycle_inits: list[dict] | None,
    components: list[str] | None = None,
) -> Path:
    """Build a synthetic project tree the validator can walk."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    contract: dict = {
        "subsystems": [
            {
                "name": "ui",
                "src_dir": "src/ui",
                "components": [{"name": p.split("/")[-1].rsplit(".", 1)[0], "file": p} for p in (components or [])],
            }
        ],
        "entry_point": "src/main.py",
    }
    if lifecycle_inits is not None:
        contract["lifecycle_inits"] = lifecycle_inits
    (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps(contract))
    (tmp_path / "src" / "main.py").write_text(entry_text)
    return tmp_path


class TestEntryPointValid:
    def test_no_contract_means_no_op(self, tmp_path: Path) -> None:
        # No stack_contract.json at all — nothing to verify.
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is True
        assert missing == []

    def test_contract_without_lifecycle_inits_means_no_op(self, tmp_path: Path) -> None:
        _make_project(tmp_path, entry_text="def main(): pass\n", lifecycle_inits=None)
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is True
        assert missing == []

    def test_empty_lifecycle_inits_means_no_op(self, tmp_path: Path) -> None:
        _make_project(tmp_path, entry_text="def main(): pass\n", lifecycle_inits=[])
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is True
        assert missing == []

    def test_missing_entry_file_fails(self, tmp_path: Path) -> None:
        # Contract declared but entry file absent.
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps({"entry_point": "src/main.py", "lifecycle_inits": [{"attr": "x", "method": "init"}]})
        )
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is False
        assert any("does not exist" in m for m in missing)

    def test_all_lifecycle_calls_present_passes(self, tmp_path: Path) -> None:
        entry = """
class App:
    def __init__(self):
        self.menu = MenuUI()
        self.hud = HUDUI()
        self.menu.initialize()
        self.hud.initialize()
"""
        _make_project(
            tmp_path,
            entry_text=entry,
            lifecycle_inits=[
                {"attr": "menu", "method": "initialize"},
                {"attr": "hud", "method": "initialize"},
            ],
        )
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is True
        assert missing == []

    def test_missing_lifecycle_call_fails_with_diff(self, tmp_path: Path) -> None:
        entry = """
class App:
    def __init__(self):
        self.menu = MenuUI()
        self.hud = HUDUI()
        self.menu.initialize()
        # NOTE: hud.initialize() not called — exact project_0-tower bug.
"""
        _make_project(
            tmp_path,
            entry_text=entry,
            lifecycle_inits=[
                {"attr": "menu", "method": "initialize"},
                {"attr": "hud", "method": "initialize"},
            ],
        )
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is False
        assert any("hud.initialize()" in m for m in missing)

    def test_lifecycle_loop_satisfies_contract(self, tmp_path: Path) -> None:
        # Developer who wrote a deterministic loop is contract-compliant
        # by construction — even if no individual call site is found.
        entry = """
import json
contract = json.loads(open("docs/stack_contract.json").read())
for entry in contract["lifecycle_inits"]:
    getattr(self, entry["attr"]).initialize()
"""
        _make_project(
            tmp_path,
            entry_text=entry,
            lifecycle_inits=[{"attr": "menu", "method": "initialize"}],
        )
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is True
        assert missing == []

    def test_missing_entry_point_field_fails(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps({"lifecycle_inits": [{"attr": "x", "method": "init"}]})
        )
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is False
        assert any("entry_point not declared" in m for m in missing)


# ---------------------------------------------------------------------------
# UI smoke
# ---------------------------------------------------------------------------


def _write_contract(root: Path, *, ui_required: bool) -> None:
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "stack_contract.json").write_text(json.dumps({"ui_required": ui_required}))


def _write_qa_report(root: Path, *, non_bg: int, threshold: int) -> None:
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "qa_report.json").write_text(
        json.dumps(
            {
                "ui_validation": {
                    "required": True,
                    "verdict": "PASS",
                    "reason": "rendered",
                    "pixel_smoke": {
                        "non_bg_samples": non_bg,
                        "threshold": threshold,
                        "frame_path": "artifacts/smoke_frame_0.png",
                        "verdict": "PASS" if non_bg >= threshold else "FAIL",
                    },
                }
            }
        )
    )


def _write_screenshot(root: Path, *, size_bytes: int = 1000) -> None:
    (root / "artifacts").mkdir(exist_ok=True)
    (root / "artifacts" / "smoke_frame_0.png").write_bytes(b"\x00" * size_bytes)


class TestUISmokeFrame:
    artifact = ExpectedArtifact(
        path="artifacts/smoke_frame_0.png",
        kind="ui_smoke_frame",
        non_empty=True,
    )

    def test_no_contract_short_circuits_to_satisfied(self, tmp_path: Path) -> None:
        # Contract not yet written — nothing to validate, treat as ok.
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is True

    def test_headless_project_short_circuits_to_satisfied(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=False)
        # No screenshot, no qa_report — still satisfied because UI not required.
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is True

    def test_ui_required_missing_screenshot_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=True)
        _write_qa_report(tmp_path, non_bg=49796, threshold=50)
        # screenshot absent
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_ui_required_blank_frame_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=True)
        _write_screenshot(tmp_path)
        _write_qa_report(tmp_path, non_bg=0, threshold=50)
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_ui_required_below_threshold_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=True)
        _write_screenshot(tmp_path)
        _write_qa_report(tmp_path, non_bg=10, threshold=50)
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_ui_required_above_threshold_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=True)
        _write_screenshot(tmp_path)
        _write_qa_report(tmp_path, non_bg=49796, threshold=50)
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is True

    def test_ui_required_missing_qa_report_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=True)
        _write_screenshot(tmp_path)
        # qa_report absent
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_ui_required_empty_screenshot_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, ui_required=True)
        _write_screenshot(tmp_path, size_bytes=0)
        _write_qa_report(tmp_path, non_bg=49796, threshold=50)
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False


# ---------------------------------------------------------------------------
# stack_contract.lifecycle_inits[] schema
# ---------------------------------------------------------------------------


def _base_contract() -> dict:
    return {
        "language": "python",
        "runtime": "cpython",
        "framework_backend": "pygame",
        "framework_frontend": "",
        "package_manager": "pip",
        "project_config_file": "pyproject.toml",
        "test_runner": "pytest",
        "static_analyzer": ["ruff"],
        "entry_point": "src/main.py",
        "run_command": "python src/main.py",
        "ui_required": True,
        "ui_kind": "pygame",
        "subsystems": [
            {
                "name": "ui",
                "src_dir": "src/ui",
                "components": [{"name": "menu_ui", "file": "src/ui/menu_ui.py"}],
            }
        ],
    }


@pytest.mark.parametrize(
    "event_loop_owner, expect_valid",
    [
        (None, True),  # null is explicit "framework owns dispatch"
        (
            {
                "attr": "menu",
                "handler_method": "handle_event",
                "class": "Menu",
                "module": "src/ui/menu_ui.py",
            },
            True,
        ),
        (
            {
                "attr": "menu",
                "handler_method": "handle_event",
                "class": "Menu",
                "module": "src/wrong/path.py",  # not in components[]
            },
            False,
        ),
        (
            {  # missing handler_method
                "attr": "menu",
                "class": "Menu",
                "module": "src/ui/menu_ui.py",
            },
            False,
        ),
        (True, False),  # wrong type
        ([], False),
    ],
)
def test_stack_contract_event_loop_owner_validation(tmp_path: Path, event_loop_owner, expect_valid: bool) -> None:
    from aise.safety_net.stack_contract import _stack_contract_valid

    contract = _base_contract()
    contract["event_loop_owner"] = event_loop_owner
    target = tmp_path / "stack_contract.json"
    target.write_text(json.dumps(contract))
    assert _stack_contract_valid(target) is expect_valid


@pytest.mark.parametrize(
    "lifecycle_inits, expect_valid",
    [
        # Absent — accepted (legacy contracts pre-skill).
        (None, True),
        # Empty list — explicit "no second-phase init needed".
        ([], True),
        # Well-formed entry referring to a real component file.
        (
            [
                {
                    "attr": "menu",
                    "method": "initialize",
                    "class": "MenuUI",
                    "module": "src/ui/menu_ui.py",
                }
            ],
            True,
        ),
        # Module path doesn't match any component file → reject.
        (
            [
                {
                    "attr": "menu",
                    "method": "initialize",
                    "class": "MenuUI",
                    "module": "src/ui/wrong_path.py",
                }
            ],
            False,
        ),
        # Missing required field → reject.
        (
            [{"attr": "menu", "method": "initialize", "class": "MenuUI"}],
            False,
        ),
        # Wrong type at top level → reject.
        ("not-a-list", False),
    ],
)
def test_stack_contract_lifecycle_inits_validation(tmp_path: Path, lifecycle_inits, expect_valid: bool) -> None:
    from aise.safety_net.stack_contract import _stack_contract_valid

    contract = _base_contract()
    if lifecycle_inits is not None:
        contract["lifecycle_inits"] = lifecycle_inits
    target = tmp_path / "stack_contract.json"
    target.write_text(json.dumps(contract))
    assert _stack_contract_valid(target) is expect_valid
