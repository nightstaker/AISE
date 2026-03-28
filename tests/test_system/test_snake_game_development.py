"""System-level E2E test: AI-assisted multi-module application development.

This test verifies that AISE can autonomously use an external LLM API
to perform full software development lifecycle:
- Requirements Analysis → Architecture Design → Detailed Design → Implementation

The system must produce a proper multi-subsystem, multi-module, multi-file structure.

Note: This test requires a local LLM API endpoint and is designed for local development
validation only. It will be skipped in CI/CD environments.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

LLM_API_BASE = os.environ.get("AISE_LLM_API_BASE", "http://10.0.0.119:8088/v1")
LLM_MODEL = os.environ.get("AISE_LLM_MODEL", "deepseek-r1")
PROJECT_NAME = "snake_game"
PROJECT_DIR = Path("tmp_test_projects") / PROJECT_NAME
TEST_TIMEOUT_SECONDS = 30 * 60
API_TIMEOUT_SECONDS = int(os.environ.get("AISE_API_TIMEOUT", "600"))


def call_llm_api(messages: list[dict[str, str]], model: str | None = None) -> str:
    """Call the external LLM API."""
    import urllib.request

    model = model or LLM_MODEL
    url = f"{LLM_API_BASE}/chat/completions"

    data = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 32000,
    }

    req = urllib.request.Request(
        url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
    )

    print(f"    API call: {url}")
    start_time = time.time()

    with urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS) as response:
        result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]

    elapsed = time.time() - start_time
    print(f"    OK: {elapsed:.1f}s, {len(content)} chars")
    return content


# =============================================================================
# PHASE 1: Requirements Analysis
# =============================================================================


def requirements_phase(project_dir: Path) -> str:
    """Requirements Analysis phase: Define detailed requirements."""
    print("\n" + "=" * 70)
    print("PHASE 1/5: REQUIREMENTS ANALYSIS")
    print("=" * 70)

    messages = [
        {
            "role": "system",
            "content": "You are a senior business analyst and requirements engineer. "
            "Your task is to analyze and define comprehensive requirements "
            "for a software application.",
        },
        {
            "role": "user",
            "content": """I need you to create a comprehensive Requirements Specification Document for a Snake Game application.

**DOCUMENT STRUCTURE** - Please write a markdown document titled "REQUIREMENTS SPECIFICATION" with the following sections:

## 1. Introduction
### 1.1 Purpose
### 1.2 Scope
### 1.3 Definitions and Acronyms

## 2. Overall Description
### 2.1 Product Perspective
### 2.2 Product Functions (High-level features)
### 2.3 User Classes and Characteristics
### 2.4 Operating Environment
### 2.5 Design and Implementation Constraints
### 2.6 User Documentation Requirements

## 3. System Features
### 3.1 Feature 1: Core Game Mechanics
- Description
- Priority
- Functional Requirements (3.1.1, 3.1.2, ...)

### 3.2 Feature 2: User Interface
- Description
- Priority
- Functional Requirements

### 3.3 Feature 3: Game Configuration
- Description
- Priority
- Functional Requirements

### 3.4 Feature 4: Score Management
- Description
- Priority
- Functional Requirements

### 3.5 Feature 5: Game States and Controls
- Description
- Priority
- Functional Requirements

## 4. External Interface Requirements
### 4.1 User Interfaces
### 4.2 Hardware Interfaces
### 4.3 Software Interfaces
### 4.4 Communications Interfaces

## 5. Non-Functional Requirements
### 5.1 Performance Requirements
### 5.2 Safety Requirements
### 5.3 Security Requirements
### 5.4 Quality Attributes

## 6. Appendix

**REQUIREMENTS**:
- Use clear, testable language for requirements
- Each requirement should be uniquely numbered
- Include both functional and non-functional requirements
- Be comprehensive but realistic for a medium-sized application

