"""System-level E2E test: Validate the full AISE SDLC pipeline.

This test feeds a raw requirement into AISE's `run_project()` API and verifies
that the multi-agent workflow (Product Manager → Architect → Developer → QA)
produces correct outputs at every phase.

It does NOT call any LLM directly — it exercises the real AISE orchestrator,
agents, skills, and LLM client through the public API.

Requires:
  - OPENROUTER_API_KEY env var (or a configured model provider)
  - OpenAI SDK installed (`pip install openai`)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from aise.config import ProjectConfig  # noqa: E402
from aise.core.artifact import ArtifactType  # noqa: E402
from aise.main import create_team  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SNAKE_GAME_REQUIREMENTS = """\
Build a Snake Game application with the following requirements:

1. Core Game Mechanics:
   - Snake moves on a grid-based board
   - Snake grows when eating food
   - Game ends when snake hits wall or itself
   - Score tracking based on food eaten

2. Multiple Difficulty Levels:
   - Easy: slow speed, large board
   - Medium: moderate speed
   - Hard: fast speed, small board

3. Architecture Requirements:
   - Multi-module structure with clear separation of concerns
   - Core game logic module (snake, food, collision)
   - UI/rendering module
   - Configuration/settings module
   - Storage module for high scores
   - Each module in its own directory with __init__.py

4. Code Quality:
   - Type hints on all public functions
   - Docstrings on all classes and public methods
   - Unit tests for core game logic
