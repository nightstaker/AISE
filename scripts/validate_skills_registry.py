#!/usr/bin/env python3
"""Validate runtime skills, agent registrations, docs, and SKILLS_SPEC.md consistency."""

from __future__ import annotations

import argparse
import ast
import importlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

ROLE_DIR_EXCLUDES = {"__pycache__", "pm", "architect", "developer", "qa", "lead", "manager", "github"}
DIR_TO_RUNTIME_NAME_EXCEPTIONS = {"architecture_requirement": "architecture_requirement_analysis"}
DOC_BANNED_MARKERS = ("TODO", "TBD")


@dataclass(frozen=True)
class SkillRecord:
    directory_name: str
    runtime_skill_name: str
    class_name: str
    module_path: str
    registered_agents: tuple[str, ...]
    has_skill_md: bool
    script_entry_path: str


@dataclass(frozen=True)
class SpecRow:
    skill_name: str
    agents: tuple[str, ...]
    phase: str
    class_name: str
    module_path: str


AGENT_FILE_TO_NAME = {
    "architect.py": "architect",
    "developer.py": "developer",
    "product_manager.py": "product_manager",
    "project_manager.py": "project_manager",
    "qa_engineer.py": "qa_engineer",
    "rd_director.py": "rd_director",
    "reviewer.py": "reviewer",
}


def _iter_agent_files() -> Iterable[Path]:
    for path in sorted((ROOT / "src" / "aise" / "agents").glob("*.py")):
        if path.name in AGENT_FILE_TO_NAME:
            yield path


def parse_agent_registrations() -> dict[str, set[str]]:
    registrations: dict[str, set[str]] = {}
    for path in _iter_agent_files():
        agent_name = AGENT_FILE_TO_NAME[path.name]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "register_skill":
                continue
            if not node.args:
                continue
            arg0 = node.args[0]
            if isinstance(arg0, ast.Call) and isinstance(arg0.func, ast.Name):
                classes.add(arg0.func.id)
        registrations[agent_name] = classes
    return registrations


def collect_runtime_skill_records() -> list[SkillRecord]:
    import aise.skills as skills  # pylint: disable=import-error

    registrations = parse_agent_registrations()
    class_to_agents: dict[str, list[str]] = {}
    for agent, classes in registrations.items():
        for class_name in classes:
            class_to_agents.setdefault(class_name, []).append(agent)

    records: list[SkillRecord] = []
    for class_name in skills.__all__:
        cls = getattr(skills, class_name)
        obj = cls()
        module = cls.__module__
        package_module = module.rsplit(".scripts.", 1)[0] if ".scripts." in module else module
        directory_name = package_module.split(".")[-1]
        skill_dir = ROOT / "src" / "aise" / "skills" / directory_name
        script_entry = skill_dir / "scripts" / f"{directory_name}.py"
        records.append(
            SkillRecord(
                directory_name=directory_name,
                runtime_skill_name=obj.name,
                class_name=class_name,
                module_path=package_module,
                registered_agents=tuple(sorted(class_to_agents.get(class_name, []))),
                has_skill_md=(skill_dir / "skill.md").exists(),
                script_entry_path=str(script_entry.relative_to(ROOT)),
            )
        )
    return sorted(records, key=lambda r: r.runtime_skill_name)


def parse_skills_spec_index() -> dict[str, SpecRow]:
    spec_path = ROOT / "SKILLS_SPEC.md"
    lines = spec_path.read_text(encoding="utf-8").splitlines()
    in_index = False
    rows: dict[str, SpecRow] = {}
    for line in lines:
        if line.strip() == "## Skill Index":
            in_index = True
            continue
        if in_index and line.startswith("## "):
            break
        if not in_index or not line.startswith("| SK-"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) != 6:
            raise ValueError(f"Unexpected Skill Index row format: {line}")
        _, skill_name, agents, phase, class_name, module_path = cols
        skill_name = skill_name.strip("`")
        class_name = class_name.strip("`")
        module_path = module_path.strip("`")
        agent_parts = tuple(sorted(a.strip() for a in agents.split(",") if a.strip()))
        rows[skill_name] = SpecRow(
            skill_name=skill_name,
            agents=agent_parts,
            phase=phase,
            class_name=class_name,
            module_path=module_path,
        )
    return rows


def _doc_has_min_sections(text: str) -> bool:
    if not text.lstrip().startswith("# Skill:"):
        return False
    required_patterns = [r"^##\s+Input\b", r"^##\s+Output\b", r"(##\s+Dependencies\b|###\s+Depends On\b)"]
    return all(re.search(p, text, flags=re.MULTILINE) for p in required_patterns)