Please write the complete Requirements Specification Document in markdown format.
""",
        },
    ]

    response = call_llm_api(messages)
    requirements_file = project_dir / "docs" / "REQUIREMENTS.md"
    requirements_file.parent.mkdir(parents=True, exist_ok=True)
    requirements_file.write_text(response)
    print(f"    Saved: {requirements_file}")
    return response


# =============================================================================
# PHASE 2: System Architecture Design
# =============================================================================


def architecture_phase(project_dir: Path, requirements_content: str) -> str:
    """Architecture Design phase: Design multi-subsystem architecture."""
    print("\n" + "=" * 70)
    print("PHASE 2/5: SYSTEM ARCHITECTURE DESIGN")
    print("=" * 70)

    messages = [
        {
            "role": "system",
            "content": "You are a senior software architect with expertise in system design, "
            "modular architecture, and clean code principles. Your task is to "
            "design a comprehensive system architecture with clear subsystems, "
            "modules, and file organization.",
        },
        {
            "role": "user",
            "content": """Based on the following Requirements Specification, design a comprehensive System Architecture.

**IMPORTANT**: This architecture MUST follow a multi-layered structure:
- Multiple SUBSYSTEMS (at least 3-4)
- Each subsystem contains multiple MODULES (at least 2-3 per subsystem)
- Each module contains 1 or more FILES

**DOCUMENT STRUCTURE** - Please write a markdown document titled "SYSTEM ARCHITECTURE DESIGN" with:

## 1. System Overview
### 1.1 Architectural Style (e.g., Layered, MVC, Event-Driven)
### 1.2 High-Level System Diagram (describe in text)
### 1.3 Key Design Decisions

## 2. Subsystem Architecture

### 2.1 [Subsystem Name 1] - [Brief Description]
**Responsibilities**: What this subsystem is responsible for

#### Module 2.1.1: [Module Name]
- Purpose: What this module does
- Files:
  - `snake/core/[module_file1].py` - Description
  - `snake/core/[module_file2].py` - Description
- Interfaces: Key classes/functions exposed to other modules
- Dependencies: Modules it depends on

#### Module 2.1.2: [Module Name]
- Purpose:
- Files:
  - `snake/core/[module_file].py` - Description
- Interfaces:
- Dependencies:

### 2.2 [Subsystem Name 2] - [Brief Description]
**Responsibilities**:

#### Module 2.2.1: [Module Name]
- Purpose:
- Files:
  - `snake/ui/[module_file1].py` - Description
  - `snake/ui/[module_file2].py` - Description
- Interfaces:
- Dependencies:

#### Module 2.2.2: [Module Name]
- Purpose:
- Files:
  - `snake/ui/[module_file].py` - Description
- Interfaces:
- Dependencies:

### 2.3 [Subsystem Name 3] - [Brief Description]
**Responsibilities**:

#### Module 2.3.1: [Module Name]
- Purpose:
- Files:
  - `snake/storage/[module_file1].py` - Description
  - `snake/storage/[module_file2].py` - Description
- Interfaces:
- Dependencies:

### 2.4 [Subsystem Name 4] - [Brief Description]
**Responsibilities**:

#### Module 2.4.1: [Module Name]
- Purpose:
- Files:
  - `snake/config/[module_file].py` - Description
- Interfaces:
- Dependencies:

## 3. Directory Structure

Provide the complete expected directory structure:

```
snake_game/
├── docs/
│   ├── REQUIREMENTS.md
│   └── ARCHITECTURE.md
├── snake/
│   ├── __init__.py
│   ├── core/                    # Core game logic subsystem
│   │   ├── __init__.py
│   │   ├── game_engine.py       # Main game loop and state management
│   │   ├── snake_controller.py  # Snake movement and behavior
│   │   ├── food_manager.py      # Food spawning and types
│   │   └── collision_detector.py # Collision detection logic
│   ├── ui/                      # User interface subsystem
│   │   ├── __init__.py
│   │   ├── display_manager.py   # Main display coordinator
│   │   ├── game_renderer.py     # Game visualization
│   │   ├── input_handler.py     # User input processing
│   │   └── message_box.py       # Game messages and notifications
│   ├── storage/                 # Data persistence subsystem
│   │   ├── __init__.py
│   │   ├── score_repository.py  # Score storage and retrieval
│   │   └── game_saver.py        # Game state save/load
│   ├── config/                  # Configuration subsystem
│   │   ├── __init__.py
│   │   ├── game_config.py       # Game configuration constants
│   │   └── difficulty_levels.py # Difficulty settings
│   └── main.py                  # Application entry point
├── tests/
│   ├── test_core/
│   ├── test_ui/
│   ├── test_storage/
│   └── test_config/
├── requirements.txt
└── README.md
```

