# Agent: QA Engineer

## Overview

| Field | Value |
|-------|-------|
| **Name** | `qa_engineer` |
| **Class** | `QAEngineerAgent` |
| **Module** | `aise.agents.qa_engineer` |
| **Role** | `AgentRole.QA_ENGINEER` |
| **Description** | Agent responsible for test planning, design, and automation |

## Purpose

The QA Engineer agent owns the testing phase of the development workflow. It creates comprehensive test plans, designs detailed test cases (integration, E2E, regression), implements automated test scripts, and reviews overall test quality and coverage.

## Skills

| Skill Name | Class | Description |
|------------|-------|-------------|
| `test_plan_design` | `TestPlanDesignSkill` | Design comprehensive test plans with scope, strategy, and risk analysis |
| `test_case_design` | `TestCaseDesignSkill` | Design detailed integration, E2E, and regression test cases |
| `test_automation` | `TestAutomationSkill` | Generate automated test scripts from test case designs |
| `test_review` | `TestReviewSkill` | Review test coverage, quality, and identify testing gaps |

## Workflow Phase

**Primary Phase:** Testing

### Execution Order
1. `test_plan_design` — Define testing scope, strategy, and risks
2. `test_case_design` — Design detailed test cases per endpoint and component
3. `test_automation` — Generate pytest scripts from test cases
4. `test_review` — Validate coverage and quality metrics (review gate)

## Artifacts Produced

| Artifact Type | Skill | Description |
|---------------|-------|-------------|
| `TEST_PLAN` | `test_plan_design` | Testing scope, strategy, risks, and subsystem plans |
| `TEST_CASES` | `test_case_design` | Detailed test cases with preconditions and expected results |
| `AUTOMATED_TESTS` | `test_automation` | Pytest scripts, conftest, and configuration |
| `REVIEW_FEEDBACK` | `test_review` | Test quality review with coverage metrics |

## Artifacts Consumed

| Artifact Type | By Skill | Purpose |
|---------------|----------|---------|
| `ARCHITECTURE_DESIGN` | `test_plan_design`, `test_case_design` | Components for subsystem planning and E2E tests |
| `API_CONTRACT` | `test_plan_design`, `test_case_design`, `test_review` | Endpoints for integration tests and coverage |
| `TEST_CASES` | `test_automation`, `test_review` | Test cases to automate and review |
| `TECH_STACK` | `test_automation` | Testing tools selection |
| `TEST_PLAN` | `test_review` | Verify test plan exists |
| `AUTOMATED_TESTS` | `test_review` | Measure automation rate |
| `UNIT_TESTS` | `test_review` | Count unit tests for coverage |

## Communication

### Messages Received
- `REQUEST` with `skill` field matching any registered skill name
- Responds with `RESPONSE` containing `status` and `artifact_id`

### Messages Sent
- Can request skills from other agents via `request_skill()`

## Integration Points

### Upstream Agents
- **Architect** — consumes `ARCHITECTURE_DESIGN`, `API_CONTRACT`
- **Developer** — consumes `UNIT_TESTS` for coverage metrics

### Downstream Agents
- None — this is the final phase agent

### Review Gates
- `test_review` serves as the review gate for the testing phase
- Sets automated tests status to `APPROVED` or `REJECTED`
- Checks endpoint coverage (target: 70%), automation rate (target: 60%), and test type balance

## Usage

```python
from aise.core.message import MessageBus
from aise.core.artifact import ArtifactStore
from aise.agents.qa_engineer import QAEngineerAgent

bus = MessageBus()
store = ArtifactStore()
qa = QAEngineerAgent(bus, store)

# Design test plan
artifact = qa.execute_skill("test_plan_design", {}, project_name="My Project")

# Design and automate tests
qa.execute_skill("test_case_design", {}, project_name="My Project")
qa.execute_skill("test_automation", {}, project_name="My Project")

# Review test quality
review = qa.execute_skill("test_review", {}, project_name="My Project")
```
