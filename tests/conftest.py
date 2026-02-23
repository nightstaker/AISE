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

        if "Return keys: code_content, test_content." in merged:
            match = re.search(r"Module:\s*([a-zA-Z0-9_]+)", merged)
            module = match.group(1) if match else "feature_logic"
            return json.dumps(
                {
                    "code_content": (
                        "from __future__ import annotations\n\n"
                        f"def implement_{module}(input_data: dict | None = None) -> dict[str, object]:\n"
                        "    payload = input_data or {}\n"
                        "    return {\n"
                        "        'fn_id': 'FN-MOCK-001',\n"
                        "        'description': 'mock implementation',\n"
                        "        'status': 'implemented',\n"
                        "        'result': {'payload_keys': sorted(payload.keys())},\n"
                        "    }\n"
                    ),
                    "test_content": (
                        f"from src.services.subsystem.{module} import implement_{module}\n\n"
                        f"def test_{module}_returns_dict() -> None:\n"
                        f"    result = implement_{module}({{'k': 'v'}})\n"
                        "    assert isinstance(result, dict)\n"
                    ),
                }
            )

        return "{}"

    monkeypatch.setattr(LLMClient, "complete", _fake_complete)
