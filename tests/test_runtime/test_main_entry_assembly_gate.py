"""End-to-end regression for the main_entry assembly gate.

Replays the princess_tower TS run failure mode in miniature:

* architect produces stack_contract.json + data_dependency_contract.json
  + action_contract.json declaring assets/floor_*.json must be loaded
  by src/level/loader.py and that primary_attack must invoke
  combat.calculateBattle.
* developer (mocked) writes a "broken" main where neither the
  loader nor the attack handler does the required work.
* We invoke PhaseExecutor against the main_entry phase and assert
  the AUTO_GATE rejects (PhaseStatus.FAILED) with the right
  violations.

Then we replay with a "fixed" main and assert the gate passes.

The test exercises the production process.md (no inline phase spec)
so any drift between docs/process.md and the predicate registry
trips the test.
"""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.phase_executor import PhaseExecutor, PhaseStatus
from aise.runtime.waterfall_v2_loader import (
    default_waterfall_v2_path,
    load_waterfall_v2,
)

# -- Fixtures ------------------------------------------------------------


def _seed_contracts(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    stack = {
        "language": "typescript",
        "framework_backend": "phaser",
        "package_manager": "npm",
        "test_runner": "vitest",
        "entry_point": "src/main.ts",
        "run_command": "npx vite preview",
        "ui_required": True,
        "subsystems": [
            {
                "name": "level",
                "src_dir": "src/level",
                "components": [{"name": "loader", "file": "src/level/loader.ts"}],
            }
        ],
        "lifecycle_inits": [
            {
                "attr": "level",
                "method": "initialize",
                "class": "LevelLoader",
                "module": "src/level/loader.ts",
            }
        ],
    }
    (docs / "stack_contract.json").write_text(json.dumps(stack), encoding="utf-8")

    data_dep = {
        "version": "1",
        "data_dependencies": [
            {
                "name": "floor_data",
                "files_glob": "assets/floor_*.json",
                "consumer_module": "src/level/loader.ts",
                "min_files": 10,
            }
        ],
    }
    (docs / "data_dependency_contract.json").write_text(json.dumps(data_dep), encoding="utf-8")

    action = {
        "version": "1",
        "actions": [
            {
                "name": "primary_attack",
                "trigger": {"kind": "key", "value": "Space"},
                "expected_change": {
                    "kind": "state_field_changes",
                    "field": "currentScreen",
                },
                "handler_must_call": [
                    "combat.calculateBattle",
                    "player.applyBattleResult",
                ],
            }
        ],
    }
    (docs / "action_contract.json").write_text(json.dumps(action), encoding="utf-8")

    # 10 floor data files on disk.
    assets = tmp_path / "assets"
    assets.mkdir(exist_ok=True)
    for i in range(1, 11):
        (assets / f"floor_{i:02d}.json").write_text("{}", encoding="utf-8")


def _write_broken_main(tmp_path: Path) -> None:
    # Mirrors the princess_tower TS regression:
    # - main.ts has lifecycle init (level.initialize)
    # - but no reference to assets/floor_*.json (loader is a no-op)
    # - and onAttack just sets state, never calls combat methods
    src = tmp_path / "src"
    (src / "level").mkdir(parents=True, exist_ok=True)
    (src / "level" / "loader.ts").write_text(
        "// stub loader\nexport class LevelLoader { initialize() {} }\n",
        encoding="utf-8",
    )
    (src / "main.ts").write_text(
        """
import { LevelLoader } from './level/loader';
class Game {
  level = new LevelLoader();
  currentScreen = 'menu';
  boot() {
    this.level.initialize();
    onAttack(() => {
      this.currentScreen = 'battle';
    });
  }
}
new Game().boot();
""",
        encoding="utf-8",
    )
    # integration_report.json with verdict=fail to make AUTO_GATE
    # reject regardless (we want the static gates to be the actual
    # blocker, not the verdict field — the broken case must fail on
    # the predicates above).
    (tmp_path / "docs" / "integration_report.json").write_text(
        json.dumps(
            {
                "phase": "main_entry",
                "verdict": "pass",
                "data_wiring_check": [
                    {
                        "name": "floor_data",
                        "static_refs": 0,
                    }
                ],
                "action_wiring_check": [
                    {
                        "name": "primary_attack",
                        "handler_calls_found": 0,
                        "handler_calls_missing": [
                            "combat.calculateBattle",
                            "player.applyBattleResult",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_fixed_main(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "level").mkdir(parents=True, exist_ok=True)
    (src / "level" / "loader.ts").write_text(
        """
export class LevelLoader {
  levels: any[] = [];
  initialize() {
    for (let i = 1; i <= 10; i++) {
      // Source string contains 'assets/floor_' so the static gate detects
      // the dependency reference.
      const path = `assets/floor_${i.toString().padStart(2, '0')}.json`;
      this.levels.push({ path });
    }
  }
}
""",
        encoding="utf-8",
    )
    (src / "main.ts").write_text(
        """
import { LevelLoader } from './level/loader';
class Combat { calculateBattle(p, m) { return { won: true }; } }
class Player { applyBattleResult(r) {} }
class Game {
  level = new LevelLoader();
  combat = new Combat();
  player = new Player();
  currentScreen = 'menu';
  boot() {
    this.level.initialize();
    onAttack(() => {
      const result = this.combat.calculateBattle(null, null);
      this.player.applyBattleResult(result);
      this.currentScreen = 'battle';
    });
  }
}
new Game().boot();
""",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "integration_report.json").write_text(
        json.dumps(
            {
                "phase": "main_entry",
                "verdict": "pass",
                "data_wiring_check": [{"name": "floor_data", "static_refs": 1}],
                "action_wiring_check": [
                    {
                        "name": "primary_attack",
                        "handler_calls_found": 2,
                        "handler_calls_missing": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _make_executor(tmp_path: Path, produce_fn) -> PhaseExecutor:
    spec = load_waterfall_v2(default_waterfall_v2_path())
    return PhaseExecutor(
        spec=spec,
        project_root=tmp_path,
        produce_fn=produce_fn,
        dispatch_reviewer=lambda role, prompt: "PASS",
    )


# -- Tests ---------------------------------------------------------------


class TestRegression:
    def test_broken_main_entry_fails_auto_gate(self, tmp_path: Path):
        _seed_contracts(tmp_path)

        # produce_fn writes the broken main on every attempt.
        def produce(role, prompt, expected):
            _write_broken_main(tmp_path)
            return f"produced ({role})"

        executor = _make_executor(tmp_path, produce)
        spec = executor.spec
        main_entry = spec.phase_by_id("main_entry")
        assert main_entry is not None
        result = executor.execute_phase(main_entry, "Build the magic-tower TS game")
        assert result.status == PhaseStatus.FAILED
        # Producer was retried 3× (the AUTO_GATE retry budget).
        assert result.producer_attempts == 3
        # The summary names both regressions.
        summary = result.failure_summary
        assert "data_dependency_wiring_static" in summary or "floor_data" in summary
        assert "action_contract_wiring_static" in summary or "primary_attack" in summary

    def test_fixed_main_entry_passes(self, tmp_path: Path):
        _seed_contracts(tmp_path)

        def produce(role, prompt, expected):
            _write_fixed_main(tmp_path)
            return f"produced ({role})"

        executor = _make_executor(tmp_path, produce)
        spec = executor.spec
        main_entry = spec.phase_by_id("main_entry")
        assert main_entry is not None
        result = executor.execute_phase(main_entry, "Build the magic-tower TS game")
        # Reviewer mock always PASSes.
        assert result.status in (
            PhaseStatus.PASSED,
            PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW,
        ), result.failure_summary
        assert all(r.passed for r in result.deliverable_reports)

    def test_legacy_project_without_optional_contracts_passes(self, tmp_path: Path):
        # No data_dependency_contract.json + no action_contract.json on
        # disk — the new gates must vacuous-pass and the phase executes
        # the same way as before this commit.
        docs = tmp_path / "docs"
        docs.mkdir()
        stack = {
            "language": "python",
            "framework_backend": "none",
            "package_manager": "pip",
            "test_runner": "pytest",
            "entry_point": "src/main.py",
            "run_command": "python -m src.main",
            "ui_required": False,
            "subsystems": [
                {
                    "name": "core",
                    "src_dir": "src/core",
                    "components": [{"name": "x", "file": "src/core/x.py"}],
                }
            ],
            "lifecycle_inits": [],
        }
        (docs / "stack_contract.json").write_text(json.dumps(stack), encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")

        # Developer writes the integration_report.json verdict=skipped
        # (legacy projects with no contracts hit that path naturally).
        def produce(role, prompt, expected):
            (docs / "integration_report.json").write_text(
                json.dumps(
                    {
                        "phase": "main_entry",
                        "verdict": "skipped",
                        "boot_check": {
                            "ran": False,
                            "verdict": "skipped",
                            "reason": "no contracts to enforce",
                        },
                    }
                ),
                encoding="utf-8",
            )
            return "ok"

        executor = _make_executor(tmp_path, produce)
        main_entry = executor.spec.phase_by_id("main_entry")
        assert main_entry is not None
        result = executor.execute_phase(main_entry, "build a small python cli")
        assert result.status in (
            PhaseStatus.PASSED,
            PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW,
        ), result.failure_summary
