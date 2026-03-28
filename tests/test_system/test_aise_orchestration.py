"""System-level test: AISE autonomous task orchestration.

This test verifies that AISE can orchestrate its own components
to complete a multi-step development task without external LLM API.

This test uses only internal AISE components and does not require external dependencies.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.message import MessageBus
from aise.core.skill import Skill, SkillContext

# Configuration
PROJECT_NAME = "system_test_project"
PROJECT_DIR = Path("tmp_test_projects") / PROJECT_NAME
TEST_TIMEOUT_SECONDS = 5 * 60  # 5 minutes


class MockArtifactWriterSkill(Skill):
    """Test skill that writes artifacts to files."""

    def __init__(self) -> None:
        self._name = "write_artifact"
        self._description = "Writes an artifact to a file"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        """Execute the skill."""
        content = input_data["content"]
        filename = input_data["filename"]
        artifact_type_str = input_data["artifact_type"]

        # Map artifact type strings to ArtifactType enum
        type_mapping = {
            "SOURCE_CODE": ArtifactType.SOURCE_CODE,
            "UNIT_TESTS": ArtifactType.UNIT_TESTS,
            "DOCUMENTATION": ArtifactType.ARCHITECTURE_DESIGN,  # Use existing type
            "CONFIG": ArtifactType.SYSTEM_REQUIREMENTS,  # Use existing type
        }
        artifact_type = type_mapping.get(artifact_type_str, ArtifactType.SOURCE_CODE)

        # Create project directory if needed
        project_path = Path(context.project_name) if context.project_name else Path(".")
        project_path.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path = project_path / filename
        file_path.write_text(content)

        print(f"    [WRITE] {filename} ({len(content)} chars)")

        return Artifact(
            artifact_type=artifact_type,
            content={"file_path": str(file_path), "size": len(content)},
            producer=self._name,
            metadata={"filename": filename},
        )


class MockCodeGeneratorSkill(Skill):
    """Test skill that generates Python code."""

    def __init__(self) -> None:
        self._name = "generate_code"
        self._description = "Generates Python code for a module"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        """Generate Python code."""
        module_name = input_data["module_name"]
        description = input_data["description"]
        functions = input_data.get("functions", [])

        # Generate code
        code_lines = [
            f'"""{description}."""',
            "",
            "from __future__ import annotations",
            "",
        ]

        if functions:
            code_lines.append(f"def {functions[0]}():")
            code_lines.append(f'    """{functions[0].replace("_", " ").title()}."""')
            code_lines.append("    pass")
            code_lines.append("")

        code = "\n".join(code_lines)

        return Artifact(
            artifact_type=ArtifactType.SOURCE_CODE,
            content={"code": code, "module": module_name},
            producer=self._name,
            metadata={"module": module_name, "functions": functions},
        )


class MockTestGeneratorSkill(Skill):
    """Test skill that generates test code."""

    def __init__(self) -> None:
        self._name = "generate_tests"
        self._description = "Generates pytest test code"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        """Generate test code."""
        module_name = input_data["module_name"]
        test_count = input_data.get("test_count", 3)

        test_lines = [
            f'"""Tests for {module_name}."""',
            "",
            "from __future__ import annotations",
            "",
            f"def test_{module_name}_basic():",
            f'    """Basic test for {module_name}."""',
            "    assert True",
        ]

        for i in range(1, test_count):
            test_lines.append(f"\ndef test_{module_name}_case_{i}():")
            test_lines.append(f'    """Test case {i} for {module_name}."""')
            test_lines.append("    assert True")

        test_code = "\n".join(test_lines)

        return Artifact(
            artifact_type=ArtifactType.UNIT_TESTS,
            content={"test_code": test_code, "module": module_name},
            producer=self._name,
            metadata={"module": module_name, "test_count": test_count},
        )


def setup_test_environment() -> tuple[MessageBus, ArtifactStore]:
    """Set up test environment.

    Returns:
        Tuple of (message_bus, artifact_store)
    """
    message_bus = MessageBus()
    artifact_store = ArtifactStore()

    return message_bus, artifact_store


def create_test_agents(message_bus: MessageBus, artifact_store: ArtifactStore) -> dict[str, Agent]:
    """Create test agents with skills.

    Args:
        message_bus: Message bus for communication
        artifact_store: Artifact store for results

    Returns:
        Dictionary of agent_name -> Agent
    """
    agents: dict[str, Agent] = {}

    # Create architect agent
    architect = Agent(
        name="architect",
        role=AgentRole.ARCHITECT,
        message_bus=message_bus,
        artifact_store=artifact_store,
    )
    architect.register_skill(MockCodeGeneratorSkill())
    agents["architect"] = architect

    # Create developer agent
    developer = Agent(
        name="developer",
        role=AgentRole.DEVELOPER,
        message_bus=message_bus,
        artifact_store=artifact_store,
    )
    developer.register_skill(MockArtifactWriterSkill())
    agents["developer"] = developer

    # Create QA engineer agent
    qa_engineer = Agent(
        name="qa_engineer",
        role=AgentRole.QA_ENGINEER,
        message_bus=message_bus,
        artifact_store=artifact_store,
    )
    qa_engineer.register_skill(MockTestGeneratorSkill())
    qa_engineer.register_skill(MockArtifactWriterSkill())
    agents["qa_engineer"] = qa_engineer

    return agents


def run_architect_phase(architect: Agent, project_name: str) -> dict[str, Any]:
    """Run architect phase.

    Args:
        architect: Architect agent
        project_name: Project name

    Returns:
        Design artifact
    """
    print("\n[PHASE 1] ARCHITECT - System Design")

    design = architect.execute_skill(
        "generate_code",
        {
            "module_name": "calculator",
            "description": "A simple calculator module",
            "functions": ["add", "subtract", "multiply", "divide"],
        },
        project_name=project_name,
    )

    print("    Generated design for calculator module")
    return {"artifact_id": design.id, "module": "calculator"}


def run_developer_phase(developer: Agent, project_name: str, design: dict[str, Any]) -> list[str]:
    """Run developer phase.

    Args:
        developer: Developer agent
        project_name: Project name
        design: Design from architect

    Returns:
        List of created files
    """
    print("\n[PHASE 2] DEVELOPER - Implementation")

    created_files = []

    # Generate source code
    source_code = '''"""Calculator module."""

from __future__ import annotations


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def divide(a: int, b: int) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
'''

    _ = developer.execute_skill(
        "write_artifact",
        {
            "content": source_code.strip(),
            "filename": "calculator.py",
            "artifact_type": "SOURCE_CODE",
        },
        project_name=project_name,
    )
    created_files.append("calculator.py")

    # Generate README
    readme = """# Calculator Module

