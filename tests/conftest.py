"""Shared pytest fixtures for deterministic test execution."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from aise.core.llm import LLMClient


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    """Skip langchain tests when optional dependency is unavailable."""
    if "tests/test_langchain" in str(collection_path):
        return importlib.util.find_spec("langchain_core") is None
    if "tests/test_web" in str(collection_path):
        return os.environ.get("AISE_ENABLE_WEB_TESTS", "").lower() not in {"1", "true", "yes"}
    return False


@pytest.fixture(autouse=True)
def mock_llm_for_non_llm_unit_tests(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Provide deterministic LLM responses for tests that do not validate LLM internals."""
    nodeid = request.node.nodeid
    if "tests/test_core/test_model_config.py" in nodeid:
        return

    def _fake_complete(self: LLMClient, messages: list[dict[str, str]], **kwargs: Any) -> str:
        system_text = "\n".join(str(msg.get("content", "")) for msg in messages if msg.get("role") == "system")
        user_text = "\n".join(str(msg.get("content", "")) for msg in messages if msg.get("role") == "user")
        merged = f"{system_text}\n{user_text}"
        round_match = re.search(r"\bRound:\s*(\d+)", user_text)
        round_no = int(round_match.group(1)) if round_match else 1

        def _extract_ids(prefix: str) -> list[str]:
            ids = sorted(set(re.findall(rf"{prefix}-\d+", user_text)))
            return ids

        def _extract_subsystem_names() -> list[str]:
            names = re.findall(r'"name"\s*:\s*"([A-Za-z0-9_\-]+)"', user_text)
            cleaned: list[str] = []
            for name in names:
                if name and name.lower() not in {"service", "component"} and name not in cleaned:
                    cleaned.append(name)
            return cleaned[:6]

        if "step:requirement_expansion.core" in str(kwargs.get("llm_purpose", "")) or (
            "Return JSON only with keys: intent_summary, business_goals." in merged
        ):
            return json.dumps(
                {
                    "intent_summary": (
                        "Clarify user intent and transform raw requirements into an implementable product scope."
                    ),
                    "business_goals": [
                        "Deliver a usable first version that covers the primary user workflow",
                        "Keep behavior deterministic and testable",
                    ],
                }
            )

        if "step:requirement_expansion.context" in str(kwargs.get("llm_purpose", "")) or (
            "Return JSON only with keys: users, scenarios, constraints, assumptions, risks." in merged
        ):
            return json.dumps(
                {
                    "users": ["End users", "Operators"],
                    "scenarios": [
                        "Primary success flow",
                        "Invalid input handling",
                        "Operational troubleshooting",
                    ],
                    "constraints": [
                        "Deterministic behavior",
                        "Observable execution",
                        "Automated testability",
                    ],
                    "assumptions": ["Interfaces can evolve across review rounds"],
                    "risks": ["Requirement ambiguity", "Edge-case coverage gaps"],
                }
            )

        if "step:product_design" in str(kwargs.get("llm_purpose", "")) or (
            "keys: overview, overall_solution, system_features, designer_response" in merged
        ):
            return json.dumps(
                {
                    "overview": (
                        "Product design organizes the requested capabilities into "
                        "traceable system features for implementation."
                    ),
                    "overall_solution": [
                        "Use a modular architecture with clear component boundaries.",
                        "Preserve traceability from user intent to system requirements.",
                    ],
                    "system_features": [
                        {
                            "id": "SF-001",
                            "name": "Primary Workflow",
                            "goal": "Support the main user workflow end-to-end",
                            "functions": [
                                "Handle user requests and validate inputs",
                                "Execute core service logic and state transitions",
                            ],
                            "constraints": ["Deterministic results", "Observable outcomes"],
                            "priority": "high",
                        },
                        {
                            "id": "SF-002",
                            "name": "Operations Visibility",
                            "goal": "Expose metrics and verifiable outcomes for operations",
                            "functions": [
                                "Emit structured execution telemetry",
                                "Provide status visibility for debugging and verification",
                            ],
                            "constraints": ["No flaky timing assumptions"],
                            "priority": "medium",
                        },
                    ],
                    "designer_response": [f"Round {round_no} design generated by mock LLM."],
                }
            )

        if "step:product_review" in str(kwargs.get("llm_purpose", "")) or (
            "Review product design and return JSON only with keys: approved, "
            "summary, issues, suggestions, decision." in merged
        ):
            approved = round_no >= 2
            return json.dumps(
                {
                    "approved": approved,
                    "summary": (
                        "Product design is acceptable." if approved else "Product design needs one refinement round."
                    ),
                    "issues": [] if approved else ["Run one refinement round before approval."],
                    "suggestions": [
                        "Keep feature-to-requirement traceability explicit.",
                        "Retain deterministic acceptance criteria for each feature.",
                    ],
                    "decision": "approve" if approved else "revise",
                }
            )

        if "step:system_requirement_design" in str(kwargs.get("llm_purpose", "")) or (
            "Top-level keys MUST be exactly: design_goals, design_approach, requirements, designer_response." in merged
        ):
            sf_ids = _extract_ids("SF") or ["SF-001"]
            requirements: list[dict[str, Any]] = []
            for idx, sf_id in enumerate(sf_ids[:3], start=1):
                requirements.append(
                    {
                        "source_sfs": [sf_id],
                        "title": f"{sf_id} executable requirement slice {idx}",
                        "requirement_overview": (
                            f"System shall implement verifiable behavior for {sf_id} slice {idx}."
                        ),
                        "scenario": f"As an actor, I can trigger {sf_id} behavior slice {idx}.",
                        "users": ["End users"],
                        "interaction_process": [
                            "User initiates request",
                            "System validates and processes request",
                            "System returns deterministic result",
                        ],
                        "expected_result": (f"System completes {sf_id} slice {idx} with observable outcome."),
                        "spec_targets": ["API contract", "State transition", "Telemetry event"],
                        "constraints": ["Deterministic behavior", "Testable outputs"],
                        "use_case_diagram": "Actor --> System : request\nSystem --> Actor : response",
                        "use_case_description": (f"Use case for {sf_id} slice {idx} execution and validation."),
                        "type": "functional",
                        "category": "Product Capability",
                        "priority": "high" if idx == 1 else "medium",
                        "verification_method": "integration_test",
                    }
                )
            return json.dumps(
                {
                    "design_goals": ["Generate implementable and testable system requirements."],
                    "design_approach": ["Split features into independently verifiable requirement slices."],
                    "requirements": requirements,
                    "designer_response": [f"Round {round_no} SR design generated by mock LLM."],
                }
            )

        if "step:system_requirement_review" in str(kwargs.get("llm_purpose", "")) or (
            "Top-level keys MUST be exactly: approved, summary, issues, suggestions, decision." in merged
            and "system requirements document" in merged.lower()
        ):
            approved = round_no >= 2
            return json.dumps(
                {
                    "approved": approved,
                    "summary": ("SR design approved." if approved else "SR design needs one refinement pass."),
                    "issues": ([] if approved else ["Round 1 baseline requires refinement before approval."]),
                    "suggestions": [
                        "Keep each SR independently verifiable.",
                        "Preserve SF-to-SR traceability on every entry.",
                    ],
                    "decision": "approve" if approved else "revise",
                }
            )

        if "step:architecture_design.foundation" in str(kwargs.get("llm_purpose", "")) or (
            "design_goals (list[str]), principles (list[str]), architecture_overview (str)," in merged
            and "architecture_diagram (str)" in merged
        ):
            return json.dumps(
                {
                    "design_goals": [
                        "Translate product/system requirements into implementable subsystem boundaries",
                        "Preserve traceability and clear API contracts",
                    ],
                    "principles": ["Separation of concerns", "Traceability-first", "Observable behavior"],
                    "architecture_overview": (
                        "The system uses a modular architecture with domain-oriented subsystems, explicit APIs, "
                        "and component responsibilities mapped to requirement slices for downstream detailed design."
                    ),
                    "layering": [
                        "entry interfaces",
                        "application orchestration",
                        "domain logic",
                        "infrastructure adapters",
                    ],
                    "architecture_diagram": (
                        "flowchart TD\n"
                        "  Client[Client] --> Entry[Entry API]\n"
                        "  Entry --> Orchestrator[Application Orchestrator]\n"
                        "  Orchestrator --> DomainA[Domain Subsystem A]\n"
                        "  Orchestrator --> DomainB[Domain Subsystem B]\n"
                        "  DomainA --> Infra[(Infrastructure)]\n"
                        "  DomainB --> Infra\n"
                    ),
                }
            )

        if "step:architecture_design.structure" in str(kwargs.get("llm_purpose", "")) or (
            "Return JSON only with keys: subsystems, components, sr_allocation." in merged
        ):
            sr_ids = _extract_ids("SR") or ["SR-001"]
            subsystem_names = ["request_coordination", "execution_runtime"]
            return json.dumps(
                {
                    "subsystems": [
                        {
                            "name": subsystem_names[0],
                            "description": (
                                "Coordinates request intake, validation, and orchestration across the system."
                            ),
                            "constraints": ["Stable APIs", "Deterministic orchestration"],
                            "apis": [
                                {
                                    "method": "POST",
                                    "path": "/api/v1/requests",
                                    "description": "Submit a request",
                                },
                                {
                                    "method": "GET",
                                    "path": "/api/v1/requests/{id}",
                                    "description": "Read request status",
                                },
                            ],
                        },
                        {
                            "name": subsystem_names[1],
                            "description": (
                                "Executes domain workflows and emits telemetry for verification and operations."
                            ),
                            "constraints": ["Observable processing", "Idempotent execution when possible"],
                            "apis": [
                                {
                                    "method": "POST",
                                    "path": "/api/v1/executions",
                                    "description": "Start execution",
                                },
                                {
                                    "method": "GET",
                                    "path": "/api/v1/executions/{id}",
                                    "description": "Read execution result",
                                },
                            ],
                        },
                    ],
                    "components": [
                        {
                            "name": "request_api_handler",
                            "type": "service",
                            "subsystem_id_or_name": subsystem_names[0],
                            "responsibilities": [
                                "Validate inbound requests",
                                "Route requests to orchestration flows",
                            ],
                        },
                        {
                            "name": "request_state_store",
                            "type": "repository",
                            "subsystem_id_or_name": subsystem_names[0],
                            "responsibilities": [
                                "Persist request state",
                                "Serve request status queries",
                            ],
                        },
                        {
                            "name": "execution_orchestrator",
                            "type": "service",
                            "subsystem_id_or_name": subsystem_names[1],
                            "responsibilities": [
                                "Run domain execution workflow",
                                "Coordinate retry and error handling",
                            ],
                        },
                        {
                            "name": "execution_telemetry_adapter",
                            "type": "adapter",
                            "subsystem_id_or_name": subsystem_names[1],
                            "responsibilities": [
                                "Emit execution metrics",
                                "Publish verifiable execution events",
                            ],
                        },
                    ],
                    "sr_allocation": {
                        subsystem_names[0]: sr_ids,
                        subsystem_names[1]: sr_ids,
                    },
                }
            )

        if "functional_requirements" in merged and "search_evidence" in merged:
            raw_section = user_text.split("原始需求如下，请分析并结构化：", 1)[-1]
            lines = [line.strip() for line in raw_section.splitlines() if line.strip()]
            functional = []
            non_functional = []
            for line in lines:
                lower = line.lower()
                has_nfr_keyword = any(key in lower for key in ("performance", "latency", "p95", "p99"))
                target = non_functional if has_nfr_keyword else functional
                target.append({"description": line, "priority": "high"})
            if not functional:
                functional = [{"description": "Implement primary flow", "priority": "high"}]
            if not non_functional:
                non_functional = [{"description": "Keep p95 latency under 300ms", "priority": "high"}]
            return json.dumps(
                {
                    "summary": "Mock requirement analysis",
                    "functional_requirements": functional,
                    "non_functional_requirements": non_functional,
                    "constraints": [{"description": "Use deterministic interfaces"}],
                    "assumptions": ["External dependencies are reachable"],
                    "open_questions": [],
                    "search_evidence": [],
                }
            )

        if '"architecture_style"' in merged and '"components"' in merged:
            return json.dumps(
                {
                    "architecture_style": "modular_monolith",
                    "components": [
                        {"name": "CoreService", "responsibility": "Core business orchestration", "type": "service"},
                        {"name": "Database", "responsibility": "Persistence", "type": "infrastructure"},
                    ],
                    "data_flows": [{"from": "CoreService", "to": "Database", "description": "store state"}],
                    "deployment": {"strategy": "containerized", "environments": ["development", "test"]},
                    "non_functional_considerations": [{"requirement": "performance", "approach": "cache hot paths"}],
                }
            )

        if '"openapi":"3.0.0"' in merged and '"endpoints"' in merged:
            return json.dumps(
                {
                    "openapi": "3.0.0",
                    "info": {"title": "Mock API", "version": "1.0.0"},
                    "endpoints": [
                        {
                            "method": "GET",
                            "path": "/api/v1/items",
                            "description": "List items",
                            "status_codes": {"200": "Success"},
                        }
                    ],
                    "schemas": {"item": {"type": "object", "properties": {"id": {"type": "string"}}}},
                }
            )

        if '"backend":{"language"' in merged and '"ci_cd"' in merged:
            return json.dumps(
                {
                    "backend": {"language": "python", "framework": "fastapi", "justification": "test"},
                    "database": {"type": "postgresql", "justification": "test"},
                    "cache": {"type": "redis", "justification": "test"},
                    "infrastructure": {
                        "containerization": "docker",
                        "orchestration": "kubernetes",
                        "deployment": "rolling",
                        "justification": "test",
                    },
                    "testing": {"unit": "pytest", "integration": "pytest", "e2e": "pytest", "justification": "test"},
                    "ci_cd": {"platform": "github_actions", "justification": "test"},
                }
            )

        if '"architecture_requirements"' in merged and '"source_sr"' in merged:
            return json.dumps(
                {
                    "architecture_requirements": [
                        {
                            "source_sr": "SR-001",
                            "target_layer": "business",
                            "component_type": "service",
                            "description": "Implement SR-001 in business service",
                            "estimated_complexity": "medium",
                        }
                    ]
                }
            )

        if '"functions"' in merged and '"source_ar"' in merged:
            return json.dumps(
                {
                    "functions": [
                        {
                            "source_ar": "AR-SR-001-1",
                            "type": "service",
                            "name": "CoreFunctionService",
                            "description": "Execute SR workflow",
                            "layer": "business",
                            "subsystem": "core",
                            "interfaces": [{"method": "GET", "path": "/api/v1/core", "description": "Read core"}],
                            "dependencies": [],
                            "file_path": "src/business_layer/core/core_function_service.py",
                            "estimated_complexity": "medium",
                        }
                    ]
                }
            )

        if (
            "step:fn_code_generation" in str(kwargs.get("llm_purpose", ""))
            or "Return JSON object only with key: code_content." in merged
        ):
            module_match = re.search(r"Module:\s*([a-zA-Z0-9_]+)", user_text)
            module = module_match.group(1) if module_match else "operation_service"
            subsystem_match = re.search(r"Subsystem:\s*([a-zA-Z0-9_]+)", user_text)
            subsystem = subsystem_match.group(1) if subsystem_match else "subsystem"
            return json.dumps(
                {
                    "code_content": (
                        "from __future__ import annotations\n\n"
                        f"def implement_{module}(input_data: dict | None = None) -> dict[str, object]:\n"
                        "    payload = input_data or {}\n"
                        "    input_keys = sorted(payload.keys())\n"
                        "    return {\n"
                        "        'status': 'ok',\n"
                        "        'data': {'processed': True, 'input_keys': input_keys},\n"
                        "        'errors': [],\n"
                        "        'meta': {\n"
                        f"            'subsystem': '{subsystem}',\n"
                        f"            'operation': '{module}',\n"
                        "            'observed': True,\n"
                        "        },\n"
                        "    }\n"
                    )
                }
            )

        if (
            "step:fn_test_generation" in str(kwargs.get("llm_purpose", ""))
            or "Return JSON object only with key: test_content." in merged
        ):
            import_match = re.search(
                r"from src\.([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+) import implement_([a-zA-Z0-9_]+)",
                user_text,
            )
            if import_match:
                subsystem, module, func_suffix = import_match.groups()
            else:
                subsystem, module, func_suffix = "subsystem", "operation_service", "operation_service"
            return json.dumps(
                {
                    "test_content": (
                        f"from src.{subsystem}.{module} import implement_{func_suffix}\n\n\n"
                        f"def test_{module}_returns_standard_shape() -> None:\n"
                        f"    result = implement_{func_suffix}({{'value': 1}})\n"
                        "    assert result['status'] == 'ok'\n"
                        "    assert isinstance(result['data'], dict)\n"
                        "    assert isinstance(result['errors'], list)\n"
                        "    assert isinstance(result['meta'], dict)\n\n\n"
                        f"def test_{module}_meta_operation_matches_module() -> None:\n"
                        f"    result = implement_{func_suffix}()\n"
                        f"    assert result['meta']['operation'] == '{module}'\n"
                    )
                }
            )

        return "{}"

    monkeypatch.setattr(LLMClient, "complete", _fake_complete)
