"""Consistency checks for runtime skills, docs, and SKILLS_SPEC registry."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "validate_skills_registry.py"

spec = importlib.util.spec_from_file_location("validate_skills_registry", SCRIPT_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_skill_registry_validation_passes():
    records = module.collect_runtime_skill_records()
    errors = [*module.validate_records(records), *module.validate_spec(records)]
    assert errors == []


def test_inventory_contains_expected_fields_and_count():
    records = module.collect_runtime_skill_records()
    assert len(records) == 31
    target = {r.runtime_skill_name: r for r in records}["architecture_requirement_analysis"]
    assert target.directory_name == "architecture_requirement"
    assert target.class_name == "ArchitectureRequirementSkill"
    assert target.module_path == "aise.skills.architecture_requirement"
    assert target.has_skill_md is True
    assert target.registered_agents == ("architect",)


def test_legacy_namespace_dirs_removed_or_non_source_only():
    legacy_dirs = ["pm", "architect", "developer", "qa", "lead", "manager", "github"]
    for name in legacy_dirs:
        path = ROOT / "src" / "aise" / "skills" / name
        if not path.exists():
            continue
        py_sources = [p for p in path.rglob("*.py") if p.is_file()]
        assert py_sources == [], f"Legacy namespace dir contains source files and needs manual review: {path}"
