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
    _flutter_entry_shape_problems,
    _is_flutter_contract,
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


def _write_flutter_contract(root: Path) -> None:
    """Minimal contract used by the runtime-skip tests below: declares
    Flutter as the UI kind so ``_required_ui_runtime`` returns
    ``"flutter"`` and the ``shutil.which`` gate engages.
    """
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "stack_contract.json").write_text(
        json.dumps({"ui_required": True, "framework_frontend": "flutter", "ui_kind": "flutter"})
    )


class TestUISmokeRuntimeSkip:
    """Fix 5 (project_0-tower 2026-04-29): when the project's UI
    runtime binary is not installed on this host, ``ui_smoke_frame``
    must NOT loop ``llm_fallback_triggered`` indefinitely — emit a
    distinct ``ui_smoke_unavailable`` event and accept the artifact.
    Operators who want strict enforcement set
    ``AISE_UI_SMOKE_REQUIRE_RUNNER=1``.
    """

    artifact = ExpectedArtifact(
        path="artifacts/smoke_frame_0.png",
        kind="ui_smoke_frame",
        non_empty=True,
    )

    def test_flutter_missing_runtime_skips_and_emits_event(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from aise.safety_net import ui_smoke as ui_smoke_module

        monkeypatch.setattr(ui_smoke_module.shutil, "which", lambda _bin: None)
        monkeypatch.delenv("AISE_UI_SMOKE_REQUIRE_RUNNER", raising=False)
        _write_flutter_contract(tmp_path)
        # Frame absent, no qa_report — under the legacy behaviour this
        # would be a layer-B miss. With the skip it's accepted instead.
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is True
        events_path = tmp_path / "trace" / "safety_net_events.jsonl"
        assert events_path.is_file()
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        assert any(e.get("event_type") == "ui_smoke_unavailable" for e in events)
        # And critically: no ``llm_fallback_triggered`` was emitted.
        assert not any(e.get("event_type") == "llm_fallback_triggered" for e in events)

    def test_flutter_present_runtime_keeps_legacy_miss(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from aise.safety_net import ui_smoke as ui_smoke_module

        monkeypatch.setattr(
            ui_smoke_module.shutil,
            "which",
            lambda b: "/usr/bin/" + b,
        )
        _write_flutter_contract(tmp_path)
        # Frame absent — runtime IS available, so the skip must not
        # engage and the legacy "missing screenshot" miss remains.
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_skip_disabled_by_env_keeps_legacy_miss(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from aise.safety_net import ui_smoke as ui_smoke_module

        monkeypatch.setattr(ui_smoke_module.shutil, "which", lambda _bin: None)
        monkeypatch.setenv("AISE_UI_SMOKE_REQUIRE_RUNNER", "1")
        _write_flutter_contract(tmp_path)
        # Operator opted out of skip → fall through to legacy miss.
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_pygame_no_external_runtime_keeps_legacy_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stacks whose runtime is the system Python (pygame, tk,
        etc.) have no external binary mapped, so the skip must NOT
        engage even when ``shutil.which`` returns None — the existing
        layer-B check is still the only behaviour for those."""
        from aise.safety_net import ui_smoke as ui_smoke_module

        monkeypatch.setattr(ui_smoke_module.shutil, "which", lambda _bin: None)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps({"ui_required": True, "framework_frontend": "pygame", "ui_kind": "pygame"})
        )
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is False

    def test_frame_present_with_missing_runtime_uses_legacy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The skip is gated on ``not target.is_file()`` — once a frame
        does exist the legacy path runs (qa_report check, threshold,
        etc.). This protects against a future where someone manages to
        capture a frame on a host without the runtime via some other
        mechanism: the metric checks must still apply.
        """
        from aise.safety_net import ui_smoke as ui_smoke_module

        monkeypatch.setattr(ui_smoke_module.shutil, "which", lambda _bin: None)
        _write_flutter_contract(tmp_path)
        _write_screenshot(tmp_path)
        _write_qa_report(tmp_path, non_bg=49796, threshold=50)
        assert _kind_ui_smoke_frame(tmp_path, self.artifact) is True


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
        # Frameworks that own dispatch from the entry file (Flutter
        # ``runApp``, FastAPI ``app``, pygame ``main`` loop) place
        # the event_loop_owner in ``main.py`` / ``main.dart`` itself.
        # That file is the contract's ``entry_point`` and is by
        # definition not a subsystem component — accept it.
        (
            {
                "attr": "gameEngine",
                "handler_method": "handle_event",
                "class": "GameEngine",
                "module": "src/main.py",  # contract.entry_point
            },
            True,
        ),
        (
            {
                "attr": "menu",
                "handler_method": "handle_event",
                "class": "Menu",
                "module": "src/wrong/path.py",  # neither component nor entry_point
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


# ---------------------------------------------------------------------------
# Framework-mandated source-root validation (Fix 1, project_0-tower 2026-04-29)
# ---------------------------------------------------------------------------


def _flutter_contract() -> dict:
    """Minimal valid Flutter contract used by the framework-root tests
    below. ``src_dir`` / ``components[].file`` / ``entry_point`` /
    ``lifecycle_inits[].module`` all live under ``lib/`` — i.e. the
    "happy path" baseline. Each test mutates one field to verify the
    new validator rejects mismatches.
    """
    return {
        "language": "dart",
        "runtime": "flutter",
        "framework_backend": "",
        "framework_frontend": "flutter",
        "package_manager": "pub",
        "project_config_file": "pubspec.yaml",
        "test_runner": "flutter test",
        "static_analyzer": ["dart analyze"],
        "entry_point": "lib/main.dart",
        "run_command": "flutter run",
        "ui_required": True,
        "ui_kind": "flutter",
        "subsystems": [
            {
                "name": "ui",
                "src_dir": "lib/ui",
                "components": [{"name": "menu_ui", "file": "lib/ui/menu_ui.dart"}],
            }
        ],
        "lifecycle_inits": [
            {
                "attr": "menu",
                "method": "initialize",
                "class": "MenuUI",
                "module": "lib/ui/menu_ui.dart",
            }
        ],
    }


class TestStackContractFrameworkRoot:
    """The Flutter / Dart-pub toolchain only resolves ``package:``
    imports under ``lib/``. The 2026-04-29 ``project_0-tower`` re-run
    shipped a Flutter contract whose ``src_dir`` was ``src/ui`` while
    the developer toolchain was forced to ``lib/`` — three parallel
    source trees ensued. The validator now rejects such mismatches so
    the architect re-dispatches with concrete corrective guidance.
    """

    def test_flutter_contract_with_lib_passes(self, tmp_path: Path) -> None:
        from aise.safety_net.stack_contract import _stack_contract_valid

        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(_flutter_contract()))
        assert _stack_contract_valid(target) is True

    def test_flutter_contract_with_src_dir_under_src_fails(self, tmp_path: Path) -> None:
        from aise.safety_net.stack_contract import _stack_contract_valid

        contract = _flutter_contract()
        contract["subsystems"][0]["src_dir"] = "src/ui"
        contract["subsystems"][0]["components"][0]["file"] = "src/ui/menu_ui.dart"
        contract["lifecycle_inits"][0]["module"] = "src/ui/menu_ui.dart"
        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(contract))
        assert _stack_contract_valid(target) is False

    def test_flutter_entry_point_under_src_fails(self, tmp_path: Path) -> None:
        from aise.safety_net.stack_contract import _stack_contract_valid

        contract = _flutter_contract()
        contract["entry_point"] = "src/main.dart"
        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(contract))
        assert _stack_contract_valid(target) is False

    def test_flutter_lifecycle_module_under_src_fails(self, tmp_path: Path) -> None:
        from aise.safety_net.stack_contract import _stack_contract_valid

        contract = _flutter_contract()
        contract["lifecycle_inits"][0]["module"] = "src/ui/menu_ui.dart"
        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(contract))
        assert _stack_contract_valid(target) is False

    def test_flutter_event_loop_owner_module_under_src_fails(self, tmp_path: Path) -> None:
        from aise.safety_net.stack_contract import _stack_contract_valid

        contract = _flutter_contract()
        contract["event_loop_owner"] = {
            "attr": "menu",
            "handler_method": "handleEvent",
            "class": "MenuUI",
            "module": "src/ui/menu_ui.dart",
        }
        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(contract))
        assert _stack_contract_valid(target) is False

    def test_python_pygame_contract_keeps_src_layout(self, tmp_path: Path) -> None:
        """Stacks without a mandated source root accept the conventional
        ``src/`` layout — the new check must not regress non-Flutter
        projects."""
        from aise.safety_net.stack_contract import _stack_contract_valid

        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(_base_contract()))
        assert _stack_contract_valid(target) is True

    def test_dart_language_alone_triggers_lib_requirement(self, tmp_path: Path) -> None:
        """``language=dart`` without an explicit framework_frontend
        still mandates ``lib/`` because Dart's ``package:`` resolver
        is the same regardless of whether the project is Flutter."""
        from aise.safety_net.stack_contract import _stack_contract_valid

        contract = _flutter_contract()
        contract["framework_frontend"] = ""
        contract["ui_kind"] = ""
        contract["ui_required"] = False
        # Subsystem still under ``src/`` — should still be rejected
        # because language=dart maps to lib/.
        contract["subsystems"][0]["src_dir"] = "src/ui"
        contract["subsystems"][0]["components"][0]["file"] = "src/ui/menu_ui.dart"
        contract["entry_point"] = "src/main.dart"
        contract["lifecycle_inits"][0]["module"] = "src/ui/menu_ui.dart"
        target = tmp_path / "stack_contract.json"
        target.write_text(json.dumps(contract))
        assert _stack_contract_valid(target) is False


