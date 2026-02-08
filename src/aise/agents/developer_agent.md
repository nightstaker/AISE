# Agent: Developer

## Overview

| Field | Value |
|-------|-------|
| **Name** | `developer` |
| **Class** | `DeveloperAgent` |
| **Module** | `aise.agents.developer` |
| **Role** | `AgentRole.DEVELOPER` |
| **Description** | Agent responsible for code implementation, testing, and bug fixing |

## Purpose

The Developer agent owns the implementation phase of the development workflow. It generates source code from architecture and API designs, writes unit tests, reviews code quality, and fixes bugs from reports or failing tests.

## Skills

| Skill Name | Class | Description |
|------------|-------|-------------|
| `code_generation` | `CodeGenerationSkill` | Generate source code from architecture design and API contracts |
| `unit_test_writing` | `UnitTestWritingSkill` | Generate unit tests with edge-case coverage |
| `code_review` | `CodeReviewSkill` | Review code for correctness, style, security, and performance |
| `bug_fix` | `BugFixSkill` | Analyze bug reports or failing tests and produce fixes |

## Workflow Phase

**Primary Phase:** Implementation

### Execution Order
1. `code_generation` — Generate module scaffolding from architecture
2. `unit_test_writing` — Generate test suites for each module
3. `code_review` — Review code quality and test coverage (review gate)
4. `bug_fix` — Fix issues found during review or testing (on demand)

## Artifacts Produced

| Artifact Type | Skill | Description |
|---------------|-------|-------------|
| `SOURCE_CODE` | `code_generation` | Module files (models, routes, services) |
| `UNIT_TESTS` | `unit_test_writing` | Test suites per module |
| `REVIEW_FEEDBACK` | `code_review` | Code quality review results |
| `BUG_REPORT` | `bug_fix` | Bug fix records with root cause analysis |

## Artifacts Consumed

| Artifact Type | By Skill | Purpose |
|---------------|----------|---------|
| `ARCHITECTURE_DESIGN` | `code_generation` | Service components to generate |
| `API_CONTRACT` | `code_generation` | Endpoints for route generation |
| `TECH_STACK` | `code_generation` | Language and framework selection |
| `SOURCE_CODE` | `unit_test_writing`, `code_review`, `bug_fix` | Code to test/review/fix |
| `UNIT_TESTS` | `code_review` | Check test coverage |

## Communication

### Messages Received
- `REQUEST` with `skill` field matching any registered skill name
- Responds with `RESPONSE` containing `status` and `artifact_id`

### Messages Sent
- Can request skills from other agents via `request_skill()`

## Integration Points

### Upstream Agents
- **Architect** — consumes `ARCHITECTURE_DESIGN`, `API_CONTRACT`, `TECH_STACK`

### Downstream Agents
- **QA Engineer** — consumes `SOURCE_CODE` indirectly (architecture review checks alignment)

### Review Gates
- `code_review` serves as the review gate for the implementation phase
- Sets source code status to `APPROVED` or `REJECTED`
- Checks for security vulnerabilities, style issues, and test coverage gaps

## Usage

```python
from aise.core.message import MessageBus
from aise.core.artifact import ArtifactStore
from aise.agents.developer import DeveloperAgent

bus = MessageBus()
store = ArtifactStore()
dev = DeveloperAgent(bus, store)

# Generate code
artifact = dev.execute_skill("code_generation", {}, project_name="My Project")

# Fix bugs
artifact = dev.execute_skill("bug_fix", {
    "bug_reports": [{"id": "BUG-001", "description": "Login fails on empty password"}]
}, project_name="My Project")
```
