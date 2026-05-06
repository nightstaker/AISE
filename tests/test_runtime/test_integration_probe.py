"""Tests for ``integration_probe.run_probe`` end-to-end.

Covers:
- Static analysis branch with passing data + action contracts
- Static analysis branch with failing wiring
- web profile → boot=skipped (no headless browser)
- cli profile → real subprocess call (uses /bin/echo with run_command)
- unknown profile → boot=skipped with reason
- to_integration_report shape validates against the schema
- main() CLI hook returns exit 1 on verdict=fail
"""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.integration_probe import (
    main,
    run_probe,
)
from aise.runtime.predicates import PredicateContext, evaluate_predicate
from aise.runtime.waterfall_v2_models import AcceptancePredicate

# -- Static-side checks ---------------------------------------------------


class TestStaticChecks:
    def test_pass_when_wired(self, tmp_path: Path):
        # Source references the data files; entry_point calls handler symbols.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text(
            """
def boot():
    levels = open('assets/level_01.json').read()
    on_attack()

def on_attack():
    combat_calculate_battle()
""",
            encoding="utf-8",
        )
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "level_01.json").write_text("{}", encoding="utf-8")

        sc = {"entry_point": "src/main.py", "language": "python"}
        dd = {
            "data_dependencies": [
                {
                    "name": "level_data",
                    "files_glob": "assets/level_*.json",
                    "consumer_module": "src/main.py",
                }
            ]
        }
        ac = {
            "actions": [
                {
                    "name": "primary_attack",
                    "trigger": {"kind": "key"},
                    "expected_change": {"kind": "any_observable_change"},
                    "handler_must_call": ["combat_calculate_battle"],
                }
            ]
        }
        result = run_probe(
            tmp_path,
            stack_contract=sc,
            data_dependency_contract=dd,
            action_contract=ac,
            enable_boot=False,
        )
        assert result.verdict == "pass", result.violations
        assert result.violations == []
        assert result.data_wiring[0].static_refs >= 1
        assert result.action_wiring[0].handler_calls_found == 1
        assert result.action_wiring[0].handler_calls_missing == []

    def test_fail_collects_violations(self, tmp_path: Path):
        # Source references nothing — both contracts trip violations.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def boot(): pass\n", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "level_01.json").write_text("{}", encoding="utf-8")

        sc = {"entry_point": "src/main.py", "language": "python"}
        dd = {
            "data_dependencies": [
                {
                    "name": "level_data",
                    "files_glob": "assets/level_*.json",
                    "consumer_module": "src/main.py",
                }
            ]
        }
        ac = {
            "actions": [
                {
                    "name": "primary_attack",
                    "trigger": {"kind": "key"},
                    "expected_change": {"kind": "any_observable_change"},
                    "handler_must_call": ["combat_calculate_battle"],
                }
            ]
        }
        result = run_probe(
            tmp_path,
            stack_contract=sc,
            data_dependency_contract=dd,
            action_contract=ac,
            enable_boot=False,
        )
        assert result.verdict == "fail"
        assert any("data_wiring.level_data" in v for v in result.violations)
        assert any("action_wiring.primary_attack" in v for v in result.violations)


# -- Boot-side branches --------------------------------------------------


