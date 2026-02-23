"""Deep architecture workflow skill with paired architecture subagents."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class DeepArchitectureWorkflowSkill(Skill):
    """Run deep architecture workflow and generate traceable architecture artifacts."""

    @property
    def name(self) -> str:
        return "deep_architecture_workflow"

    @property
    def description(self) -> str:
        return (
            "Run Architecture Designer, Architecture Reviewer, and Subsystem Architect "
            "workflow to generate system-architecture and subsystem design docs "
            "with code scaffolding"
        )

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        project_name = context.project_name or str(input_data.get("project_name", "Untitled")).strip() or "Untitled"
        project_root = self._resolve_project_root(context)
        docs_dir = self._resolve_docs_dir(input_data, context)
        src_dir = self._resolve_src_dir(input_data, context)
        docs_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(parents=True, exist_ok=True)

        product_design = self._load_product_design(context, docs_dir)
        system_requirements = self._load_system_requirements(context, docs_dir)
        if not system_requirements:
            system_requirements = self._fallback_requirements_from_product_design(product_design)

        # Step 1: architecture design + reviewer loop.
        architecture_rounds = self._run_architecture_review_rounds(
            context=context,
            product_design=product_design,
            system_requirements=system_requirements,
            min_rounds=2,
        )
        architecture_design = architecture_rounds[-1]["architecture_design"]

        # Step 2: initialize top-level source structure and API definitions.
        bootstrap_files: list[str] = self._initialize_top_level_code(
            src_dir=src_dir,
            architecture_design=architecture_design,
        )

        # Step 3: split subsystem tasks, assign reviewer/architect instances.
        assignments = self._build_subsystem_assignments(architecture_design)

        # Step 4: per-subsystem detailed design + reviewer loop.
        detail_designs: dict[str, dict[str, Any]] = {}
        detail_rounds: dict[str, list[dict[str, Any]]] = {}
        for subsystem in architecture_design.get("subsystems", []):
            rounds = self._run_subsystem_detail_rounds(
                context=context,
                subsystem=subsystem,
                system_requirements=system_requirements,
                architecture_design=architecture_design,
                assignment=assignments.get(subsystem.get("id", ""), {}),
                min_rounds=2,
            )
            detail_rounds[str(subsystem.get("id", ""))] = rounds
            detail_designs[str(subsystem.get("id", ""))] = rounds[-1]["detail_design"]

        # Step 5: initialize per-subsystem code and API contracts.
        subsystem_scaffold_files: list[str] = self._initialize_subsystem_code(
            src_dir=src_dir,
            architecture_design=architecture_design,
            detail_designs=detail_designs,
        )

        architecture_doc_path = docs_dir / "system-architecture.md"
        architecture_doc_path.write_text(
            self._render_system_architecture_doc(
                project_name=project_name,
                product_design=product_design,
                system_requirements=system_requirements,
                architecture_design=architecture_design,
                rounds=architecture_rounds,
                assignments=assignments,
            ),
            encoding="utf-8",
        )

        detail_doc_paths: list[Path] = []
        for subsystem in architecture_design.get("subsystems", []):
            subsystem_id = str(subsystem.get("id", ""))
            detail = detail_designs.get(subsystem_id, {})
            rounds = detail_rounds.get(subsystem_id, [])
            file_name = f"{self._slugify(str(subsystem.get('name', subsystem_id)))}-detail-design.md"
            path = docs_dir / file_name
            path.write_text(
                self._render_subsystem_detail_doc(
                    project_name=project_name,
                    subsystem=subsystem,
                    architecture_design=architecture_design,
                    system_requirements=system_requirements,
                    detail_design=detail,
                    rounds=rounds,
                ),
                encoding="utf-8",
            )
            detail_doc_paths.append(path)

        api_contract = self._build_api_contract(architecture_design)
        tech_stack = {
            "implementation_language": "to_be_determined",
            "runtime_framework": "to_be_determined",
            "data_storage": "to_be_determined",
            "deployment_model": "to_be_determined",
        }
        architecture_requirements = self._build_architecture_requirements(
            architecture_design=architecture_design,
            system_requirements=system_requirements,
        )
        functional_design = self._build_functional_design(detail_designs)

        architecture_artifact = Artifact(
            artifact_type=ArtifactType.ARCHITECTURE_DESIGN,
            content={
                "project_name": project_name,
                "design_goals": architecture_design.get("design_goals", []),
                "principles": architecture_design.get("principles", []),
                "architecture_overview": architecture_design.get("architecture_overview", ""),
                "architecture_diagram": architecture_design.get("architecture_diagram", ""),
                "components": architecture_design.get("components", []),
                "subsystems": architecture_design.get("subsystems", []),
                "sr_allocation": architecture_design.get("sr_allocation", {}),
            },
            producer="architecture_designer",
            metadata={
                "project_name": project_name,
                "subagent": "architecture_designer",
                "step": "step1",
            },
        )
        context.artifact_store.store(architecture_artifact)

        api_artifact = Artifact(
            artifact_type=ArtifactType.API_CONTRACT,
            content=api_contract,
            producer="architecture_designer",
            metadata={"project_name": project_name, "step": "step2"},
        )
        context.artifact_store.store(api_artifact)

        tech_stack_artifact = Artifact(
            artifact_type=ArtifactType.TECH_STACK,
            content=tech_stack,
            producer="architecture_designer",
            metadata={"project_name": project_name, "step": "step2"},
        )
        context.artifact_store.store(tech_stack_artifact)

        architecture_requirement_artifact = Artifact(
            artifact_type=ArtifactType.ARCHITECTURE_REQUIREMENT,
            content=architecture_requirements,
            producer="architecture_designer",
            metadata={"project_name": project_name, "step": "step4"},
        )
        context.artifact_store.store(architecture_requirement_artifact)

        functional_design_artifact = Artifact(
            artifact_type=ArtifactType.FUNCTIONAL_DESIGN,
            content=functional_design,
            producer="subsystem_architect",
            metadata={"project_name": project_name, "step": "step4"},
        )
        context.artifact_store.store(functional_design_artifact)

        status_tracking_artifact = Artifact(
            artifact_type=ArtifactType.STATUS_TRACKING,
            content={
                "workflow": "deep_architecture_workflow",
                "step1_rounds": len(architecture_rounds),
                "step4_subsystems": len(detail_designs),
                "step4_rounds_each": {sid: len(rounds) for sid, rounds in detail_rounds.items()},
                "bootstrap_files": bootstrap_files,
                "subsystem_scaffold_files": subsystem_scaffold_files,
            },
            producer="architect",
            metadata={"project_name": project_name, "step": "status"},
        )
        context.artifact_store.store(status_tracking_artifact)

        review_artifact = Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "workflow": "deep_architecture_workflow",
                "architecture_reviews": [round_item.get("review", {}) for round_item in architecture_rounds],
                "subsystem_reviews": {
                    sid: [round_item.get("review", {}) for round_item in rounds]
                    for sid, rounds in detail_rounds.items()
                },
            },
            producer="architecture_reviewer",
            metadata={"project_name": project_name},
        )
        context.artifact_store.store(review_artifact)

        generated_docs = [str(architecture_doc_path), *[str(path) for path in detail_doc_paths]]
        generated_sources = [*bootstrap_files, *subsystem_scaffold_files]

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "workflow": "deep_architecture_workflow",
                "project_name": project_name,
                "project_root": str(project_root) if project_root else "",
                "sub_agents": [
                    "architecture_designer",
                    "architecture_reviewer[*]",
                    "subsystem_architect[*]",
                ],
                "steps": {
                    "step1": {
                        "name": "architecture_design_review_loop",
                        "status": "completed",
                        "rounds": len(architecture_rounds),
                    },
                    "step2": {
                        "name": "bootstrap_source_structure",
                        "status": "completed",
                        "files": bootstrap_files,
                        "skipped": False,
                    },
                    "step3": {
                        "name": "subsystem_task_split",
                        "status": "completed",
                        "assignments": assignments,
                    },
                    "step4": {
                        "name": "subsystem_detail_design_review_loop",
                        "status": "completed",
                        "subsystems": list(detail_designs.keys()),
                    },
                    "step5": {
                        "name": "subsystem_source_initialization",
                        "status": "completed",
                        "files": subsystem_scaffold_files,
                        "skipped": False,
                    },
                },
                "generated_docs": generated_docs,
                "generated_sources": generated_sources,
                "artifact_ids": {
                    "architecture_design": architecture_artifact.id,
                    "api_contract": api_artifact.id,
                    "tech_stack": tech_stack_artifact.id,
                    "architecture_requirement": architecture_requirement_artifact.id,
                    "functional_design": functional_design_artifact.id,
                    "review_feedback": review_artifact.id,
                    "status_tracking": status_tracking_artifact.id,
                },
            },
            producer="architect",
            metadata={"project_name": project_name},
        )

    def _load_product_design(self, context: SkillContext, docs_dir: Path) -> dict[str, Any]:
        artifact = context.artifact_store.get_latest(ArtifactType.SYSTEM_DESIGN)
        if artifact and isinstance(artifact.content, dict):
            return artifact.content
        path = docs_dir / "system-design.md"
        if not path.exists():
            return {"overview": "", "system_features": []}
        content = path.read_text(encoding="utf-8")
        features: list[dict[str, Any]] = []
        for idx, line in enumerate(content.splitlines(), start=1):
            if line.strip().startswith("### SF-"):
                section = line.strip().lstrip("# ")
                sf_id = section.split(" ", 1)[0]
                features.append(
                    {
                        "id": sf_id,
                        "name": section,
                        "goal": section,
                        "functions": ["Referenced from product design markdown"],
                    }
                )
            if len(features) >= 12:
                break
        return {
            "overview": "Loaded from docs/system-design.md",
            "system_features": features,
            "all_features": features,
        }

    def _load_system_requirements(self, context: SkillContext, docs_dir: Path) -> dict[str, Any]:
        artifact = context.artifact_store.get_latest(ArtifactType.SYSTEM_REQUIREMENTS)
        if artifact and isinstance(artifact.content, dict):
            requirements = artifact.content.get("requirements")
            if isinstance(requirements, list):
                return artifact.content

        path = docs_dir / "system-requirements.md"
        if not path.exists():
            return {"requirements": []}

        requirements: list[dict[str, Any]] = []
        lines = path.read_text(encoding="utf-8").splitlines()
        current: dict[str, Any] | None = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("### SR-"):
                if current:
                    requirements.append(current)
                title = stripped.lstrip("# ")
                sr_id = title.split(" ", 1)[0]
                current = {
                    "id": sr_id,
                    "title": title,
                    "requirement_overview": title,
                    "scenario": "",
                    "users": ["End User"],
                    "interaction_process": [],
                    "expected_result": "",
                    "spec_targets": [],
                    "constraints": [],
                }
            elif current and stripped.startswith("- Scenario:"):
                current["scenario"] = stripped.removeprefix("- Scenario:").strip()
            elif current and stripped.startswith("- Requirement Overview:"):
                current["requirement_overview"] = stripped.removeprefix("- Requirement Overview:").strip()
        if current:
            requirements.append(current)

        return {"requirements": requirements}

    def _fallback_requirements_from_product_design(
        self,
        product_design: dict[str, Any],
    ) -> dict[str, Any]:
        requirements: list[dict[str, Any]] = []
        features = product_design.get("system_features", [])
        for idx, feature in enumerate(features or [], start=1):
            requirements.append(
                {
                    "id": f"SR-{idx:03d}",
                    "title": feature.get("name", f"Requirement {idx}"),
                    "requirement_overview": feature.get("goal", feature.get("name", "")),
                    "scenario": f"Deliver {feature.get('name', f'feature {idx}')} end-to-end.",
                    "users": ["End User", "Ops"],
                    "interaction_process": [
                        "Client sends request",
                        "Subsystem handles business logic",
                        "System returns response",
                    ],
                    "expected_result": feature.get("goal", "Feature is delivered"),
                    "spec_targets": ["P95 <= 300ms", "Availability >= 99.9%"],
                    "constraints": [],
                }
            )
        return {"requirements": requirements}

    def _run_architecture_review_rounds(
        self,
        *,
        context: SkillContext,
        product_design: dict[str, Any],
        system_requirements: dict[str, Any],
        min_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_design: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None
        total_rounds = max(2, min_rounds)

        for round_index in range(1, total_rounds + 1):
            design = self._designer_build_architecture_design(
                context=context,
                product_design=product_design,
                system_requirements=system_requirements,
                previous_design=previous_design,
                previous_review=previous_review,
                round_index=round_index,
            )
            review = self._review_architecture_design(
                context=context,
                system_requirements=system_requirements,
                architecture_design=design,
                round_index=round_index,
                reviewer_instances=["architecture_reviewer_1", "architecture_reviewer_2"],
            )
            rounds.append({"round": round_index, "architecture_design": design, "review": review})
            previous_design = design
            previous_review = review
        return rounds

    def _designer_build_architecture_design(
        self,
        *,
        context: SkillContext,
        product_design: dict[str, Any],
        system_requirements: dict[str, Any],
        previous_design: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
    ) -> dict[str, Any]:
        requirements = self._normalize_requirements(system_requirements.get("requirements", []))
        subsystems = previous_design.get("subsystems", []) if previous_design else []
        if not subsystems:
            subsystems = self._build_subsystems(requirements)

        sr_allocation = self._allocate_srs_to_subsystems(requirements, subsystems)
        components = self._build_components(subsystems, sr_allocation)

        if previous_review and previous_review.get("issues"):
            feedback = " | ".join(str(issue) for issue in previous_review.get("issues", [])[:3])
            for subsystem in subsystems:
                if feedback:
                    subsystem.setdefault("constraints", [])
                    if feedback not in subsystem["constraints"]:
                        subsystem["constraints"].append(feedback)

        feature_count = len(product_design.get("system_features", []))
        llm_design = self._run_llm_json(
            context=context,
            purpose="subagent:architecture_designer step:architecture_design",
            system_prompt=(
                "You are an architecture designer. Return JSON only with optional keys: "
                "design_goals (list[str]), principles (list[str]), architecture_overview (str), "
                "architecture_diagram (str), layering (list[str])."
            ),
            user_prompt=(
                f"Round: {round_index}\n"
                f"Requirement count: {len(requirements)}\n"
                f"Feature count: {feature_count}\n"
                "Product design document:\n"
                f"{self._compact_json(product_design)}\n\n"
                "Current architecture design document:\n"
                f"{self._build_current_architecture_context(previous_design, previous_review)}\n"
            ),
        )
        design_goals = self._as_str_list(
            llm_design.get("design_goals"),
            fallback=[
                "Deliver a traceable architecture from SR to subsystem/component.",
                "Keep API boundaries explicit and implementable.",
                "Prepare subsystem-level detailed design and coding bootstrap.",
            ],
        )
        principles = self._as_str_list(
            llm_design.get("principles"),
            fallback=[
                "Clear separation of concerns",
                "API-first contract design",
                "Traceability from SR to implementation units",
                "Operational observability by default",
            ],
        )
        layering = self._as_str_list(
            llm_design.get("layering"),
            fallback=["System Layer", "Subsystem Layer", "Component/Service Layer"],
        )
        return {
            "round": round_index,
            "design_goals": design_goals,
            "principles": principles,
            "architecture_overview": str(llm_design.get("architecture_overview", "")).strip()
            or f"Architecture derived from {len(requirements)} SR items and {feature_count} product feature items.",
            "architecture_diagram": str(llm_design.get("architecture_diagram", "")).strip()
            or "Client -> API Gateway -> Application Service Layer -> Domain Services -> Persistence/Infrastructure",
            "layering": layering,
            "subsystems": subsystems,
            "components": components,
            "sr_allocation": sr_allocation,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _review_architecture_design(
        self,
        *,
        context: SkillContext,
        system_requirements: dict[str, Any],
        architecture_design: dict[str, Any],
        round_index: int,
        reviewer_instances: list[str],
    ) -> dict[str, Any]:
        issues: list[str] = []
        requirements = self._normalize_requirements(system_requirements.get("requirements", []))
        subsystems = architecture_design.get("subsystems", [])
        allocation = architecture_design.get("sr_allocation", {})

        if not subsystems:
            issues.append("No subsystems defined in architecture design.")

        assigned: set[str] = set()
        for subsystem_id, sr_ids in allocation.items():
            for sr_id in sr_ids:
                assigned.add(str(sr_id))
            if not sr_ids:
                issues.append(f"Subsystem {subsystem_id} has no SR allocation.")

        required_ids = {str(item.get("id", "")) for item in requirements if str(item.get("id", "")).strip()}
        missing = sorted(sr_id for sr_id in required_ids if sr_id not in assigned)
        if missing:
            issues.append(f"Unallocated SR items: {', '.join(missing)}")

        for subsystem in subsystems:
            if not subsystem.get("apis"):
                issues.append(f"{subsystem.get('id', 'SUBSYS')} missing API design entries.")

        approved = round_index >= 2 and not issues
        if round_index == 1 and not issues:
            issues.append("Round 1 requires at least one refinement pass before approval.")
            approved = False
        llm_review = self._run_llm_json(
            context=context,
            purpose="subagent:architecture_reviewer step:architecture_review",
            system_prompt=(
                "You are an architecture reviewer. Return JSON only with optional keys: "
                "summary (str), suggestions (list[str])."
            ),
            user_prompt=(f"Round: {round_index}\nCurrent issues:\n- " + "\n- ".join(issues or ["(none)"]) + "\n"),
        )

        return {
            "reviewer_instances": reviewer_instances,
            "approved": approved,
            "decision": "approve" if approved else "revise",
            "summary": str(llm_review.get("summary", "")).strip()
            or ("Architecture accepted" if approved else "Architecture requires revision"),
            "issues": issues,
            "suggestions": self._as_str_list(
                llm_review.get("suggestions"),
                fallback=[
                    "Ensure every SR is mapped to exactly one primary subsystem.",
                    "Provide API contract examples for each subsystem.",
                    "Capture reviewer feedback and designer responses in revision history.",
                ],
            ),
        }

    def _initialize_top_level_code(
        self,
        *,
        src_dir: Path,
        architecture_design: dict[str, Any],
    ) -> list[str]:
        files: list[str] = []
        (src_dir / "services").mkdir(parents=True, exist_ok=True)
        app_file = src_dir / "main.py"
        subsystem_modules = [
            self._slugify(str(subsystem.get("name", subsystem.get("id", "service"))))
            for subsystem in architecture_design.get("subsystems", [])
        ]
        include_contract_lines = []
        for module in subsystem_modules:
            include_contract_lines.extend(
                [
                    f"    from .services.{module}.api import build_contract as {module}_contract",
                    f"    contracts.extend({module}_contract())",
                ]
            )

        include_contract_block = "\n".join(include_contract_lines)
        app_file.write_text(
            (
                "from __future__ import annotations\n\n"
                "def build_application_manifest() -> dict[str, object]:\n"
                "    contracts: list[dict[str, object]] = []\n"
                f"{include_contract_block}\n"
                "    return {\n"
                "        'name': 'aise_generated_application',\n"
                "        'version': '0.1.0',\n"
                "        'status': 'ready',\n"
                "        'contracts': contracts,\n"
                "    }\n\n\n"
                "APPLICATION_MANIFEST = build_application_manifest()\n"
            ),
            encoding="utf-8",
        )
        files.append(str(app_file))

        index_file = src_dir / "services" / "__init__.py"
        index_file.write_text("# generated by deep_architecture_workflow\n", encoding="utf-8")
        files.append(str(index_file))

        api_index = src_dir / "api_contracts.md"
        lines = ["# API Contracts", "", "Generated from architecture subsystems.", ""]
        for subsystem in architecture_design.get("subsystems", []):
            lines.append(f"## {subsystem.get('id', '')} {subsystem.get('name', '')}")
            for api in subsystem.get("apis", []):
                lines.append(f"- `{api.get('method', 'GET')} {api.get('path', '/')}`: {api.get('description', '')}")
            lines.append("")
        api_index.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        files.append(str(api_index))
        return files

    def _build_subsystem_assignments(
        self,
        architecture_design: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        assignments: dict[str, dict[str, Any]] = {}
        reviewer_pool = ["architecture_reviewer_1", "architecture_reviewer_2"]
        architect_pool = ["subsystem_architect_1", "subsystem_architect_2", "subsystem_architect_3"]

        subsystems = architecture_design.get("subsystems", [])
        for index, subsystem in enumerate(subsystems):
            subsystem_id = str(subsystem.get("id", f"SUBSYS-{index + 1:02d}"))
            assignments[subsystem_id] = {
                "subsystem_architect": architect_pool[index % len(architect_pool)],
                "architecture_reviewer": reviewer_pool[index % len(reviewer_pool)],
                "subsystem": subsystem.get("name", subsystem_id),
                "assigned_sr_ids": architecture_design.get(
                    "sr_allocation",
                    {},
                ).get(subsystem_id, []),
            }
        return assignments

    def _run_subsystem_detail_rounds(
        self,
        *,
        context: SkillContext,
        subsystem: dict[str, Any],
        system_requirements: dict[str, Any],
        architecture_design: dict[str, Any],
        assignment: dict[str, Any],
        min_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_design: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None
        total_rounds = max(2, min_rounds)

        for round_index in range(1, total_rounds + 1):
            detail_design = self._subsystem_architect_design(
                context=context,
                subsystem=subsystem,
                system_requirements=system_requirements,
                architecture_design=architecture_design,
                assignment=assignment,
                previous_design=previous_design,
                previous_review=previous_review,
                round_index=round_index,
            )
            review = self._review_subsystem_detail(
                context=context,
                subsystem=subsystem,
                detail_design=detail_design,
                round_index=round_index,
                reviewer=str(assignment.get("architecture_reviewer", "architecture_reviewer_1")),
            )
            rounds.append({"round": round_index, "detail_design": detail_design, "review": review})
            previous_design = detail_design
            previous_review = review
        return rounds

    def _subsystem_architect_design(
        self,
        *,
        context: SkillContext,
        subsystem: dict[str, Any],
        system_requirements: dict[str, Any],
        architecture_design: dict[str, Any],
        assignment: dict[str, Any],
        previous_design: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
    ) -> dict[str, Any]:
        sr_ids = [str(sr_id) for sr_id in assignment.get("assigned_sr_ids", [])]
        sr_items = [
            item
            for item in self._normalize_requirements(system_requirements.get("requirements", []))
            if str(item.get("id", "")) in sr_ids
        ]
        if not sr_items:
            sr_items = self._normalize_requirements(system_requirements.get("requirements", []))[:1]

        components = previous_design.get("components", []) if previous_design else []
        if not components:
            components = self._build_subsystem_components(subsystem)

        fn_items = self._build_fn_items(sr_items, components)
        if previous_review and previous_review.get("issues"):
            comment = " | ".join(str(i) for i in previous_review.get("issues", [])[:2])
            for fn in fn_items:
                fn.setdefault("notes", [])
                if comment:
                    fn["notes"].append(f"Reviewer focus: {comment}")
        llm_detail = self._run_llm_json(
            context=context,
            purpose="subagent:subsystem_architect step:subsystem_detail_design",
            system_prompt=(
                "You are a subsystem architect. Return JSON only with optional keys: "
                "logic_architecture_goals (list[str]), design_strategy (list[str]), "
                "technology_choices (object with language/framework/storage)."
            ),
            user_prompt=(
                f"Subsystem: {subsystem.get('id', '')} {subsystem.get('name', '')}\n"
                f"Round: {round_index}\n"
                f"Assigned SR IDs: {', '.join(sr_ids)}\n"
            ),
        )

        return {
            "round": round_index,
            "subsystem": subsystem.get("name", subsystem.get("id", "")),
            "owner": assignment.get("subsystem_architect", "subsystem_architect_1"),
            "logic_architecture_goals": self._as_str_list(
                llm_detail.get("logic_architecture_goals"),
                fallback=[
                    f"Ensure subsystem {subsystem.get('name', '')} delivers assigned SR with clear service split.",
                    "Keep interfaces stable and testable.",
                ],
            ),
            "design_strategy": self._as_str_list(
                llm_detail.get("design_strategy"),
                fallback=[
                    "Decompose by domain capability",
                    "Encapsulate storage and integration concerns",
                    "API-first for component boundaries",
                ],
            ),
            "components": components,
            "apis": subsystem.get("apis", []),
            "technology_choices": self._normalize_technology_choices(llm_detail.get("technology_choices")),
            "sr_breakdown": [
                {
                    "sr_id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "functions": [fn for fn in fn_items if fn.get("source_sr") == item.get("id", "")],
                }
                for item in sr_items
            ],
            "designer_response": self._build_designer_response(previous_review),
            "architecture_reference": architecture_design.get("architecture_overview", ""),
        }

    def _review_subsystem_detail(
        self,
        *,
        context: SkillContext,
        subsystem: dict[str, Any],
        detail_design: dict[str, Any],
        round_index: int,
        reviewer: str,
    ) -> dict[str, Any]:
        issues: list[str] = []
        breakdown = detail_design.get("sr_breakdown", [])
        if not breakdown:
            issues.append("No SR breakdown found for subsystem detail design.")

        for sr_item in breakdown:
            fns = sr_item.get("functions", [])
            if not fns:
                issues.append(f"{sr_item.get('sr_id', 'SR-UNKNOWN')} has no FN decomposition.")
            for fn in fns:
                if not fn.get("description"):
                    issues.append(f"{fn.get('id', 'FN-UNKNOWN')} missing description.")
                if not fn.get("spec"):
                    issues.append(f"{fn.get('id', 'FN-UNKNOWN')} missing specification.")

        approved = round_index >= 2 and not issues
        if round_index == 1 and not issues:
            issues.append("Round 1 requires at least one revision response.")
            approved = False
        llm_review = self._run_llm_json(
            context=context,
            purpose="subagent:architecture_reviewer step:subsystem_detail_review",
            system_prompt=(
                "You are an architecture reviewer. Return JSON only with optional keys: "
                "summary (str), suggestions (list[str])."
            ),
            user_prompt=(
                f"Subsystem: {subsystem.get('id', '')} {subsystem.get('name', '')}\n"
                f"Round: {round_index}\n"
                f"Issues:\n- " + "\n- ".join(issues or ["(none)"]) + "\n"
            ),
        )

        return {
            "reviewer": reviewer,
            "approved": approved,
            "decision": "approve" if approved else "revise",
            "summary": str(llm_review.get("summary", "")).strip()
            or (
                f"{subsystem.get('name', subsystem.get('id', 'subsystem'))} detail design approved"
                if approved
                else "Detail design requires revision"
            ),
            "issues": issues,
            "suggestions": self._as_str_list(
                llm_review.get("suggestions"),
                fallback=[
                    "Ensure each SR maps to one or more component-level FN entries.",
                    "Keep FN specification concrete enough for developers.",
                ],
            ),
        }

    def _initialize_subsystem_code(
        self,
        *,
        src_dir: Path,
        architecture_design: dict[str, Any],
        detail_designs: dict[str, dict[str, Any]],
    ) -> list[str]:
        files: list[str] = []
        for subsystem in architecture_design.get("subsystems", []):
            subsystem_id = str(subsystem.get("id", ""))
            module_name = self._slugify(str(subsystem.get("name", subsystem_id)))
            subsystem_dir = src_dir / "services" / module_name
            subsystem_dir.mkdir(parents=True, exist_ok=True)

            init_path = subsystem_dir / "__init__.py"
            init_path.write_text("# generated subsystem package\n", encoding="utf-8")
            files.append(str(init_path))

            api_prefix = f"/api/v1/{module_name}"

            schemas_path = subsystem_dir / "schemas.py"
            schemas_path.write_text(
                (
                    "from __future__ import annotations\n\n"
                    "from dataclasses import dataclass, field\n\n\n"
                    "@dataclass(slots=True)\n"
                    "class OperationRequest:\n"
                    "    session_id: str = 'default-session'\n"
                    "    payload: dict[str, object] = field(default_factory=dict)\n\n\n"
                    "@dataclass(slots=True)\n"
                    "class OperationResponse:\n"
                    "    subsystem: str\n"
                    "    operation: str\n"
                    "    accepted: bool\n"
                    "    detail: str\n"
                    "    state: dict[str, object] = field(default_factory=dict)\n"
                ),
                encoding="utf-8",
            )
            files.append(str(schemas_path))

            service_path = subsystem_dir / "service.py"
            service_lines = [
                "from __future__ import annotations",
                "",
                "from .schemas import OperationRequest, OperationResponse",
                "",
                "",
                "def health_check() -> dict[str, str]:",
                "    return {'status': 'ok'}",
                "",
            ]
            for index, api in enumerate(subsystem.get("apis", []), start=1):
                method = str(api.get("method", "GET")).lower()
                raw_path = str(api.get("path", f"{api_prefix}/action_{index}")).replace("'", "")
                normalized_path = self._normalize_router_path(raw_path, prefix=api_prefix)
                operation_name = self._extract_operation_name(normalized_path, fallback=f"action_{index}")
                if method == "get" and operation_name == "health":
                    continue
                handler_name = f"handle_{operation_name}"
                service_lines.extend(
                    [
                        f"def {handler_name}(request: OperationRequest) -> OperationResponse:",
                        f"    detail = 'processed {operation_name} for session ' + request.session_id",
                        "    state = {",
                        "        'payload_keys': sorted(request.payload.keys()),",
                        f"        'operation': '{operation_name}',",
                        "    }",
                        "    return OperationResponse(",
                        f"        subsystem='{module_name}',",
                        f"        operation='{operation_name}',",
                        "        accepted=True,",
                        "        detail=detail,",
                        "        state=state,",
                        "    )",
                        "",
                    ]
                )
            if len(service_lines) <= 8:
                service_lines.extend(
                    [
                        "def handle_action(request: OperationRequest) -> OperationResponse:",
                        "    return OperationResponse(",
                        f"        subsystem='{module_name}',",
                        "        operation='action',",
                        "        accepted=True,",
                        "        detail='default action processed',",
                        "        state={'payload_keys': sorted(request.payload.keys())},",
                        "    )",
                        "",
                    ]
                )
            service_path.write_text("\n".join(service_lines).rstrip() + "\n", encoding="utf-8")
            files.append(str(service_path))

            api_path = subsystem_dir / "api.py"
            api_lines = [
                "from .schemas import OperationRequest, OperationResponse",
                "from .service import health_check",
                "",
                "",
                "def build_contract() -> list[dict[str, object]]:",
                "    return [",
            ]
            for index, api in enumerate(subsystem.get("apis", []), start=1):
                method = str(api.get("method", "GET")).lower()
                raw_path = str(api.get("path", f"{api_prefix}/action_{index}")).replace("'", "")
                path = self._normalize_router_path(raw_path, prefix=api_prefix)
                func_name = self._build_handler_name(method=method, path=path, index=index)
                operation_name = self._extract_operation_name(path, fallback=f"action_{index}")
                description = str(api.get("description", "")).strip().replace("'", "\\'")
                if method == "get" and operation_name == "health":
                    api_lines.extend(
                        [
                            "        {",
                            f"            'method': '{method.upper()}',",
                            f"            'path': '{path}',",
                            "            'handler': 'get_health',",
                            "            'description': 'health check endpoint',",
                            "        },",
                        ]
                    )
                    continue
                api_lines.extend(
                    [
                        "        {",
                        f"            'method': '{method.upper()}',",
                        f"            'path': '{path}',",
                        f"            'handler': '{func_name}',",
                        f"            'description': '{description}',",
                        "        },",
                    ]
                )
            if not subsystem.get("apis", []):
                default_method = "GET"
                default_path = "/health"
                default_func_name = "get_health"
                api_lines.extend(
                    [
                        "        {",
                        f"            'method': '{default_method}',",
                        f"            'path': '{default_path}',",
                        f"            'handler': '{default_func_name}',",
                        "            'description': 'auto-generated default endpoint',",
                        "        },",
                    ]
                )
            api_lines.extend(
                [
                    "    ]",
                    "",
                    "def invoke(operation: str, request: OperationRequest) -> OperationResponse:",
                    "    if operation == 'health':",
                    "        state = {'health': health_check()}",
                    "        return OperationResponse(",
                    f"            subsystem='{module_name}',",
                    "            operation='health',",
                    "            accepted=True,",
                    "            detail='health check succeeded',",
                    "            state=state,",
                    "        )",
                    "    handler_name = f'handle_{operation}'",
                    "    from . import service",
                    "    handler = getattr(service, handler_name, None)",
                    "    if handler is None:",
                    "        return OperationResponse(",
                    f"            subsystem='{module_name}',",
                    "            operation=operation,",
                    "            accepted=False,",
                    "            detail='operation is not implemented',",
                    "            state={'available_operations': [entry['handler'] for entry in build_contract()]},",
                    "        )",
                    "    return handler(request)",
                ]
            )
            api_path.write_text("\n".join(api_lines).rstrip() + "\n", encoding="utf-8")
            files.append(str(api_path))

            detail = detail_designs.get(subsystem_id, {})
            fn_path = subsystem_dir / "functions.md"
            fn_lines = [
                f"# {subsystem.get('name', subsystem_id)} Function List",
                "",
            ]
            for sr_item in detail.get("sr_breakdown", []):
                fn_lines.append(f"## {sr_item.get('sr_id', '')} {sr_item.get('title', '')}")
                for fn in sr_item.get("functions", []):
                    fn_lines.append(f"- {fn.get('id', '')}: {fn.get('description', '')} ({fn.get('spec', '')})")
                fn_lines.append("")
            fn_path.write_text("\n".join(fn_lines).strip() + "\n", encoding="utf-8")
            files.append(str(fn_path))

        return files

    def _normalize_router_path(self, raw_path: str, *, prefix: str) -> str:
        path = raw_path.strip()
        if not path.startswith("/"):
            path = f"/{path}"
        if path.startswith(prefix):
            path = path[len(prefix) :]
        if not path:
            return "/"
        if not path.startswith("/"):
            return f"/{path}"
        return path

    def _build_handler_name(self, *, method: str, path: str, index: int) -> str:
        cleaned = path.strip("/").replace("-", "_").replace("/", "_")
        cleaned = cleaned if cleaned else "root"
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
        if not cleaned:
            cleaned = f"action_{index}"
        return f"{method}_{cleaned}"

    def _extract_operation_name(self, path: str, *, fallback: str) -> str:
        cleaned = path.strip("/").replace("-", "_")
        if not cleaned:
            return fallback
        parts = [part for part in cleaned.split("/") if part]
        if not parts:
            return fallback
        operation = parts[-1]
        operation = "".join(ch for ch in operation if ch.isalnum() or ch == "_")
        return operation or fallback

    def _build_api_contract(self, architecture_design: dict[str, Any]) -> dict[str, Any]:
        endpoints: list[dict[str, Any]] = []
        for subsystem in architecture_design.get("subsystems", []):
            subsystem_id = subsystem.get("id", "")
            for api in subsystem.get("apis", []):
                endpoints.append(
                    {
                        "id": f"API-{len(endpoints) + 1:03d}",
                        "subsystem_id": subsystem_id,
                        "method": api.get("method", "GET"),
                        "path": api.get("path", "/"),
                        "description": api.get("description", ""),
                    }
                )
        return {
            "version": "v1",
            "style": "interface_contract",
            "endpoints": endpoints,
            "schemas": [
                {
                    "name": "ErrorResponse",
                    "fields": {"code": "string", "message": "string"},
                }
            ],
        }

    def _build_architecture_requirements(
        self,
        *,
        architecture_design: dict[str, Any],
        system_requirements: dict[str, Any],
    ) -> dict[str, Any]:
        requirements: list[dict[str, Any]] = []
        for sr in self._normalize_requirements(system_requirements.get("requirements", [])):
            sr_id = str(sr.get("id", ""))
            subsystem_id = self._find_primary_subsystem_for_sr(sr_id, architecture_design)
            requirements.append(
                {
                    "id": f"AR-{len(requirements) + 1:03d}",
                    "source_sr": sr_id,
                    "subsystem_id": subsystem_id,
                    "description": f"Implement architecture support for {sr_id} in {subsystem_id}",
                    "priority": "high",
                }
            )
        return {
            "requirements": requirements,
            "allocation": architecture_design.get("sr_allocation", {}),
        }

    def _build_functional_design(self, detail_designs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        functions: list[dict[str, Any]] = []
        for subsystem_id, detail in detail_designs.items():
            for sr_item in detail.get("sr_breakdown", []):
                for fn in sr_item.get("functions", []):
                    functions.append(
                        {
                            "id": fn.get("id", ""),
                            "subsystem_id": subsystem_id,
                            "source_sr": sr_item.get("sr_id", ""),
                            "description": fn.get("description", ""),
                            "spec": fn.get("spec", ""),
                        }
                    )
        return {
            "functions": functions,
            "count": len(functions),
        }

    def _build_subsystems(
        self,
        requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        keyword_candidates = self._extract_requirement_keywords(requirements)
        requirement_count = max(1, len(requirements))
        subsystem_count = min(4, max(1, (requirement_count + 1) // 2))
        if not keyword_candidates:
            keyword_candidates = ["capability"]

        subsystems: list[dict[str, Any]] = []
        for index in range(subsystem_count):
            subsystem_id = f"SUBSYS-{index + 1:03d}"
            keyword = keyword_candidates[index % len(keyword_candidates)]
            name = self._slugify(f"{keyword}_capability")
            subsystems.append(
                {
                    "id": subsystem_id,
                    "name": name,
                    "description": f"Capability group {index + 1} for requirement fulfillment and service delivery.",
                    "constraints": [],
                    "apis": [
                        {
                            "method": "GET",
                            "path": f"/api/v1/{name}/health",
                            "description": f"Health endpoint for {name}",
                        },
                        {
                            "method": "POST",
                            "path": f"/api/v1/{name}/execute",
                            "description": f"Primary command endpoint for {name}",
                        },
                    ],
                }
            )
        return subsystems

    def _allocate_srs_to_subsystems(
        self,
        requirements: list[dict[str, Any]],
        subsystems: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        allocation: dict[str, list[str]] = {str(item.get("id", "")): [] for item in subsystems}
        if not subsystems:
            return allocation
        if len(requirements) == 1 and len(subsystems) > 1:
            only_sr = str(requirements[0].get("id", "")).strip()
            if only_sr:
                for subsystem in subsystems:
                    allocation.setdefault(str(subsystem.get("id", "")), []).append(only_sr)
            return allocation

        for index, requirement in enumerate(requirements):
            sr_id = str(requirement.get("id", "")).strip()
            if not sr_id:
                continue
            subsystem = subsystems[index % len(subsystems)]
            key = str(subsystem.get("id", ""))
            allocation.setdefault(key, []).append(sr_id)
        return allocation

    def _build_components(
        self,
        subsystems: list[dict[str, Any]],
        sr_allocation: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        components: list[dict[str, Any]] = []
        for subsystem in subsystems:
            subsystem_id = str(subsystem.get("id", ""))
            module = self._slugify(str(subsystem.get("name", subsystem_id)))
            components.extend(
                [
                    {
                        "id": f"COMP-{subsystem_id}-API",
                        "name": f"{module}-api",
                        "type": "service",
                        "subsystem_id": subsystem_id,
                        "responsibilities": [
                            "Expose HTTP APIs",
                            "Input validation",
                        ],
                        "sr_ids": sr_allocation.get(subsystem_id, []),
                    },
                    {
                        "id": f"COMP-{subsystem_id}-DOMAIN",
                        "name": f"{module}-domain",
                        "type": "service",
                        "subsystem_id": subsystem_id,
                        "responsibilities": [
                            "Business orchestration",
                            "Policy and rule evaluation",
                        ],
                        "sr_ids": sr_allocation.get(subsystem_id, []),
                    },
                    {
                        "id": f"COMP-{subsystem_id}-REPO",
                        "name": f"{module}-repository",
                        "type": "repository",
                        "subsystem_id": subsystem_id,
                        "responsibilities": [
                            "Persistence abstraction",
                            "Data access and query",
                        ],
                        "sr_ids": sr_allocation.get(subsystem_id, []),
                    },
                ]
            )
        return components

    def _build_subsystem_components(self, subsystem: dict[str, Any]) -> list[dict[str, Any]]:
        subsystem_id = str(subsystem.get("id", "SUBSYS"))
        module = self._slugify(str(subsystem.get("name", subsystem_id)))
        responsibilities = self._infer_subsystem_component_responsibilities(module)
        return [
            {
                "id": f"{subsystem_id}-C1",
                "name": f"{module}-app-service",
                "type": "service",
                "responsibility": responsibilities[0],
            },
            {
                "id": f"{subsystem_id}-C2",
                "name": f"{module}-domain-service",
                "type": "service",
                "responsibility": responsibilities[1],
            },
            {
                "id": f"{subsystem_id}-C3",
                "name": f"{module}-gateway",
                "type": "adapter",
                "responsibility": responsibilities[2],
            },
        ]

    def _build_fn_items(
        self,
        sr_items: list[dict[str, Any]],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        functions: list[dict[str, Any]] = []
        for sr in sr_items:
            sr_id = str(sr.get("id", ""))
            sr_title = str(sr.get("title", sr.get("requirement_overview", ""))).strip()
            for idx, component in enumerate(components, start=1):
                fn_id = f"FN-{sr_id}-{idx:02d}"
                fn_desc = self._build_fn_description(sr_title, component)
                fn_spec = self._build_fn_spec(sr_title, component)
                functions.append(
                    {
                        "id": fn_id,
                        "source_sr": sr_id,
                        "component": component.get("name", ""),
                        "description": fn_desc,
                        "spec": fn_spec,
                    }
                )
        return functions

    def _find_primary_subsystem_for_sr(
        self,
        sr_id: str,
        architecture_design: dict[str, Any],
    ) -> str:
        for subsystem_id, sr_ids in architecture_design.get("sr_allocation", {}).items():
            if sr_id in sr_ids:
                return str(subsystem_id)
        return "SUBSYS-UNKNOWN"

    def _normalize_requirements(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue
            sr_id = str(item.get("id", f"SR-{index:03d}")).strip() or f"SR-{index:03d}"
            normalized.append(
                {
                    "id": sr_id,
                    "title": str(item.get("title", sr_id)),
                    "requirement_overview": str(item.get("requirement_overview", "")),
                    "scenario": str(item.get("scenario", "")),
                    "users": item.get("users", ["End User"]),
                    "interaction_process": item.get("interaction_process", []),
                    "expected_result": str(item.get("expected_result", "")),
                    "spec_targets": item.get("spec_targets", []),
                    "constraints": item.get("constraints", []),
                }
            )
        return normalized

    def _render_system_architecture_doc(
        self,
        *,
        project_name: str,
        product_design: dict[str, Any],
        system_requirements: dict[str, Any],
        architecture_design: dict[str, Any],
        rounds: list[dict[str, Any]],
        assignments: dict[str, dict[str, Any]],
    ) -> str:
        lines = [
            "# system-architecture.md",
            "",
            f"Generated at: {self._now_iso()}",
            f"Project: {project_name}",
            "",
            "## Inputs",
            "",
            f"- Product Features: {len(product_design.get('system_features', []))}",
            f"- System Requirements: {len(self._normalize_requirements(system_requirements.get('requirements', [])))}",
            "",
            "## Architecture Design Goals",
            "",
            *[f"- {goal}" for goal in architecture_design.get("design_goals", [])],
            "",
            "## Design Principles",
            "",
            *[f"- {principle}" for principle in architecture_design.get("principles", [])],
            "",
            "## Overall Architecture",
            "",
            f"- Overview: {architecture_design.get('architecture_overview', '')}",
            f"- Diagram: {architecture_design.get('architecture_diagram', '')}",
            "",
            "## Layered Expansion",
            "",
            *[f"- {layer}" for layer in architecture_design.get("layering", [])],
            "",
            "## Subsystems",
            "",
        ]

        for subsystem in architecture_design.get("subsystems", []):
            subsystem_id = str(subsystem.get("id", ""))
            assigned_sr = ", ".join(architecture_design.get("sr_allocation", {}).get(subsystem_id, [])) or "(none)"
            lines.extend(
                [
                    f"### {subsystem_id} - {subsystem.get('name', '')}",
                    f"- Description: {subsystem.get('description', '')}",
                    "- API Design:",
                    *[
                        f"  - `{api.get('method', 'GET')} {api.get('path', '/')}`: {api.get('description', '')}"
                        for api in subsystem.get("apis", [])
                    ],
                    f"- Assigned SR: {assigned_sr}",
                    "",
                ]
            )

        lines.extend(["## Components", ""])
        for component in architecture_design.get("components", []):
            lines.extend(
                [
                    f"### {component.get('id', '')} - {component.get('name', '')}",
                    f"- Type: {component.get('type', '')}",
                    f"- Subsystem: {component.get('subsystem_id', '')}",
                    "- Responsibilities:",
                    *[f"  - {item}" for item in component.get("responsibilities", [])],
                    f"- SR Mapping: {', '.join(component.get('sr_ids', [])) or '(none)'}",
                    "",
                ]
            )

        lines.extend(["## Task Split (Step 3)", ""])
        for subsystem_id, assignment in assignments.items():
            lines.extend(
                [
                    f"- {subsystem_id}:",
                    f"  - Subsystem Architect: {assignment.get('subsystem_architect', '')}",
                    f"  - Architecture Reviewer: {assignment.get('architecture_reviewer', '')}",
                    f"  - SR IDs: {', '.join(assignment.get('assigned_sr_ids', [])) or '(none)'}",
                ]
            )
        lines.append("")

        lines.extend(["## Revision History", ""])
        for item in rounds:
            review = item.get("review", {})
            design = item.get("architecture_design", {})
            lines.extend(
                [
                    f"### Round {item.get('round', '')}",
                    f"- Reviewer Decision: {review.get('decision', '')}",
                    f"- Reviewer Summary: {review.get('summary', '')}",
                    "- Reviewer Issues:",
                    *self._bullet_or_default(review.get("issues", []), default="(none)"),
                    "- Reviewer Suggestions:",
                    *self._bullet_or_default(review.get("suggestions", []), default="(none)"),
                    "- Architecture Designer Response:",
                    *self._bullet_or_default(
                        design.get("designer_response", []),
                        default="Initial draft",
                    ),
                    "",
                ]
            )

        return "\n".join(lines).strip() + "\n"

    def _render_subsystem_detail_doc(
        self,
        *,
        project_name: str,
        subsystem: dict[str, Any],
        architecture_design: dict[str, Any],
        system_requirements: dict[str, Any],
        detail_design: dict[str, Any],
        rounds: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"# {subsystem.get('name', subsystem.get('id', 'subsystem'))}-detail-design.md",
            "",
            f"Generated at: {self._now_iso()}",
            f"Project: {project_name}",
            "",
            "## Context",
            "",
            f"- Subsystem: {subsystem.get('id', '')} {subsystem.get('name', '')}",
            f"- Architecture Overview: {architecture_design.get('architecture_overview', '')}",
            f"- Total SR in project: {len(self._normalize_requirements(system_requirements.get('requirements', [])))}",
            "",
            "## Logic Architecture Goals",
            "",
            *[f"- {goal}" for goal in detail_design.get("logic_architecture_goals", [])],
            "",
            "## Design Strategy",
            "",
            *[f"- {item}" for item in detail_design.get("design_strategy", [])],
            "",
            "## Components / Services",
            "",
        ]

        for component in detail_design.get("components", []):
            lines.extend(
                [
                    f"### {component.get('id', '')} - {component.get('name', '')}",
                    f"- Type: {component.get('type', '')}",
                    f"- Responsibility: {component.get('responsibility', '')}",
                    "",
                ]
            )

        lines.extend(["## API Design", ""])
        for api in detail_design.get("apis", []):
            lines.append(f"- `{api.get('method', 'GET')} {api.get('path', '/')}`: {api.get('description', '')}")
        lines.extend(["", "## Technology Choices", ""])
        tech = detail_design.get("technology_choices", {})
        lines.extend(
            [
                f"- Language: {tech.get('language', '')}",
                f"- Framework: {tech.get('framework', '')}",
                f"- Storage: {tech.get('storage', '')}",
                "",
                "## SR -> FN Breakdown",
                "",
            ]
        )

        for sr_item in detail_design.get("sr_breakdown", []):
            lines.extend(
                [
                    f"### {sr_item.get('sr_id', '')} - {sr_item.get('title', '')}",
                    "- Functions:",
                ]
            )
            for fn in sr_item.get("functions", []):
                lines.extend(
                    [
                        f"  - {fn.get('id', '')}",
                        f"    - Component: {fn.get('component', '')}",
                        f"    - Description: {fn.get('description', '')}",
                        f"    - Spec: {fn.get('spec', '')}",
                    ]
                )
            lines.append("")

        lines.extend(["## Revision History", ""])
        for round_item in rounds:
            review = round_item.get("review", {})
            design = round_item.get("detail_design", {})
            lines.extend(
                [
                    f"### Round {round_item.get('round', '')}",
                    f"- Reviewer: {review.get('reviewer', '')}",
                    f"- Reviewer Decision: {review.get('decision', '')}",
                    f"- Reviewer Summary: {review.get('summary', '')}",
                    "- Reviewer Issues:",
                    *self._bullet_or_default(review.get("issues", []), default="(none)"),
                    "- Reviewer Suggestions:",
                    *self._bullet_or_default(review.get("suggestions", []), default="(none)"),
                    "- Subsystem Architect Response:",
                    *self._bullet_or_default(
                        design.get("designer_response", []),
                        default="Initial draft",
                    ),
                    "",
                ]
            )

        return "\n".join(lines).strip() + "\n"

    def _build_designer_response(self, previous_review: dict[str, Any] | None) -> list[str]:
        if not previous_review:
            return ["Initial draft based on upstream requirements and architecture context."]
        issues = [str(item) for item in previous_review.get("issues", [])]
        if not issues:
            return ["No additional reviewer issues; confirming consistency and traceability."]
        return [f"Addressed reviewer issue: {issue}" for issue in issues[:6]]

    def _resolve_project_root(self, context: SkillContext) -> Path | None:
        project_root = context.parameters.get("project_root")
        if isinstance(project_root, str) and project_root.strip():
            return Path(project_root).resolve()
        return None

    def _resolve_docs_dir(self, input_data: dict[str, Any], context: SkillContext) -> Path:
        return self._resolve_dir(input_data, context, key="output_dir", default_subdir="docs")

    def _resolve_src_dir(self, input_data: dict[str, Any], context: SkillContext) -> Path:
        return self._resolve_dir(input_data, context, key="source_dir", default_subdir="src")

    def _resolve_dir(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
        *,
        key: str,
        default_subdir: str,
    ) -> Path:
        root = self._resolve_project_root(context)
        default_path = (root / default_subdir) if root is not None else Path(default_subdir)
        raw = input_data.get(key)
        if not isinstance(raw, str) or not raw.strip():
            return default_path

        user_path = Path(raw)
        if root is None:
            return user_path.resolve()
        candidate = (root / user_path).resolve() if not user_path.is_absolute() else user_path.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return default_path
        return candidate

    def _slugify(self, text: str) -> str:
        cleaned = []
        prev_dash = False
        for ch in text.lower().strip():
            if ch.isalnum():
                cleaned.append(ch)
                prev_dash = False
            else:
                if not prev_dash:
                    cleaned.append("_")
                prev_dash = True
        value = "".join(cleaned).strip("_")
        if len(value) > 48:
            value = value[:48].rstrip("_")
        return value or "subsystem"

    def _infer_subsystem_component_responsibilities(self, module: str) -> list[str]:
        return [
            f"Coordinate {module} requests and workflow routing",
            f"Apply {module} domain logic and validation rules",
            f"Integrate persistence and external dependencies for {module}",
        ]

    def _extract_requirement_keywords(
        self,
        requirements: list[dict[str, Any]],
    ) -> list[str]:
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "system",
            "feature",
            "requirement",
            "user",
            "users",
            "support",
            "supports",
            "build",
            "create",
            "开发",
            "系统",
            "支持",
            "用户",
            "需求",
        }
        text_chunks: list[str] = []
        for item in requirements:
            if not isinstance(item, dict):
                continue
            text_chunks.append(str(item.get("title", "")))
            text_chunks.append(str(item.get("requirement_overview", "")))
        merged = " ".join(text_chunks).lower()
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{1,6}", merged)
        words = [self._slugify(token) for token in tokens]
        keywords: list[str] = []
        for word in words:
            if not word or word in stopwords or word.isdigit():
                continue
            if word.startswith("sr_") or word.startswith("sf_"):
                continue
            if word not in keywords:
                keywords.append(word)
            if len(keywords) >= 8:
                break
        return keywords

    def _build_current_architecture_context(
        self,
        previous_design: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
    ) -> str:
        if not previous_design:
            return (
                "Round 1 initial context:\n"
                "- No previous architecture design.\n"
                "- Generate the first architecture draft from product design document and system requirements."
            )
        payload = {
            "previous_architecture_design": previous_design,
            "reviewer_feedback": previous_review or {},
        }
        return self._compact_json(payload)

    def _compact_json(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except TypeError:
            return str(payload)

    def _build_fn_description(self, sr_title: str, component: dict[str, Any]) -> str:
        comp_name = str(component.get("name", "component"))
        return f"{comp_name} supports delivery of {sr_title}"

    def _build_fn_spec(self, sr_title: str, component: dict[str, Any]) -> str:
        return "Input/Output validated, observable metrics, and retry/error handling defined."

    def _bullet_or_default(self, values: Any, *, default: str) -> list[str]:
        if not isinstance(values, list):
            return [f"  - {default}"]
        bullets = [f"  - {str(item)}" for item in values if str(item).strip()]
        return bullets if bullets else [f"  - {default}"]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_technology_choices(self, value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            language = str(value.get("language", "")).strip() or "to_be_determined"
            framework = str(value.get("framework", "")).strip() or "to_be_determined"
            storage = str(value.get("storage", "")).strip() or "to_be_determined"
            return {"language": language, "framework": framework, "storage": storage}
        return {"language": "to_be_determined", "framework": "to_be_determined", "storage": "to_be_determined"}

    def _as_str_list(self, value: Any, *, fallback: list[str]) -> list[str]:
        if not isinstance(value, list):
            return fallback
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or fallback

    def _run_llm_json(
        self,
        *,
        context: SkillContext,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        if context.llm_client is None:
            raise RuntimeError("LLM client is required for deep_architecture_workflow")
        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            llm_purpose=purpose,
        )
        parsed = self._parse_json_response(response)
        if parsed is None:
            raise RuntimeError(f"LLM response is not valid JSON object for {purpose}")
        return parsed

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if not block:
            return None
        try:
            parsed = json.loads(block.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
