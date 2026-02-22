"""Deep architecture workflow skill with paired architecture subagents."""

from __future__ import annotations

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
            product_design=product_design,
            system_requirements=system_requirements,
            min_rounds=2,
        )
        architecture_design = architecture_rounds[-1]["architecture_design"]

        # Step 2: initialize top-level source structure and API definitions.
        bootstrap_files = self._initialize_top_level_code(
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
                subsystem=subsystem,
                system_requirements=system_requirements,
                architecture_design=architecture_design,
                assignment=assignments.get(subsystem.get("id", ""), {}),
                min_rounds=2,
            )
            detail_rounds[str(subsystem.get("id", ""))] = rounds
            detail_designs[str(subsystem.get("id", ""))] = rounds[-1]["detail_design"]

        # Step 5: initialize per-subsystem code and API contracts.
        subsystem_scaffold_files = self._initialize_subsystem_code(
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
            "backend": {"language": "Python", "framework": "FastAPI"},
            "database": {"name": "PostgreSQL"},
            "deployment": {"container": "Docker", "orchestration": "Kubernetes"},
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
                product_design=product_design,
                system_requirements=system_requirements,
                previous_design=previous_design,
                previous_review=previous_review,
                round_index=round_index,
            )
            review = self._review_architecture_design(
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
        return {
            "round": round_index,
            "design_goals": [
                "Deliver a traceable architecture from SR to subsystem/component.",
                "Keep API boundaries explicit and implementable.",
                "Prepare subsystem-level detailed design and coding bootstrap.",
            ],
            "principles": [
                "Clear separation of concerns",
                "API-first contract design",
                "Traceability from SR to implementation units",
                "Operational observability by default",
            ],
            "architecture_overview": (
                f"Architecture derived from {len(requirements)} SR items and {feature_count} product feature items."
            ),
            "architecture_diagram": (
                "Client -> API Gateway -> Application Service Layer -> Domain Services -> Persistence/Infrastructure"
            ),
            "layering": [
                "System Layer",
                "Subsystem Layer",
                "Component/Service Layer",
            ],
            "subsystems": subsystems,
            "components": components,
            "sr_allocation": sr_allocation,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _review_architecture_design(
        self,
        *,
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

        return {
            "reviewer_instances": reviewer_instances,
            "approved": approved,
            "decision": "approve" if approved else "revise",
            "summary": "Architecture accepted" if approved else "Architecture requires revision",
            "issues": issues,
            "suggestions": [
                "Ensure every SR is mapped to exactly one primary subsystem.",
                "Provide API contract examples for each subsystem.",
                "Capture reviewer意见 and designer responses in revision history.",
            ],
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
        app_file.write_text(
            (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI(title='AISE Generated Service')\n\n"
                "@app.get('/healthz')\n"
                "def healthz() -> dict[str, str]:\n"
                "    return {'status': 'ok'}\n"
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
                subsystem=subsystem,
                system_requirements=system_requirements,
                architecture_design=architecture_design,
                assignment=assignment,
                previous_design=previous_design,
                previous_review=previous_review,
                round_index=round_index,
            )
            review = self._review_subsystem_detail(
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

        return {
            "round": round_index,
            "subsystem": subsystem.get("name", subsystem.get("id", "")),
            "owner": assignment.get("subsystem_architect", "subsystem_architect_1"),
            "logic_architecture_goals": [
                f"Ensure subsystem {subsystem.get('name', '')} delivers assigned SR with clear service split.",
                "Keep interfaces stable and testable.",
            ],
            "design_strategy": [
                "Decompose by domain capability",
                "Encapsulate storage and integration concerns",
                "API-first for component boundaries",
            ],
            "components": components,
            "apis": subsystem.get("apis", []),
            "technology_choices": {
                "language": "Python",
                "framework": "FastAPI",
                "storage": "PostgreSQL",
            },
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

        return {
            "reviewer": reviewer,
            "approved": approved,
            "decision": "approve" if approved else "revise",
            "summary": (
                f"{subsystem.get('name', subsystem.get('id', 'subsystem'))} detail design approved"
                if approved
                else "Detail design requires revision"
            ),
            "issues": issues,
            "suggestions": [
                "Ensure each SR maps to one or more component-level FN entries.",
                "Keep FN specification concrete enough for developers.",
            ],
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

            api_path = subsystem_dir / "api.py"
            api_lines = [
                "from fastapi import APIRouter",
                "",
                f"router = APIRouter(prefix='/{module_name}', tags=['{module_name}'])",
                "",
            ]
            for index, api in enumerate(subsystem.get("apis", []), start=1):
                method = str(api.get("method", "GET")).lower()
                path = str(api.get("path", f"/{module_name}/{index}")).replace("'", "")
                func_name = f"endpoint_{index}_{method}"
                api_lines.extend(
                    [
                        f"@router.{method}('{path}')",
                        f"def {func_name}() -> dict[str, str]:",
                        f"    return {{'subsystem': '{module_name}', 'endpoint': '{func_name}'}}",
                        "",
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
            "style": "REST",
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

    def _build_subsystems(self, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        requirement_text = " ".join(
            f"{item.get('title', '')} {item.get('requirement_overview', '')}"
            for item in requirements
            if isinstance(item, dict)
        ).lower()
        if "snake" in requirement_text or "贪吃蛇" in requirement_text:
            seeds = [
                ("SUBSYS-001", "gameplay_core", "Snake movement loop, collision, and map runtime"),
                ("SUBSYS-002", "mode_matchmaking", "Single/AI/multiplayer mode setup and room/session management"),
                ("SUBSYS-003", "scoring_progression", "Food effects, score settlement, and level progression"),
            ]
        else:
            seeds = [
                ("SUBSYS-001", "core_domain", "Core domain behavior and business orchestration"),
                ("SUBSYS-002", "integration_service", "External integration and adapter layer"),
                ("SUBSYS-003", "platform_ops", "Observability, operations, and maintenance support"),
            ]
        subsystems: list[dict[str, Any]] = []
        for subsystem_id, name, desc in seeds:
            primary_action = "actions"
            if "gameplay" in name:
                primary_action = "tick"
            elif "matchmaking" in name:
                primary_action = "match"
            elif "scoring" in name:
                primary_action = "score"
            subsystems.append(
                {
                    "id": subsystem_id,
                    "name": name,
                    "description": desc,
                    "constraints": [],
                    "apis": [
                        {
                            "method": "GET",
                            "path": f"/api/v1/{name}/health",
                            "description": f"Health endpoint for {name}",
                        },
                        {
                            "method": "POST",
                            "path": f"/api/v1/{name}/{primary_action}",
                            "description": f"Primary command endpoint for {name}",
                        },
                    ],
                }
            )

        if len(requirements) <= 1:
            return subsystems
        if len(requirements) == 2:
            return subsystems[:2]
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
        return value or "subsystem"

    def _infer_subsystem_component_responsibilities(self, module: str) -> list[str]:
        if "gameplay" in module or "snake" in module:
            return [
                "Coordinate game tick, snake movement, and collision workflow",
                "Apply map rules, collision rules, and deterministic state transitions",
                "Persist round snapshots and expose replay/state query adapters",
            ]
        if "match" in module or "mode" in module:
            return [
                "Coordinate mode selection, room lifecycle, and player readiness",
                "Apply matching policies and bot-player orchestration rules",
                "Integrate session store and transport adapters for real-time sync",
            ]
        if "score" in module or "progress" in module:
            return [
                "Coordinate score changes, food effects, and settlement flow",
                "Apply scoring formulas, level thresholds, and reward constraints",
                "Integrate leaderboard/reward storage and query adapters",
            ]
        return [
            "Coordinate business process",
            "Domain logic and validation",
            "External systems and persistence integration",
        ]

    def _build_fn_description(self, sr_title: str, component: dict[str, Any]) -> str:
        comp_name = str(component.get("name", "component"))
        if "snake" in sr_title.lower() or "贪吃蛇" in sr_title:
            if "app-service" in comp_name:
                return f"{comp_name} orchestrates mode flow, input actions, and game tick for {sr_title}"
            if "domain-service" in comp_name:
                return f"{comp_name} computes movement/collision/food effect rules for {sr_title}"
            return f"{comp_name} persists game state, score, and replay snapshots for {sr_title}"
        return f"{comp_name} supports delivery of {sr_title}"

    def _build_fn_spec(self, sr_title: str, component: dict[str, Any]) -> str:
        if "snake" in sr_title.lower() or "贪吃蛇" in sr_title:
            return (
                "Define clear input/output schema, deterministic state transition, "
                "and verifiable checks for score/level or match outcome."
            )
        return "Input/Output validated, observable metrics, and retry/error handling defined."

    def _bullet_or_default(self, values: Any, *, default: str) -> list[str]:
        if not isinstance(values, list):
            return [f"  - {default}"]
        bullets = [f"  - {str(item)}" for item in values if str(item).strip()]
        return bullets if bullets else [f"  - {default}"]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