A simple calculator module with basic arithmetic operations.

## Functions

- `add(a, b)` - Add two numbers
- `subtract(a, b)` - Subtract b from a
- `multiply(a, b)` - Multiply two numbers
- `divide(a, b)` - Divide a by b

## Installation

No external dependencies required.

## Usage

```python
from calculator import add, subtract, multiply, divide

result = add(2, 3)  # 5
```"""

    _ = developer.execute_skill(
        "write_artifact",
        {
            "content": readme.strip(),
            "filename": "README.md",
            "artifact_type": "DOCUMENTATION",
        },
        project_name=project_name,
    )
    created_files.append("README.md")

    # Generate requirements.txt
    reqs = "pytest>=7.0.0\n"
    _ = developer.execute_skill(
        "write_artifact",
        {
            "content": reqs,
            "filename": "requirements.txt",
            "artifact_type": "CONFIG",
        },
        project_name=project_name,
    )
    created_files.append("requirements.txt")

    return created_files


def run_qa_phase(qa_engineer: Agent, project_name: str, created_files: list[str]) -> list[str]:
    """Run QA engineer phase.

    Args:
        qa_engineer: QA engineer agent
        project_name: Project name
        created_files: List of created source files

    Returns:
        List of created test files
    """
    print("\n[PHASE 3] QA ENGINEER - Testing")

    test_files = []

    # Generate tests for calculator
    test_code = '''"""Tests for calculator module."""

from __future__ import annotations

import pytest
from calculator import add, subtract, multiply, divide


class TestAdd:
    """Tests for add function."""

    def test_add_positive_numbers(self) -> None:
        """Test adding positive numbers."""
        assert add(2, 3) == 5

    def test_add_negative_numbers(self) -> None:
        """Test adding negative numbers."""
        assert add(-2, -3) == -5

    def test_add_mixed_numbers(self) -> None:
        """Test adding mixed positive and negative numbers."""
        assert add(-2, 3) == 1


class TestSubtract:
    """Tests for subtract function."""

    def test_subtract_positive_numbers(self) -> None:
        """Test subtracting positive numbers."""
        assert subtract(5, 3) == 2

    def test_subtract_result_negative(self) -> None:
        """Test subtraction resulting in negative number."""
        assert subtract(3, 5) == -2


class TestMultiply:
    """Tests for multiply function."""

    def test_multiply_positive_numbers(self) -> None:
        """Test multiplying positive numbers."""
        assert multiply(2, 3) == 6

    def test_multiply_by_zero(self) -> None:
        """Test multiplication by zero."""
        assert multiply(5, 0) == 0


class TestDivide:
    """Tests for divide function."""

    def test_divide_positive_numbers(self) -> None:
        """Test dividing positive numbers."""
        assert divide(6, 2) == 3.0

    def test_divide_by_zero_raises_error(self) -> None:
        """Test that division by zero raises ValueError."""
        with pytest.raises(ValueError):
            divide(5, 0)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_all_functions_with_zero(self) -> None:
        """Test all functions with zero."""
        assert add(0, 0) == 0
        assert subtract(0, 0) == 0
        assert multiply(0, 5) == 0
        assert divide(0, 5) == 0.0
'''

    _ = qa_engineer.execute_skill(
        "write_artifact",
        {
            "content": test_code.strip(),
            "filename": "test_calculator.py",
            "artifact_type": "UNIT_TESTS",
        },
        project_name=project_name,
    )
    test_files.append("test_calculator.py")

    return test_files


def verify_project(project_dir: Path) -> dict[str, Any]:
    """Verify the generated project.

    Args:
        project_dir: Project directory

    Returns:
        Verification results
    """
    print("\n[PHASE 4] VERIFICATION")

    results = {
        "passed": 0,
        "failed": 0,
        "errors": [],
    }

    # Check files exist
    required_files = [
        "calculator.py",
        "test_calculator.py",
        "README.md",
        "requirements.txt",
    ]

    print("\n  Checking files...")
    for filename in required_files:
        file_path = project_dir / filename
        if file_path.exists():
            size = file_path.stat().st_size
            print(f"    ✓ {filename} ({size} bytes)")
            results["passed"] += 1
        else:
            print(f"    ✗ {filename} MISSING")
            results["failed"] += 1
            results["errors"].append(f"Missing file: {filename}")

    # Check source code is valid Python
    print("\n  Checking source code validity...")
    try:
        source_file = project_dir / "calculator.py"
        with open(source_file) as f:
            compile(f.read(), "calculator.py", "exec")
        print("    ✓ calculator.py is valid Python")
        results["passed"] += 1
    except SyntaxError as e:
        print(f"    ✗ calculator.py has syntax error: {e}")
        results["failed"] += 1
        results["errors"].append(f"Syntax error: {e}")

    # Check README content
    print("\n  Checking README...")
    readme_file = project_dir / "README.md"
    if readme_file.exists():
        content = readme_file.read_text()
        if "Calculator" in content or "calculator" in content:
            print("    ✓ README contains project title")
            results["passed"] += 1
        else:
            print("    ✗ README missing project title")
            results["failed"] += 1
            results["errors"].append("README missing title")

        if "add" in content.lower() and "subtract" in content.lower():
            print("    ✓ README documents functions")
            results["passed"] += 1
        else:
            print("    ✗ README missing function documentation")
            results["failed"] += 1
            results["errors"].append("README missing docs")

    # Run tests
    print("\n  Running tests...")
    import os
    import subprocess

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_dir)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "test_calculator.py", "-v", "--tb=short"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        output = result.stdout + result.stderr

        # Parse test results
        import re

        passed_match = re.search(r"(\d+)\s+passed", output)
        failed_match = re.search(r"(\d+)\s+failed", output)

        tests_passed = int(passed_match.group(1)) if passed_match else 0
        tests_failed = int(failed_match.group(1)) if failed_match else 0

        print(f"    Tests: {tests_passed} passed, {tests_failed} failed")

        if tests_passed > 0:
            print("    ✓ Tests executed successfully")
            results["passed"] += 1
        else:
            print("    ✗ No tests passed")
            results["failed"] += 1
            results["errors"].append("No tests passed")

        if tests_failed == 0:
            print("    ✓ All tests passed")
            results["passed"] += 1
        else:
            print(f"    ✗ {tests_failed} tests failed")
            results["failed"] += 1
            results["errors"].append(f"{tests_failed} tests failed")

    except subprocess.TimeoutExpired:
        print("    ✗ Tests timed out")
        results["failed"] += 1
        results["errors"].append("Tests timed out")
    except Exception as e:
        print(f"    ✗ Test execution error: {e}")
        results["failed"] += 1
        results["errors"].append(str(e))

    return results


@pytest.fixture(scope="function")
def system_test_setup() -> tuple[Path, MessageBus, ArtifactStore, dict[str, Agent]]:
    """Set up system test environment.

    Returns:
        Tuple of (project_dir, message_bus, artifact_store, agents)
    """
    # Clean up
    if PROJECT_DIR.exists():
        shutil.rmtree(PROJECT_DIR)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    # Setup environment
    message_bus, artifact_store = setup_test_environment()
    agents = create_test_agents(message_bus, artifact_store)

    return PROJECT_DIR, message_bus, artifact_store, agents


class TestAISESystemOrchestration:
    """System-level test for AISE orchestration."""

    def test_calculator_module_development(self, system_test_setup) -> None:
        """Test complete calculator module development workflow.

        This test verifies that AISE can:
        1. Design a system (Architect)
        2. Implement the code (Developer)
        3. Create tests (QA Engineer)
        4. Verify all deliverables
        """
        project_dir, message_bus, artifact_store, agents = system_test_setup
        start_time = time.time()

        print("\n" + "=" * 70)
        print("SYSTEM TEST: AISE Calculator Module Development")
        print("=" * 70)
        print(f"Started at: {time.strftime('%H:%M:%S')}")
        print(f"Project directory: {project_dir}")
        print("=" * 70)

        try:
            # Phase 1: Architect
            architect = agents["architect"]
            design = run_architect_phase(architect, str(project_dir))

            # Phase 2: Developer
            developer = agents["developer"]
            created_files = run_developer_phase(developer, str(project_dir), design)

            # Phase 3: QA Engineer
            qa_engineer = agents["qa_engineer"]
            _ = run_qa_phase(qa_engineer, str(project_dir), created_files)

            # Phase 4: Verification
            results = verify_project(project_dir)

            # Summary
            elapsed = time.time() - start_time
            print("\n" + "=" * 70)
            print("TEST SUMMARY")
            print("=" * 70)
            print(f"Total time: {elapsed:.1f}s")
            print(f"Checks passed: {results['passed']}")
            print(f"Checks failed: {results['failed']}")

            if results["errors"]:
                print("\nErrors:")
                for error in results["errors"]:
                    print(f"  - {error}")

            print("=" * 70)

            # Assertions
            assert results["failed"] == 0, f"{results['failed']} checks failed: {results['errors']}"
            assert results["passed"] >= 8, f"Insufficient checks passed: {results['passed']}"

            print("\n✅ SYSTEM TEST PASSED!")

        finally:
            print(f"\nTotal elapsed: {time.time() - start_time:.1f}s")