class TestBootBranches:
    def test_web_profile_skipped(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        (tmp_path / "vite.config.ts").write_text("\n", encoding="utf-8")
        sc = {"language": "typescript", "entry_point": "src/index.ts"}
        result = run_probe(
            tmp_path,
            stack_contract=sc,
            enable_boot=True,
        )
        # Web profile auto-detected; boot returns skipped.
        assert result.profile == "web_typescript"
        assert result.runtime_kind == "web"
        assert result.boot.verdict == "skipped"
        assert "headless browser" in result.boot.reason

    def test_unknown_profile_skipped(self, tmp_path: Path):
        result = run_probe(tmp_path, stack_contract=None, enable_boot=True)
        assert result.profile == "unknown"
        assert result.boot.verdict == "skipped"

    def test_disabled_boot(self, tmp_path: Path):
        # enable_boot=False short-circuits regardless of profile.
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        sc = {"language": "typescript"}
        result = run_probe(tmp_path, stack_contract=sc, enable_boot=False)
        assert result.boot.verdict == "skipped"
        assert "disabled by caller" in result.boot.reason

    def test_cli_profile_runs_subprocess(self, tmp_path: Path):
        # Use ``echo`` as the run_command — exits 0, prints something.
        # This is the actual cli boot harness path, exercised end-to-end.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
        sc = {
            "language": "python",
            "entry_point": "src/main.py",
            "run_command": "echo HELLO_WORLD",
            "profile": "cli",  # explicit override to avoid web detection
        }
        result = run_probe(tmp_path, stack_contract=sc, enable_boot=True)
        assert result.profile == "cli"
        # Should pass — echo exits 0 with non-empty stdout.
        assert result.boot.verdict == "pass", result.boot.reason
        assert result.boot.exit_code == 0

    def test_cli_profile_failed_command(self, tmp_path: Path):
        # ``false`` exits 1 — boot verdict must be fail.
        sc = {
            "language": "python",
            "entry_point": "src/main.py",
            "run_command": "false",
            "profile": "cli",
        }
        result = run_probe(tmp_path, stack_contract=sc, enable_boot=True)
        assert result.profile == "cli"
        assert result.boot.verdict == "fail"
        assert result.boot.exit_code == 1


# -- Report shape (validates against schema) ------------------------------


class TestReportShape:
    def test_to_integration_report_matches_schema(self, tmp_path: Path):
        result = run_probe(tmp_path, stack_contract=None, enable_boot=False)
        report = result.to_integration_report()
        out = tmp_path / "integration_report.json"
        out.write_text(json.dumps(report), encoding="utf-8")
        ctx = PredicateContext(project_root=tmp_path, deliverable_path=out)
        r = evaluate_predicate(
            AcceptancePredicate("schema", "schemas/integration_report.schema.json"),
            ctx,
        )
        assert r.passed, r.detail


# -- CLI hook ------------------------------------------------------------


class TestCliHook:
    def test_main_writes_report_and_exits_zero_on_pass(self, tmp_path: Path, capsys):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps({"language": "python", "entry_point": "src/main.py"}),
            encoding="utf-8",
        )
        rc = main([str(tmp_path), "--no-boot"])
        # Captured stdout should be valid JSON
        out = capsys.readouterr().out
        report = json.loads(out)
        assert report["phase"] == "main_entry"
        # No contracts → verdict=skipped (still rc=0).
        assert report["verdict"] == "skipped"
        assert rc == 0
        # File on disk too.
        on_disk = (tmp_path / "docs" / "integration_report.json").read_text("utf-8")
        assert json.loads(on_disk)["phase"] == "main_entry"

    def test_main_exits_one_on_fail(self, tmp_path: Path, capsys):
        # Construct a project where action wiring fails → verdict=fail
        # → main() returns 1.
        (tmp_path / "docs").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# nothing wired\n", encoding="utf-8")
        (tmp_path / "docs" / "stack_contract.json").write_text(
            json.dumps({"language": "python", "entry_point": "src/main.py"}),
            encoding="utf-8",
        )
        (tmp_path / "docs" / "action_contract.json").write_text(
            json.dumps(
                {
                    "actions": [
                        {
                            "name": "primary",
                            "trigger": {"kind": "key"},
                            "expected_change": {"kind": "any_observable_change"},
                            "handler_must_call": ["do_thing"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        rc = main([str(tmp_path), "--no-boot"])
        capsys.readouterr()
        assert rc == 1

    def test_main_rejects_missing_arg(self, capsys):
        rc = main([])
        assert rc == 2
        err = capsys.readouterr().err
        assert "usage" in err

    def test_main_rejects_non_directory(self, tmp_path: Path):
        # Pointing at a file should fail fast.
        f = tmp_path / "not-a-dir"
        f.write_text("", encoding="utf-8")
        rc = main([str(f), "--no-boot"])
        assert rc == 2