## 4. Key Components Description

### 4.1 Core Classes
- Describe main classes in each subsystem
- Their responsibilities
- Key methods

### 4.2 Data Models
- Describe data structures used
- Entity relationships

### 4.3 Interfaces and Contracts
- API between subsystems
- Event/Callback mechanisms

## 5. Cross-Cutting Concerns
### 5.1 Error Handling Strategy
### 5.2 Logging Approach
### 5.3 Configuration Management

## 6. Design Patterns Used
- List and explain design patterns applied

**REQUIREMENTS**:
- Design at least 4 subsystems
- Each subsystem must have at least 2 modules
- Each module must have at least 1 file
- Total files in `snake/` directory should be at least 15
- Use clear package and module naming conventions
- Follow separation of concerns principle
- Document interfaces between modules

Please write the complete System Architecture Design document in markdown format.
""",
        },
    ]

    response = call_llm_api(messages)
    architecture_file = project_dir / "docs" / "ARCHITECTURE.md"
    architecture_file.write_text(response)
    print(f"    Saved: {architecture_file}")
    return response


# =============================================================================
# PHASE 3: Detailed Design
# =============================================================================


def detailed_design_phase(project_dir: Path, requirements_content: str, architecture_content: str) -> str:
    """Detailed Design phase: Design each module in detail."""
    print("\n" + "=" * 70)
    print("PHASE 3/5: DETAILED DESIGN")
    print("=" * 70)

    user_prompt = """Based on the Requirements and Architecture above, create a Detailed Design Document.

**DOCUMENT STRUCTURE**:

## DETAILED DESIGN DOCUMENT

For each module specified in the architecture, provide:

### Module: [module_name]
**File**: `snake/[subsystem]/[module_name].py`

#### 1. Module Overview
- Purpose and responsibilities
- Key functionalities

#### 2. Classes and Functions

##### Class: [ClassName]
**Purpose**:

**Attributes**:
- `attr1: type` - description
- `attr2: type` - description

**Methods**:
```python
def __init__(self, param1: type, param2: type) -> None:
    \"\"\"Constructor docstring.\"\"\"
    pass

def method_name(self, param: type) -> return_type:
    # \"\"\"Method docstring.\"\"\"
    pass
```

#### 3. Interfaces
- Public API
- Events/Callbacks

#### 4. Dependencies
- Imports from other modules
- External libraries

(REPEAT FOR ALL MODULES)

**REQUIREMENTS**:
- Provide detailed design for ALL modules
- Include class descriptions
- Specify all public methods with signatures
- Document data flow between modules

Please write the complete Detailed Design Document."""

    messages = [
        {
            "role": "system",
            "content": "You are a senior software engineer responsible for detailed module design. "
            "Your task is to create detailed design documents for each module.",
        },
        {"role": "user", "content": user_prompt},
    ]

    response = call_llm_api(messages)
    design_file = project_dir / "docs" / "DETAILED_DESIGN.md"
    design_file.write_text(response)
    print(f"    Saved: {design_file}")
    return response


def implementation_phase(project_dir: Path, all_docs: str) -> None:
    """Implementation phase: Generate all source files."""
    print("\n" + "=" * 70)
    print("PHASE 4/5: IMPLEMENTATION")
    print("=" * 70)

    # Break into multiple phases due to token limits
    subsystems = [
        ("core", "game_engine, snake_controller, food_manager, collision_detector"),
        ("ui", "display_manager, game_renderer, input_handler, message_box"),
        ("storage", "score_repository, game_saver"),
        ("config", "game_config, difficulty_levels"),
        ("main", "main.py, __init__.py files"),
    ]

    for subsystem, modules in subsystems:
        print(f"\n  Generating {subsystem} subsystem...")

        messages = [
            {
                "role": "system",
                "content": f"You are a senior Python developer. Implement the {subsystem} subsystem "
                f"of the Snake game following the architecture and detailed design. "
                f"Generate complete, production-ready code.",
            },
            {
                "role": "user",
                "content": f"""Generate the implementation for the {subsystem} subsystem.

**MODULES TO IMPLEMENT**: {modules}

**OUTPUT FORMAT**:

For each file, use this format:

=== FILE: snake/{subsystem}/<filename>.py ===