def _doc_has_example(text: str) -> bool:
    return ("```json" in text) or bool(re.search(r"example", text, flags=re.IGNORECASE))


def validate_records(records: list[SkillRecord]) -> list[str]:
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_classes: set[str] = set()
    for rec in records:
        if rec.runtime_skill_name in seen_names:
            errors.append(f"Duplicate runtime skill name: {rec.runtime_skill_name}")
        seen_names.add(rec.runtime_skill_name)
        if rec.class_name in seen_classes:
            errors.append(f"Duplicate class export: {rec.class_name}")
        seen_classes.add(rec.class_name)

        skill_dir = ROOT / "src" / "aise" / "skills" / rec.directory_name
        required_paths = [
            skill_dir / "__init__.py",
            skill_dir / "skill.md",
            skill_dir / "scripts" / f"{rec.directory_name}.py",
        ]
        for path in required_paths:
            if not path.exists():
                errors.append(f"Missing required skill path for {rec.runtime_skill_name}: {path.relative_to(ROOT)}")

        expected_runtime = DIR_TO_RUNTIME_NAME_EXCEPTIONS.get(rec.directory_name, rec.directory_name)
        if rec.runtime_skill_name != expected_runtime:
            errors.append(
                "Directory/runtime mismatch for "
                f"{rec.directory_name}: runtime={rec.runtime_skill_name}, "
                f"expected={expected_runtime}"
            )

        if not rec.registered_agents:
            errors.append(f"Skill is exported but not registered by any agent: {rec.runtime_skill_name}")

        try:
            cls = getattr(importlib.import_module("aise.skills"), rec.class_name)
            inst = cls()
            if not str(getattr(inst, "description", "")).strip():
                errors.append(f"Empty description on skill class: {rec.class_name}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"Failed to instantiate {rec.class_name}: {type(exc).__name__}: {exc}")

        doc_text = (skill_dir / "skill.md").read_text(encoding="utf-8")
        if any(marker in doc_text for marker in DOC_BANNED_MARKERS):
            errors.append(f"Banned placeholder marker in {skill_dir / 'skill.md'}")
        if not _doc_has_min_sections(doc_text):
            errors.append(f"skill.md missing minimum sections for {rec.runtime_skill_name}")
        if not _doc_has_example(doc_text):
            errors.append(f"skill.md missing example block/text for {rec.runtime_skill_name}")

    # Agent registrations should not reference unknown exports
    exported_classes = {r.class_name for r in records}
    for agent, class_names in parse_agent_registrations().items():
        for class_name in class_names:
            if class_name not in exported_classes:
                errors.append(f"Agent {agent} registers non-exported skill class: {class_name}")
    return errors


def validate_spec(records: list[SkillRecord]) -> list[str]:
    errors: list[str] = []
    spec_rows = parse_skills_spec_index()
    runtime_by_name = {r.runtime_skill_name: r for r in records}

    missing = sorted(set(runtime_by_name) - set(spec_rows))
    extra = sorted(set(spec_rows) - set(runtime_by_name))
    if missing:
        errors.append(f"SKILLS_SPEC.md missing skills in Skill Index: {missing}")
    if extra:
        errors.append(f"SKILLS_SPEC.md has unknown skills in Skill Index: {extra}")

    for name, rec in runtime_by_name.items():
        row = spec_rows.get(name)
        if not row:
            continue
        if row.class_name != rec.class_name:
            errors.append(f"Spec class mismatch for {name}: {row.class_name} != {rec.class_name}")
        if row.module_path != rec.module_path:
            errors.append(f"Spec module mismatch for {name}: {row.module_path} != {rec.module_path}")
        if tuple(sorted(row.agents)) != tuple(sorted(rec.registered_agents)):
            errors.append(
                f"Spec agents mismatch for {name}: {row.agents} != {rec.registered_agents}"
            )
    return errors


def print_inventory(records: list[SkillRecord]) -> None:
    print("directory_name\truntime_skill_name\tclass_name\tmodule_path\tregistered_agents\thas_skill_md\tscript_entry_path")
    for rec in records:
        print(
            "\t".join(
                [
                    rec.directory_name,
                    rec.runtime_skill_name,
                    rec.class_name,
                    rec.module_path,
                    ",".join(rec.registered_agents),
                    str(rec.has_skill_md).lower(),
                    rec.script_entry_path,
                ]
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Print runtime skill inventory table")
    args = parser.parse_args()

    records = collect_runtime_skill_records()
    if args.inventory:
        print_inventory(records)

    errors = []
    errors.extend(validate_records(records))
    errors.extend(validate_spec(records))

    if errors:
        print("Skill registry validation FAILED", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        return 1

    print(f"Skill registry validation passed ({len(records)} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