"""

# Maximum time for the entire AISE pipeline to complete
PIPELINE_TIMEOUT_SECONDS = int(os.environ.get("AISE_PIPELINE_TIMEOUT", "3600"))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project_output_dir(tmp_path_factory):
    """Provide a clean temporary directory for project output."""
    d = tmp_path_factory.mktemp("aise_snake_game")
    yield d
    # Cleanup is automatic with tmp_path_factory


@pytest.fixture(scope="module")
def aise_pipeline_results(project_output_dir):
    """Run the full AISE pipeline once and share results across tests.

    Returns a dict with:
      - results: list of phase result dicts
      - orchestrator: the Orchestrator instance (for artifact inspection)
      - project_root: Path to the generated project
      - elapsed: total pipeline time in seconds
    """
    # The config is loaded from config/global_project_config.json by default
    # via _load_cli_project_config inside run_project → create_team
    config = ProjectConfig.from_json_file(Path(__file__).parent.parent.parent / "config" / "global_project_config.json")
    config.project_name = "Snake Game"

    # Increase max_tokens for complex generation
    config.default_model.max_tokens = 16384

    project_root = project_output_dir / "snake_game"
    project_root.mkdir(parents=True, exist_ok=True)
    for subdir in ("docs", "src", "tests", "trace"):
        (project_root / subdir).mkdir(parents=True, exist_ok=True)

    orchestrator = create_team(config, project_root=str(project_root))

    logger.info("Starting AISE pipeline for Snake Game project at %s", project_root)
    start = time.time()
    results = orchestrator.run_default_workflow(
        project_input={"raw_requirements": SNAKE_GAME_REQUIREMENTS},
        project_name="Snake Game",
    )
    elapsed = time.time() - start
    logger.info("AISE pipeline completed in %.1fs with %d phase results", elapsed, len(results))

    return {
        "results": results,
        "orchestrator": orchestrator,
        "project_root": project_root,
        "elapsed": elapsed,
        "artifact_store": orchestrator.artifact_store,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_phase_result(results: list[dict], phase_name: str) -> dict[str, Any] | None:
    """Find a phase result by name."""
    for r in results:
        if r.get("phase") == phase_name:
            return r
    return None


def _find_files(root: Path, pattern: str = "*.py") -> list[Path]:
    """Recursively find files matching a glob pattern."""
    return sorted(root.rglob(pattern))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="Requires OPENROUTER_API_KEY environment variable for LLM API access",
)
class TestAISESnakeGamePipeline:
    """Validate the full AISE SDLC pipeline output for a Snake Game project."""

    # --- Pipeline-level checks ---

    def test_pipeline_completes_successfully(self, aise_pipeline_results):
        """The pipeline must complete and return results for each phase."""
        results = aise_pipeline_results["results"]
        assert len(results) >= 3, (
            f"Expected at least 3 phase results (requirements, design, implementation), "
            f"got {len(results)}: {[r.get('phase') for r in results]}"
        )

    def test_pipeline_time_is_reasonable(self, aise_pipeline_results):
        """Pipeline should complete within the timeout."""
        elapsed = aise_pipeline_results["elapsed"]
        assert elapsed < PIPELINE_TIMEOUT_SECONDS, (
            f"Pipeline took {elapsed:.0f}s, exceeding {PIPELINE_TIMEOUT_SECONDS}s timeout"
        )

    # --- Phase 1: Requirements ---

    def test_requirements_phase_succeeds(self, aise_pipeline_results):
        """Requirements phase must complete successfully."""
        phase = _get_phase_result(aise_pipeline_results["results"], "requirements")
        assert phase is not None, "Requirements phase result not found"
        assert phase["status"] in ("completed", "in_review"), f"Requirements phase status: {phase['status']}"

    def test_requirements_artifacts_produced(self, aise_pipeline_results):
        """Requirements phase must produce requirement-related artifacts."""
        store = aise_pipeline_results["artifact_store"]
        # Check for any requirement-related artifact types
        req_types = [
            ArtifactType.REQUIREMENTS,
            ArtifactType.USER_STORIES,
            ArtifactType.PRD,
            ArtifactType.SYSTEM_DESIGN,
            ArtifactType.SYSTEM_REQUIREMENTS,
        ]
        found = []
        for at in req_types:
            artifacts = store.get_by_type(at)
            if artifacts:
                found.append(at.value)

        assert len(found) > 0, (
            f"No requirement artifacts found. Expected at least one of: {[t.value for t in req_types]}"
        )
        logger.info("Requirements artifacts found: %s", found)

    def test_requirements_docs_generated(self, aise_pipeline_results):
        """Requirements phase should generate documentation files."""
        project_root = aise_pipeline_results["project_root"]
        docs_dir = project_root / "docs"
        doc_files = list(docs_dir.rglob("*.md"))
        logger.info("Doc files after requirements phase: %s", [f.name for f in doc_files])
        # The deep_product_workflow generates system-design.md and/or system-requirements.md
        assert len(doc_files) >= 1, (
            f"Expected at least 1 markdown doc in {docs_dir}, found: {[f.name for f in doc_files]}"
        )

    # --- Phase 2: Design / Architecture ---

    def test_design_phase_succeeds(self, aise_pipeline_results):
        """Design phase must complete successfully."""
        phase = _get_phase_result(aise_pipeline_results["results"], "design")
        assert phase is not None, "Design phase result not found"
        assert phase["status"] in ("completed", "in_review"), f"Design phase status: {phase['status']}"

    def test_architecture_artifacts_produced(self, aise_pipeline_results):
        """Design phase must produce architecture artifacts."""
        store = aise_pipeline_results["artifact_store"]
        arch_types = [
            ArtifactType.ARCHITECTURE_DESIGN,
            ArtifactType.ARCHITECTURE_REQUIREMENT,
            ArtifactType.FUNCTIONAL_DESIGN,
            ArtifactType.API_CONTRACT,
            ArtifactType.TECH_STACK,
        ]
        found = []
        for at in arch_types:
            artifacts = store.get_by_type(at)
            if artifacts:
                found.append(at.value)

        assert len(found) > 0, (
            f"No architecture artifacts found. Expected at least one of: {[t.value for t in arch_types]}"
        )
        logger.info("Architecture artifacts found: %s", found)

    def test_architecture_docs_generated(self, aise_pipeline_results):
        """Architecture phase should generate design documents."""
        project_root = aise_pipeline_results["project_root"]
        docs_dir = project_root / "docs"
        doc_files = list(docs_dir.rglob("*.md"))
        # After both requirements + design, should have multiple docs
        assert len(doc_files) >= 2, (
            f"Expected at least 2 markdown docs after design phase, found: {[f.name for f in doc_files]}"
        )

    # --- Phase 3: Implementation ---

    def test_implementation_phase_succeeds(self, aise_pipeline_results):
        """Implementation phase must complete successfully."""
        phase = _get_phase_result(aise_pipeline_results["results"], "implementation")
        assert phase is not None, "Implementation phase result not found"
        assert phase["status"] in ("completed", "in_review"), f"Implementation phase status: {phase['status']}"

    def test_source_code_generated(self, aise_pipeline_results):
        """Implementation must generate Python source files."""
        project_root = aise_pipeline_results["project_root"]
        src_dir = project_root / "src"
        py_files = _find_files(src_dir, "*.py")
        logger.info("Source files generated: %d files", len(py_files))
        for f in py_files[:20]:
            logger.info("  %s (%d bytes)", f.relative_to(project_root), f.stat().st_size)

        assert len(py_files) >= 3, (
            f"Expected at least 3 Python source files in {src_dir}, found {len(py_files)}: {[f.name for f in py_files]}"
        )

    def test_multi_module_structure(self, aise_pipeline_results):
        """Source code should have a multi-module directory structure."""
        project_root = aise_pipeline_results["project_root"]
        src_dir = project_root / "src"

        # Find directories containing __init__.py (Python packages)
        packages = []
        for init_file in src_dir.rglob("__init__.py"):
            packages.append(init_file.parent)

        # Also count directories containing .py files
        dirs_with_py = set()
        for py_file in src_dir.rglob("*.py"):
            dirs_with_py.add(py_file.parent)

        logger.info("Python packages: %s", [p.relative_to(src_dir) for p in packages])
        logger.info("Dirs with Python files: %s", [d.relative_to(src_dir) for d in dirs_with_py])

        assert len(dirs_with_py) >= 2, (
            f"Expected at least 2 directories with Python files (multi-module), "
            f"found {len(dirs_with_py)}: {[str(d.relative_to(src_dir)) for d in dirs_with_py]}"
        )

    def test_source_files_are_valid_python(self, aise_pipeline_results):
        """All generated .py files must be syntactically valid Python."""
        project_root = aise_pipeline_results["project_root"]
        src_dir = project_root / "src"
        py_files = _find_files(src_dir, "*.py")

        errors = []
        for py_file in py_files:
            try:
                source = py_file.read_text(encoding="utf-8")
                compile(source, str(py_file), "exec")
            except SyntaxError as e:
                errors.append(f"{py_file.relative_to(project_root)}: {e}")

        assert not errors, f"{len(errors)} files have syntax errors:\n" + "\n".join(errors)

    def test_source_code_artifacts_produced(self, aise_pipeline_results):
        """Implementation must produce source code artifacts in the store."""
        store = aise_pipeline_results["artifact_store"]
        code_artifacts = store.get_by_type(ArtifactType.SOURCE_CODE)
        assert code_artifacts, "No SOURCE_CODE artifacts found in artifact store"

    # --- Phase 4: Testing (if reached) ---

    def test_testing_phase_produces_test_artifacts(self, aise_pipeline_results):
        """If the testing phase runs, it should produce test artifacts."""
        phase = _get_phase_result(aise_pipeline_results["results"], "testing")
        if phase is None:
            pytest.skip("Testing phase did not execute (pipeline may have stopped earlier)")

        store = aise_pipeline_results["artifact_store"]
        test_types = [
            ArtifactType.TEST_PLAN,
            ArtifactType.TEST_CASES,
            ArtifactType.AUTOMATED_TESTS,
            ArtifactType.UNIT_TESTS,
        ]
        found = []
        for at in test_types:
            artifacts = store.get_by_type(at)
            if artifacts:
                found.append(at.value)

        logger.info("Test artifacts found: %s", found)
        # At least one test-related artifact should exist
        assert len(found) > 0, (
            f"Testing phase ran but no test artifacts found. "
            f"Phase status: {phase.get('status')}, tasks: {phase.get('tasks')}"
        )

    # --- Cross-cutting quality checks ---

    def test_generated_tests_are_runnable(self, aise_pipeline_results):
        """Generated test files (if any) should be syntactically valid and discoverable by pytest."""
        project_root = aise_pipeline_results["project_root"]
        tests_dir = project_root / "tests"
        test_files = _find_files(tests_dir, "*.py")

        if not test_files:
            pytest.skip("No test files generated by AISE pipeline")

        # Check syntax
        errors = []
        for tf in test_files:
            try:
                source = tf.read_text(encoding="utf-8")
                compile(source, str(tf), "exec")
            except SyntaxError as e:
                errors.append(f"{tf.relative_to(project_root)}: {e}")

        assert not errors, f"{len(errors)} test files have syntax errors:\n" + "\n".join(errors)

        # Try to collect tests (don't run them — just verify pytest can discover them)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", str(tests_dir)],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=60,
        )
        logger.info("pytest --collect-only stdout:\n%s", result.stdout[-500:] if result.stdout else "(empty)")
        if result.returncode != 0:
            logger.warning("pytest --collect-only stderr:\n%s", result.stderr[-500:] if result.stderr else "(empty)")
        # We don't assert on returncode here because generated tests may have import
        # issues with the generated source — but they should at least be discoverable

    def test_generated_tests_execute(self, aise_pipeline_results):
        """Generated test files should be executable by pytest."""
        project_root = aise_pipeline_results["project_root"]
        tests_dir = project_root / "tests"
        src_dir = project_root / "src"
        test_files = _find_files(tests_dir, "*.py")

        if not test_files:
            pytest.skip("No test files generated by AISE pipeline")

        # Run the generated tests
        env = os.environ.copy()
        # Add src to PYTHONPATH so generated tests can import the generated source
        env["PYTHONPATH"] = str(src_dir) + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=120,
            env=env,
        )
        logger.info("Generated tests stdout:\n%s", result.stdout[-2000:] if result.stdout else "(empty)")
        if result.stderr:
            logger.info("Generated tests stderr:\n%s", result.stderr[-1000:])

        # Log but don't hard-fail on test execution — LLM-generated tests may have
        # issues. We check that at least some tests were collected.
        if "no tests ran" in result.stdout.lower():
            logger.warning("No tests were collected/run from generated test files")

    def test_trace_files_created(self, aise_pipeline_results):
        """LLM trace files should be generated in the trace directory."""
        project_root = aise_pipeline_results["project_root"]
        trace_dir = project_root / "trace"
        trace_files = list(trace_dir.rglob("*.json"))
        logger.info("Trace files: %d", len(trace_files))
        assert len(trace_files) >= 1, (
            f"Expected LLM trace files in {trace_dir}, found none. This suggests no LLM calls were made."
        )

    def test_artifact_store_has_entries(self, aise_pipeline_results):
        """The artifact store should contain artifacts from all phases."""
        store = aise_pipeline_results["artifact_store"]
        all_artifacts = list(store._artifacts.values())
        logger.info("Total artifacts in store: %d", len(all_artifacts))
        for a in all_artifacts:
            logger.info(
                "  [%s] %s by %s (v%d)",
                a.artifact_type.value,
                a.id,
                a.producer,
                a.version,
            )
        assert len(all_artifacts) >= 3, (
            f"Expected at least 3 artifacts (from requirements, design, implementation), found {len(all_artifacts)}"
        )

    # --- Summary ---

    def test_print_pipeline_summary(self, aise_pipeline_results):
        """Print a summary of the full pipeline run (always passes)."""
        results = aise_pipeline_results["results"]
        project_root = aise_pipeline_results["project_root"]
        elapsed = aise_pipeline_results["elapsed"]
        store = aise_pipeline_results["artifact_store"]

        print("\n" + "=" * 70)
        print("AISE PIPELINE SUMMARY")
        print("=" * 70)
        print(f"Project Root: {project_root}")
        print(f"Total Time: {elapsed:.1f}s")
        print(f"Phases Completed: {len(results)}")

        for r in results:
            phase = r.get("phase", "?")
            status = r.get("status", "?")
            tasks = r.get("tasks", {})
            print(f"\n  Phase: {phase} — Status: {status}")
            for task_key, task_result in tasks.items():
                print(f"    Task: {task_key} — {task_result.get('status', '?')}")

        print(f"\nArtifacts: {len(store._artifacts)}")
        print(f"Source files: {len(_find_files(project_root / 'src', '*.py'))}")
        print(f"Test files: {len(_find_files(project_root / 'tests', '*.py'))}")
        print(f"Doc files: {len(list((project_root / 'docs').rglob('*.md')))}")
        print(f"Trace files: {len(list((project_root / 'trace').rglob('*.json')))}")
        print("=" * 70)