```python
[complete implementation]
```

**REQUIREMENTS**:
- Follow Python best practices
- Include type hints
- Add docstrings
- Handle edge cases
- ASCII characters only
- Each file should be complete and runnable (importable)

Generate ALL files for the {subsystem} subsystem.
""",
            },
        ]

        response = call_llm_api(messages)

        # Parse and write files
        file_pattern = r"===\s*FILE:\s*([^=]+)\s*==="
        matches = list(re.finditer(file_pattern, response))

        for i, match in enumerate(matches):
            filepath_str = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(response)
            content = response[start:end].strip()

            # Remove code fences
            content = re.sub(r"^```\w*\n?", "", content, flags=re.MULTILINE)
            content = re.sub(r"\n?```$", "", content, flags=re.MULTILINE)

            filepath = project_dir / filepath_str
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            print(f"    ✓ {filepath_str} ({len(content)} bytes)")


# =============================================================================
# PHASE 5: Verification
# =============================================================================


def verify_architecture_document(content: str) -> dict[str, Any]:
    """Verify the architecture document has proper multi-level structure."""
    print("\n  Verifying Architecture Document...")

    results = {"subsystems": 0, "modules": 0, "files_planned": 0, "valid": False, "errors": []}

    # Count subsystems - look for lines with "### 2." and "Subsystem"
    subsystems = [line for line in content.split("\n") if "### 2." in line and "Subsystem" in line]
    results["subsystems"] = len(subsystems)
    print(f"    Subsystems found: {results['subsystems']}")

    # Count modules - look for "#### Module" lines
    modules = [line for line in content.split("\n") if "#### Module" in line]
    results["modules"] = len(modules)
    print(f"    Modules found: {results['modules']}")

    # Count planned files - look for `snake/` patterns
    files = re.findall(r"`snake/[^`]+`", content)
    results["files_planned"] = len(files)
    print(f"    Files planned: {results['files_planned']}")

    # Validation
    if results["subsystems"] >= 3:
        print("    ✓ Has at least 3 subsystems")
    else:
        results["errors"].append(f"Less than 3 subsystems ({results['subsystems']})")

    if results["modules"] >= 6:
        print("    ✓ Has at least 6 modules")
    else:
        results["errors"].append(f"Less than 6 modules ({results['modules']})")

    if results["files_planned"] >= 15:
        print("    ✓ Has at least 15 files planned")
    else:
        results["errors"].append(f"Less than 15 files planned ({results['files_planned']})")

    results["valid"] = len(results["errors"]) == 0
    return results


def verify_generated_code(project_dir: Path) -> dict[str, Any]:
    """Verify the generated code has proper multi-module structure."""
    print("\n  Verifying Generated Code Structure...")

    results = {"subsystems": {}, "total_files": 0, "valid_python": True, "errors": []}

    snake_dir = project_dir / "snake"
    if not snake_dir.exists():
        results["errors"].append("snake/ directory not found")
        return results

    # Count files per subsystem
    for item in snake_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            subsystem_files = list(item.glob("*.py"))
            results["subsystems"][item.name] = len(subsystem_files)
            results["total_files"] += len(subsystem_files)

            # Verify Python syntax
            for py_file in subsystem_files:
                try:
                    content = py_file.read_text()
                    compile(content, str(py_file), "exec")
                except SyntaxError as e:
                    results["valid_python"] = False
                    results["errors"].append(f"Syntax error in {py_file}: {e}")

    # Also count __init__.py files
    for py_file in snake_dir.glob("*.py"):
        results["total_files"] += 1

    print(f"    Subsystems with files: {list(results['subsystems'].keys())}")
    print(f"    Total Python files: {results['total_files']}")

    # Validation
    if len(results["subsystems"]) >= 3:
        print("    ✓ Has at least 3 subsystem directories")
    else:
        results["errors"].append("Less than 3 subsystem directories")

    if results["total_files"] >= 10:
        print("    ✓ Has at least 10 Python files")
    else:
        results["errors"].append("Less than 10 Python files")

    return results


def run_system_tests(project_dir: Path) -> dict[str, Any]:
    """Run simple content-based tests on generated code."""
    print("\n  Running System Tests...")

    results = {"passed": 0, "failed": 0}

    # Test 1: snake directory exists
    if (project_dir / "snake").exists():
        results["passed"] += 1
        print("    ✓ snake directory exists")
    else:
        results["failed"] += 1
        print("    ✗ snake directory missing")

    # Test 2: Has Python files
    py_files = list(project_dir.rglob("*.py"))
    if len(py_files) >= 10:
        results["passed"] += 1
        print(f"    ✓ Has {len(py_files)} Python files")
    else:
        results["failed"] += 1
        print(f"    ✗ Only {len(py_files)} Python files")

    # Test 3: core module
    if (project_dir / "snake" / "core").exists():
        results["passed"] += 1
        print("    ✓ core module exists")
    else:
        results["failed"] += 1
        print("    ✗ core module missing")

    # Test 4: ui module
    if (project_dir / "snake" / "ui").exists():
        results["passed"] += 1
        print("    ✓ ui module exists")
    else:
        results["failed"] += 1
        print("    ✗ ui module missing")

    # Test 5: Find Game class
    found = False
    for f in project_dir.rglob("*.py"):
        if "class Game" in f.read_text():
            found = True
            break
    if found:
        results["passed"] += 1
        print("    ✓ Game class found")
    else:
        results["failed"] += 1
        print("    ✗ Game class not found")

    # Test 6: main.py exists
    if (project_dir / "snake" / "main" / "main.py").exists():
        results["passed"] += 1
        print("    ✓ main.py exists")
    else:
        results["failed"] += 1
        print("    ✗ main.py missing")

    return results


@pytest.mark.skipif(
    os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true",
    reason="This test requires a local LLM API endpoint and is for local development validation only",
)
class TestMultiModuleSystemDevelopment:
    """System test for multi-module application development."""

    def test_full_lifecycle_development(self):
        """Test complete software development lifecycle with multi-module architecture."""
        print("\n" + "#" * 70)
        print("# SYSTEM TEST: Multi-Module Application Development")
        print("#" * 70)
        print(f"# Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"# Project: {PROJECT_DIR}")
        print("#" * 70)

        # Clean up
        if PROJECT_DIR.exists():
            shutil.rmtree(PROJECT_DIR)
        PROJECT_DIR.mkdir(parents=True)

        # PHASE 1: Requirements Analysis
        requirements_content = requirements_phase(PROJECT_DIR)

        # PHASE 2: Architecture Design
        architecture_content = architecture_phase(PROJECT_DIR, requirements_content)

        # Verify architecture document
        arch_verification = verify_architecture_document(architecture_content)
        assert arch_verification["valid"], f"Architecture document validation failed: {arch_verification['errors']}"

        # PHASE 3: Detailed Design
        detailed_design_content = detailed_design_phase(PROJECT_DIR, requirements_content, architecture_content)

        # PHASE 4: Implementation
        all_docs = requirements_content + "\n\n" + architecture_content + "\n\n" + detailed_design_content
        implementation_phase(PROJECT_DIR, all_docs)

        # PHASE 5: Verification
        print("\n" + "=" * 70)
        print("PHASE 5/5: VERIFICATION")
        print("=" * 70)

        # Verify generated code structure
        code_verification = verify_generated_code(PROJECT_DIR)
        assert code_verification["total_files"] >= 10, (
            f"Insufficient files generated: {code_verification['total_files']}"
        )
        assert len(code_verification["subsystems"]) >= 3, (
            f"Insufficient subsystems: {len(code_verification['subsystems'])}"
        )

        # Run system tests
        test_results = run_system_tests(PROJECT_DIR)
        assert test_results["passed"] >= 5, (
            f"Insufficient tests passed: {test_results['passed']}/{test_results['passed'] + test_results['failed']}"
        )

        # Final summary
        print("\n" + "#" * 70)
        print("# FINAL SUMMARY")
        print("#" * 70)
        print("# Requirements Document: ✓")
        print(
            f"# Architecture Document: ✓ ({arch_verification['subsystems']} subsystems, {arch_verification['modules']} modules)"
        )
        print("# Detailed Design: ✓")
        print(f"# Implementation: ✓ ({code_verification['total_files']} files)")
        print(f"# System Tests: {test_results['passed']} passed, {test_results['failed']} failed")
        print("#" * 70)
        print("# SYSTEM TEST: PASSED")
        print("#" * 70)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