# ---------------------------------------------------------------------------
# Flutter entry-shape check (Fix 2, project_0-tower 2026-04-29)
# ---------------------------------------------------------------------------


class TestFlutterEntryShape:
    """Flutter ``lib/main.dart`` MUST hand control to the runtime via
    ``runApp(...)``. The 2026-04-29 ``project_0-tower`` re-run shipped
    a CLI loop in ``lib/main.dart`` — every lifecycle method was
    invoked by name (so the existing AST check passed), but the file
    imported ``dart:io`` and read ``stdin`` byte-by-byte, so the
    Flutter framework never booted. This check rejects that shape.
    """

    def test_is_flutter_contract_matches_framework_frontend(self) -> None:
        assert _is_flutter_contract({"framework_frontend": "flutter"}) is True

    def test_is_flutter_contract_matches_ui_kind(self) -> None:
        assert _is_flutter_contract({"ui_kind": "Flutter"}) is True

    def test_is_flutter_contract_rejects_dart_only(self) -> None:
        # Dart CLI projects are not Flutter; the entry-shape check
        # would mis-fire on a legitimate ``dart run`` CLI binary.
        assert _is_flutter_contract({"language": "dart"}) is False

    def test_runapp_call_satisfies_shape(self) -> None:
        src = """
import 'package:flutter/material.dart';
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SnakeApp());
}
"""
        assert _flutter_entry_shape_problems(src) == []

    def test_missing_runapp_is_rejected(self) -> None:
        src = """
import 'package:flutter/material.dart';
void main() {
  // Built widgets but never handed control to the framework.
  final root = MaterialApp(home: Container());
}
"""
        problems = _flutter_entry_shape_problems(src)
        assert problems
        assert any("runApp" in p for p in problems)

    def test_dart_io_import_with_runapp_is_still_rejected(self) -> None:
        # Even when ``runApp`` is somewhere in the file, ``dart:io``
        # signals a CLI loop pattern; reject so the developer rewrites
        # the entry as a Flutter widget tree.
        src = """
import 'dart:io';
import 'package:flutter/material.dart';
void main() {
  runApp(const SnakeApp());
  while (true) {
    final byte = stdin.readByteSync();
    if (byte == -1) break;
  }
}
"""
        problems = _flutter_entry_shape_problems(src)
        assert any("dart:io" in p for p in problems)

    def test_cli_loop_without_runapp_is_rejected_with_both_problems(self) -> None:
        # The 2026-04-29 project_0-tower shape: dart:io CLI loop, no
        # runApp anywhere. We expect BOTH problems reported so the
        # developer fix is unambiguous.
        src = """
import 'dart:io';
void main() {
  while (true) {
    stdout.write('> ');
    final byte = stdin.readByteSync();
    if (byte == -1) break;
  }
}
"""
        problems = _flutter_entry_shape_problems(src)
        assert any("runApp" in p for p in problems)
        assert any("dart:io" in p for p in problems)

    def test_entry_point_valid_rejects_flutter_cli_loop(self, tmp_path: Path) -> None:
        """End-to-end: contract names Flutter, entry file is a CLI
        loop — ``_entry_point_valid`` returns False and the missing
        list contains both shape problems."""
        contract = _flutter_contract()
        # Add a single lifecycle init the entry happens to call by name
        # so the existing method-presence check would pass alone.
        contract["lifecycle_inits"] = [
            {"attr": "menu", "method": "initialize", "class": "MenuUI", "module": "lib/ui/menu_ui.dart"}
        ]
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps(contract))
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "main.dart").write_text(
            "import 'dart:io';\nvoid main() {\n  menu.initialize();\n  while (true) { stdin.readByteSync(); }\n}\n"
        )
        ok, missing = _entry_point_valid(tmp_path)
        assert ok is False
        assert any("runApp" in m for m in missing)
        assert any("dart:io" in m for m in missing)

    def test_entry_point_valid_accepts_proper_flutter_main(self, tmp_path: Path) -> None:
        contract = _flutter_contract()
        contract["lifecycle_inits"] = [
            {"attr": "menu", "method": "initialize", "class": "MenuUI", "module": "lib/ui/menu_ui.dart"}
        ]
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps(contract))
        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "main.dart").write_text(
            "import 'package:flutter/material.dart';\n"
            "void main() {\n"
            "  WidgetsFlutterBinding.ensureInitialized();\n"
            "  menu.initialize();\n"
            "  runApp(const SnakeApp());\n"
            "}\n"
        )
        ok, _missing = _entry_point_valid(tmp_path)
        assert ok is True

    def test_entry_point_valid_skips_shape_check_for_python_pygame(self, tmp_path: Path) -> None:
        """Non-Flutter projects must not get tripped by the new check.
        A pygame project's ``src/main.py`` legitimately imports nothing
        Flutter-related and has no ``runApp`` — the existing lifecycle
        AST check is the only one that should run."""
        contract = _base_contract()
        contract["lifecycle_inits"] = [
            {"attr": "menu", "method": "initialize", "class": "MenuUI", "module": "src/ui/menu_ui.py"}
        ]
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps(contract))
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text(
            "class App:\n    def __init__(self):\n        self.menu = MenuUI()\n        self.menu.initialize()\n"
        )
        ok, _missing = _entry_point_valid(tmp_path)
        assert ok is True
