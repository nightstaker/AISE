"""Deep architecture workflow skill with paired architecture subagents."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        recorder = context.parameters.get("task_memory_recorder") or input_data.get("_task_memory_recorder")
        phase_key = str(context.parameters.get("phase_key") or context.parameters.get("phase") or "design")
        retry_task_key = str(context.parameters.get("retry_task_key") or input_data.get("retry_task_key") or "")
        execution_scope = str(context.parameters.get("execution_scope") or "full_skill")
        project_root = self._resolve_project_root(context)
        docs_dir = self._resolve_docs_dir(input_data, context)
        src_dir = self._resolve_src_dir(input_data, context)
        docs_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(parents=True, exist_ok=True)

        attempts: dict[str, int] = {}

        def _start(task_key: str) -> None:
            if retry_task_key and task_key != retry_task_key:
                return
            if not recorder or not hasattr(recorder, "record_task_attempt_start"):
                return
            started = recorder.record_task_attempt_start(
                phase_key=phase_key,
                task_key=task_key,
                display_name=task_key.rsplit(".", 1)[-1],
                kind="retry" if retry_task_key else "initial",
                mode=str(context.parameters.get("retry_mode") or input_data.get("retry_mode") or "current"),
                executor={
                    "agent": "architect",
                    "skill": "deep_architecture_workflow",
                    "task_key": task_key,
                    "execution_scope": execution_scope if retry_task_key else "full_skill",
                },
            )
            attempt = started.get("attempt", {}) if isinstance(started, dict) else {}
            attempt_no = int((attempt or {}).get("attempt_no", 0) or 0)
            attempts[task_key] = attempt_no
            if hasattr(recorder, "record_task_attempt_context") and attempt_no:
                recorder.record_task_attempt_context(
                    phase_key=phase_key,
                    task_key=task_key,
                    attempt_no=attempt_no,
                    context=self._step_task_memory_context(
                        task_key=task_key,
                        docs_dir=docs_dir,
                        src_dir=src_dir,
                        available_input_keys=sorted(input_data.keys()),
                    ),
                )

        def _end(task_key: str, *, status: str, error: str = "", outputs: dict[str, Any] | None = None) -> None:
            if retry_task_key and task_key != retry_task_key:
                return
            attempt_no = attempts.get(task_key, 0)
            if not recorder or not attempt_no:
                return
            if outputs and hasattr(recorder, "record_task_attempt_output"):
                recorder.record_task_attempt_output(
                    phase_key=phase_key,
                    task_key=task_key,
                    attempt_no=attempt_no,
                    outputs=outputs,
                )
            if hasattr(recorder, "record_task_attempt_end"):
                recorder.record_task_attempt_end(
                    phase_key=phase_key,
                    task_key=task_key,
                    attempt_no=attempt_no,
                    status=status,
                    error=error,
                )

        product_design = self._load_product_design(context, docs_dir)
        system_requirements = self._load_system_requirements(context, docs_dir)
        if not system_requirements:
            system_requirements = self._fallback_requirements_from_product_design(product_design)
        review_min_rounds, review_max_rounds = self._resolve_review_round_bounds(input_data=input_data, context=context)

        # Step 1: architecture design + reviewer loop.
        _start("architect.deep_architecture_workflow.step1.design")
        _start("architect.deep_architecture_workflow.step1.review")
        try:
            architecture_rounds = self._run_architecture_review_rounds(
                context=context,
                product_design=product_design,
                system_requirements=system_requirements,
                min_rounds=review_min_rounds,
                max_rounds=review_max_rounds,
            )
            _end(
                "architect.deep_architecture_workflow.step1.design",
                status="completed",
                outputs={"rounds": len(architecture_rounds)},
            )
            _end(
                "architect.deep_architecture_workflow.step1.review",
                status="completed",
                outputs={"rounds": len(architecture_rounds)},
            )
        except Exception as exc:
            _end("architect.deep_architecture_workflow.step1.design", status="failed", error=str(exc))
            _end("architect.deep_architecture_workflow.step1.review", status="failed", error=str(exc))
            raise
        architecture_design = architecture_rounds[-1]["architecture_design"]

        # Step 2+3: lightweight bootstrap and subsystem task split are grouped as one
        # visible workflow task to reduce over-fragmented architecture phase tracking.
        _start("architect.deep_architecture_workflow.step2_3")
        try:
            bootstrap_files: list[str] = self._initialize_top_level_code(
                src_dir=src_dir,
                architecture_design=architecture_design,
            )
            assignments = self._build_subsystem_assignments(architecture_design)
            _end(
                "architect.deep_architecture_workflow.step2_3",
                status="completed",
                outputs={
                    "generated_files": bootstrap_files,
                    "assignment_count": len(assignments),
                    "workflow_summary": {
                        "workflow": "deep_architecture_workflow",
                        "subsystems": [
                            {
                                "subsystem_id": str(sid),
                                "subsystem_name": str(item.get("subsystem", sid)),
                                "subsystem_slug": str(item.get("subsystem_english_name", "")).strip()
                                or self._slugify(str(item.get("subsystem", sid))),
                                "subsystem_english_name": str(item.get("subsystem_english_name", "")).strip(),
                                "assigned_sr_ids": [str(x) for x in item.get("assigned_sr_ids", [])]
                                if isinstance(item.get("assigned_sr_ids"), list)
                                else [],
                            }
                            for sid, item in assignments.items()
                            if isinstance(item, dict)
                        ],
                    },
                },
            )
        except Exception as exc:
            _end("architect.deep_architecture_workflow.step2_3", status="failed", error=str(exc))
            raise

        # Step 4: per-subsystem detailed design + reviewer loop.
        # Each subsystem runs serially inside its own loop, but different subsystems
        # can execute in parallel to reduce architecture-phase wall-clock time.
        _start("architect.deep_architecture_workflow.step4.design")
        _start("architect.deep_architecture_workflow.step4.review")
        detail_designs: dict[str, dict[str, Any]] = {}
        detail_rounds: dict[str, list[dict[str, Any]]] = {}
        detail_doc_paths: list[Path] = []
        try:
            subsystems = [s for s in architecture_design.get("subsystems", []) if isinstance(s, dict)]
            subsystem_order = [str(s.get("id", "")) for s in subsystems]

            def _run_one_subsystem(
                subsystem: dict[str, Any],
            ) -> tuple[str, dict[str, Any], list[dict[str, Any]], str, str]:
                subsystem_id = str(subsystem.get("id", ""))
                rounds = self._run_subsystem_detail_rounds(
                    context=context,
                    subsystem=subsystem,
                    system_requirements=system_requirements,
                    architecture_design=architecture_design,
                    assignment=assignments.get(subsystem.get("id", ""), {}),
                    min_rounds=review_min_rounds,
                    max_rounds=review_max_rounds,
                )
                detail = rounds[-1]["detail_design"]
                file_name = f"subsystem-{self._subsystem_slug(subsystem, fallback=subsystem_id)}-design.md"
                rendered_doc = self._render_subsystem_detail_doc(
                    project_name=project_name,
                    subsystem=subsystem,
                    architecture_design=architecture_design,
                    system_requirements=system_requirements,
                    detail_design=detail,
                    rounds=rounds,
                )
                return subsystem_id, detail, rounds, file_name, rendered_doc

            future_results: dict[str, tuple[dict[str, Any], list[dict[str, Any]], Path]] = {}
            max_workers = min(4, max(1, len(subsystems)))
            if len(subsystems) <= 1:
                for subsystem in subsystems:
                    sid, detail, rounds, file_name, rendered_doc = _run_one_subsystem(subsystem)
                    path = docs_dir / file_name
                    # Write immediately after this subsystem finishes so users can inspect
                    # detail docs while other subsystems are still running.
                    path.write_text(rendered_doc, encoding="utf-8")
                    future_results[sid] = (detail, rounds, path)
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="arch-subsys") as pool:
                    future_map = {pool.submit(_run_one_subsystem, subsystem): subsystem for subsystem in subsystems}
                    for future in as_completed(future_map):
                        sid, detail, rounds, file_name, rendered_doc = future.result()
                        path = docs_dir / file_name
                        # Real-time incremental persistence: each subsystem doc is flushed
                        # as soon as its design+review loop completes.
                        path.write_text(rendered_doc, encoding="utf-8")
                        future_results[sid] = (detail, rounds, path)

            for subsystem_id in subsystem_order:
                packed = future_results.get(subsystem_id)
                if not packed:
                    continue
                detail, rounds, path = packed
                detail_rounds[subsystem_id] = rounds
                detail_designs[subsystem_id] = detail
                detail_doc_paths.append(path)
            _end(
                "architect.deep_architecture_workflow.step4.design",
                status="completed",
                outputs={
                    "subsystems": list(detail_designs.keys()),
                    "workflow_summary": {
                        "workflow": "deep_architecture_workflow",
                        "subsystems": [
                            {
                                "subsystem_id": str(sid),
                                "subsystem_name": str((assignments.get(sid, {}) or {}).get("subsystem", sid)),
                                "subsystem_slug": str(
                                    (assignments.get(sid, {}) or {}).get("subsystem_english_name", "")
                                ).strip()
                                or self._slugify(str((assignments.get(sid, {}) or {}).get("subsystem", sid))),
                                "subsystem_english_name": str(
                                    (assignments.get(sid, {}) or {}).get("subsystem_english_name", "")
                                ).strip(),
                                "assigned_sr_ids": [
                                    str(x) for x in (assignments.get(sid, {}) or {}).get("assigned_sr_ids", [])
                                ]
                                if isinstance((assignments.get(sid, {}) or {}).get("assigned_sr_ids"), list)
                                else [],
                            }
                            for sid in detail_designs.keys()
                        ],
                        "subsystem_rounds_each": {str(sid): len(rounds) for sid, rounds in detail_rounds.items()},
                    },
                },
            )
            _end(
                "architect.deep_architecture_workflow.step4.review",
                status="completed",
                outputs={
                    "subsystems": list(detail_designs.keys()),
                    "workflow_summary": {
                        "workflow": "deep_architecture_workflow",
                        "subsystems": [
                            {
                                "subsystem_id": str(sid),
                                "subsystem_name": str((assignments.get(sid, {}) or {}).get("subsystem", sid)),
                                "subsystem_slug": str(
                                    (assignments.get(sid, {}) or {}).get("subsystem_english_name", "")
                                ).strip()
                                or self._slugify(str((assignments.get(sid, {}) or {}).get("subsystem", sid))),
                                "subsystem_english_name": str(
                                    (assignments.get(sid, {}) or {}).get("subsystem_english_name", "")
                                ).strip(),
                                "assigned_sr_ids": [
                                    str(x) for x in (assignments.get(sid, {}) or {}).get("assigned_sr_ids", [])
                                ]
                                if isinstance((assignments.get(sid, {}) or {}).get("assigned_sr_ids"), list)
                                else [],
                            }
                            for sid in detail_designs.keys()
                        ],
                        "subsystem_rounds_each": {str(sid): len(rounds) for sid, rounds in detail_rounds.items()},
                    },
                },
            )
        except Exception as exc:
            _end("architect.deep_architecture_workflow.step4.design", status="failed", error=str(exc))
            _end("architect.deep_architecture_workflow.step4.review", status="failed", error=str(exc))
            raise

        # Step 5: initialize per-subsystem code and API contracts.
        _start("architect.deep_architecture_workflow.step5")
        try:
            subsystem_scaffold_files: list[str] = self._initialize_subsystem_code(
                src_dir=src_dir,
                architecture_design=architecture_design,
                detail_designs=detail_designs,
            )
            _end(
                "architect.deep_architecture_workflow.step5",
                status="completed",
                outputs={"generated_files": subsystem_scaffold_files},
            )
        except Exception as exc:
            _end("architect.deep_architecture_workflow.step5", status="failed", error=str(exc))
            raise

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

        # Subsystem detail docs were already written incrementally during Step 4.

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
                    "step2_3": {
                        "name": "bootstrap_and_subsystem_task_split",
                        "status": "completed",
                        "files": bootstrap_files,
                        "assignments": assignments,
                        "merged_steps": ["step2", "step3"],
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
        lines = content.splitlines()
        features: list[dict[str, Any]] = []
        intent_summary = ""
        business_goals: list[str] = []
        users: list[str] = []
        constraints: list[str] = []
        in_business_goals = False
        in_users = False
        in_constraints = False

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("- Summary:"):
                intent_summary = stripped.removeprefix("- Summary:").strip()
            if stripped == "- Business Goals:":
                in_business_goals = True
                in_users = in_constraints = False
                continue
            if stripped == "- Users:":
                in_users = True
                in_business_goals = in_constraints = False
                continue
            if stripped == "- Constraints:":
                in_constraints = True
                in_business_goals = in_users = False
                continue
            if stripped.startswith("## ") or stripped.startswith("### "):
                in_business_goals = in_users = in_constraints = False

            if in_business_goals and stripped.startswith("- "):
                goal = stripped.removeprefix("- ").strip()
                if goal:
                    business_goals.append(goal)
            elif in_users and stripped.startswith("- "):
                user = stripped.removeprefix("- ").strip()
                if user:
                    users.append(user)
            elif in_constraints and stripped.startswith("- "):
                cst = stripped.removeprefix("- ").strip()
                if cst:
                    constraints.append(cst)

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

        if not features:
            seed_items = business_goals[:8] or self._split_intent_summary_to_feature_seeds(intent_summary)
            for index, seed in enumerate(seed_items, start=1):
                feature_name = self._feature_title_from_seed(seed, index=index)
                features.append(
                    {
                        "id": f"SF-{index:03d}",
                        "name": feature_name,
                        "goal": seed,
                        "functions": [
                            f"Deliver user-facing capability for {feature_name}",
                            f"Provide observable state transitions and outcome feedback for {feature_name}",
                        ],
                        "constraints": constraints[:6],
                        "users": users[:6],
                    }
                )

        return {
            "overview": intent_summary or "Loaded from docs/system-design.md",
            "system_features": features,
            "all_features": features,
            "intent_summary": intent_summary,
            "users": users,
            "constraints": constraints,
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

    def _split_intent_summary_to_feature_seeds(self, intent_summary: str) -> list[str]:
        text = str(intent_summary or "").strip()
        if not text:
            return []
        segments = re.split(r"[。.!?；;]|,|，", text)
        seeds: list[str] = []
        for segment in segments:
            item = segment.strip(" -")
            if len(item) < 6:
                continue
            if item not in seeds:
                seeds.append(item)
            if len(seeds) >= 6:
                break
        return seeds

    def _feature_title_from_seed(self, seed: str, *, index: int) -> str:
        text = str(seed or "").strip()
        if not text:
            return f"Feature {index}"
        if re.search(r"[\u4e00-\u9fff]", text):
            return text[:24]
        words = [w for w in re.split(r"[^a-zA-Z0-9]+", text) if w]
        if not words:
            return f"Feature {index}"
        title = " ".join(words[:6]).strip()
        return title[:64]

    def _run_architecture_review_rounds(
        self,
        *,
        context: SkillContext,
        product_design: dict[str, Any],
        system_requirements: dict[str, Any],
        min_rounds: int,
        max_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_design: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None
        total_rounds = self._clamp_review_rounds(min_rounds=min_rounds, max_rounds=max_rounds)

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
        if not isinstance(subsystems, list):
            subsystems = []

        if previous_review and previous_review.get("issues"):
            feedback = " | ".join(str(issue) for issue in previous_review.get("issues", [])[:3])
            for subsystem in subsystems:
                if feedback:
                    subsystem.setdefault("constraints", [])
                    if feedback not in subsystem["constraints"]:
                        subsystem["constraints"].append(feedback)

        feature_count = len(product_design.get("system_features", []))
        current_context = self._build_current_architecture_context(previous_design, previous_review)
        subsystem_summary = [
            {
                "id": subsystem.get("id", ""),
                "name": subsystem.get("name", ""),
                "english_name": subsystem.get("english_name", ""),
                "apis": [api.get("path", "") for api in subsystem.get("apis", [])[:3]],
            }
            for subsystem in subsystems[:8]
        ]
        architecture_scope = f" round:{round_index} reqs:{len(requirements)} features:{feature_count}"

        reuse_previous_diagram = self._should_reuse_architecture_diagram(
            previous_design=previous_design,
            previous_review=previous_review,
            round_index=round_index,
        )
        previous_diagram = str(previous_design.get("architecture_diagram", "")) if previous_design else ""
        diagram_guidance = (
            "You may reuse the previous Mermaid diagram exactly if topology is unchanged, "
            "but you must still return architecture_diagram.\n"
            f"Previous diagram (optional):\n{previous_diagram[:3000]}\n"
            if reuse_previous_diagram and previous_diagram
            else ""
        )
        llm_design = self._run_llm_json_segment(
            context=context,
            purpose=f"subagent:architecture_designer step:architecture_design.foundation{architecture_scope}",
            system_prompt=(
                "You are an architecture designer. Return JSON only with keys: "
                "design_goals (list[str]), principles (list[str]), architecture_overview (str), "
                "layering (list[str]), architecture_diagram (str).\n"
                "Rules for architecture_diagram:\n"
                "- Mermaid syntax starting with `flowchart TD` or `graph TD`\n"
                "- No markdown code fence\n"
                "- Max 50 lines\n"
                "- Max 3000 chars total\n"
                "- Show only major layers/components and key flows\n"
            ),
            user_prompt=(
                f"Round: {round_index}\n"
                f"Requirement count: {len(requirements)}\n"
                f"Feature count: {feature_count}\n"
                "Generate architecture goals/principles/overview/layering/diagram in one JSON object.\n\n"
                "Product design document:\n"
                f"{self._compact_json(product_design)}\n\n"
                "Subsystem draft (for context):\n"
                f"{self._compact_json(subsystem_summary)}\n\n"
                "Current architecture design document:\n"
                f"{current_context}\n\n"
                f"{diagram_guidance}"
            ),
            required_keys=["design_goals", "principles", "architecture_overview", "layering", "architecture_diagram"],
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
        previous_structure_context = ""
        if isinstance(previous_design, dict):
            previous_structure = {
                "subsystems": previous_design.get("subsystems", []),
                "components": previous_design.get("components", []),
                "sr_allocation": previous_design.get("sr_allocation", {}),
            }
            previous_structure_context = self._compact_json(previous_structure)
        structure_payload = self._run_llm_json_segment(
            context=context,
            purpose=f"subagent:architecture_designer step:architecture_design.structure{architecture_scope}",
            system_prompt=(
                "You are an architecture designer. Return JSON only with keys: subsystems, components, sr_allocation.\n"
                "Rules:\n"
                "- Design domain-meaningful subsystems (not generic 'service layer' or 'data layer').\n"
                "- subsystems: list[object] with keys: name, english_name, description, constraints, apis.\n"
                "- name may be Chinese or bilingual for documentation display.\n"
                "- english_name is REQUIRED and must be 1-3 English words (ASCII letters/numbers only), "
                "used for directories/module names.\n"
                "- each subsystem.apis item has keys: method, path, description.\n"
                "- components: list[object] with keys: name, type, subsystem_id_or_name, responsibilities.\n"
                "- Use subsystem_id, subsystem name, or subsystem english_name when referencing subsystem_id_or_name.\n"
                "- sr_allocation: object mapping subsystem ids/names to SR id lists.\n"
                "- An SR may be allocated to multiple related subsystems when "
                "cross-subsystem collaboration is required.\n"
                "- Every SR must be allocated to at least one subsystem.\n"
                "- Components must have concrete responsibilities tied to domain behavior.\n"
                "- Infer APIs/components from requirements and architecture context; do NOT use fixed templates "
                "like health+execute for every subsystem.\n"
            ),
            user_prompt=(
                f"Round: {round_index}\n"
                f"Requirements:\n{self._compact_json(requirements)}\n\n"
                f"Product design:\n{self._compact_json(product_design)}\n\n"
                f"Architecture overview:\n{str(llm_design.get('architecture_overview', ''))[:4000]}\n\n"
                f"Layering:\n{self._compact_json(layering)}\n\n"
                + (
                    f"Previous structure from last round (revise if needed):\n{previous_structure_context}\n\n"
                    if previous_structure_context
                    else ""
                )
                + "Generate a fresh domain-specific subsystem/component/API/SR-allocation structure.\n"
            ),
            required_keys=["subsystems", "components", "sr_allocation"],
        )
        subsystems = self._normalize_llm_architecture_subsystems(
            structure_payload.get("subsystems"),
            requirements=requirements,
        )
        sr_allocation = self._normalize_llm_architecture_sr_allocation(
            structure_payload.get("sr_allocation"),
            requirements=requirements,
            subsystems=subsystems,
        )
        components = self._normalize_llm_architecture_components(
            structure_payload.get("components"),
            subsystems=subsystems,
            sr_allocation=sr_allocation,
        )
        return {
            "round": round_index,
            "design_goals": design_goals,
            "principles": principles,
            "architecture_overview": str(llm_design.get("architecture_overview", "")).strip()
            or f"Architecture derived from {len(requirements)} SR items and {feature_count} product feature items.",
            "architecture_diagram": str(llm_design.get("architecture_diagram", "")).strip()
            or (
                "flowchart TD\n"
                "  Client[Client] --> Gateway[API Gateway]\n"
                "  Gateway --> App[Application Services]\n"
                "  App --> Domain[Domain Logic]\n"
                "  Domain --> Data[(Persistence)]\n"
            ),
            "layering": layering,
            "subsystems": subsystems,
            "components": components,
            "sr_allocation": sr_allocation,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _run_llm_json_segment(
        self,
        *,
        context: SkillContext,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        required_keys: list[str],
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        last_partial: dict[str, Any] = {}
        last_error: Exception | None = None
        for attempt in range(1, max(1, max_attempts) + 1):
            prompt = user_prompt.rstrip() + "\n\n" + self._json_schema_echo_prompt(required_keys=required_keys)
            if attempt > 1:
                missing = [key for key in required_keys if key not in last_partial]
                prompt += (
                    "\n\nRetry guidance:\n"
                    "- Previous response was incomplete or truncated.\n"
                    f"- You must include keys: {', '.join(required_keys)}.\n"
                    f"- Missing keys from previous response: {', '.join(missing) if missing else '(schema invalid)'}.\n"
                )
                if last_partial:
                    prompt += (
                        "- Continue from the partial response below and return a FULL valid JSON object "
                        "for this segment (not just prose).\n"
                        f"Partial response:\n{self._compact_json(last_partial)}\n"
                    )
                prompt += (
                    "- Rebuild the full JSON skeleton first, then fill values and return compact valid JSON only.\n"
                )
            try:
                payload = self._run_llm_json(
                    context=context,
                    purpose=purpose,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                )
            except Exception as exc:
                last_error = exc
                continue

            if isinstance(payload, dict):
                last_partial = payload
            if self._segment_payload_is_acceptable(payload, required_keys=required_keys):
                return payload
        missing = [key for key in required_keys if key not in last_partial]
        message = (
            f"LLM segment failed for {purpose}: invalid/incomplete JSON after {max(1, max_attempts)} attempts; "
            f"missing keys={missing or '(schema/content invalid)'}"
        )
        if last_partial:
            message += f"; partial={self._compact_json(last_partial)[:500]}"
        if last_error is not None:
            raise RuntimeError(message) from last_error
        raise RuntimeError(message)

    def _should_reuse_architecture_diagram(
        self,
        *,
        previous_design: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
    ) -> bool:
        if round_index <= 1 or not isinstance(previous_design, dict):
            return False
        diagram = str(previous_design.get("architecture_diagram", "")).strip()
        if len(diagram) < 30:
            return False
        if self._looks_truncated_text(diagram):
            return False
        issues = [str(x).lower() for x in (previous_review or {}).get("issues", []) if str(x).strip()]
        suggestions = [str(x).lower() for x in (previous_review or {}).get("suggestions", []) if str(x).strip()]
        review_text = " | ".join(issues + suggestions)
        if any(token in review_text for token in ("diagram", "flowchart", "mermaid", "topology")):
            return False
        return True

    def _segment_payload_is_acceptable(self, payload: dict[str, Any], *, required_keys: list[str]) -> bool:
        if not isinstance(payload, dict):
            return False

        for key in required_keys:
            if key not in payload:
                return False

        if "design_goals" in required_keys:
            goals = payload.get("design_goals")
            if not isinstance(goals, list) or not any(str(item).strip() for item in goals):
                return False
        if "principles" in required_keys:
            principles = payload.get("principles")
            if not isinstance(principles, list) or not any(str(item).strip() for item in principles):
                return False
        if "architecture_overview" in required_keys:
            overview = str(payload.get("architecture_overview", "")).strip()
            if len(overview) < 60:
                return False
            if self._looks_truncated_text(overview):
                return False
        if "layering" in required_keys:
            layering = payload.get("layering")
            if not isinstance(layering, list) or not any(str(item).strip() for item in layering):
                return False
        if "architecture_diagram" in required_keys:
            diagram = str(payload.get("architecture_diagram", "")).strip()
            if len(diagram) < 30:
                return False
            if len(diagram) > 5000:
                return False
            if self._looks_truncated_text(diagram):
                return False
            if not (
                diagram.startswith("flowchart ")
                or diagram.startswith("graph ")
                or diagram.startswith("flowchart\n")
                or diagram.startswith("graph\n")
            ):
                return False

        return True

    def _looks_truncated_text(self, text: str) -> bool:
        if not text:
            return True
        tail = text.rstrip()
        if tail.endswith((":", ",", "\\", "/", "|", "├", "└", "─", "┬", "┴", "│")):
            return True
        # Unbalanced markdown/code fences often indicate truncation.
        if tail.count("```") % 2 == 1:
            return True
        # Heuristic: abruptly cut in the middle of a quoted string phrase.
        if tail.count('"') % 2 == 1:
            return True
        return False

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
            purpose=(
                "subagent:architecture_reviewer step:architecture_review "
                f"round:{round_index} reqs:{len(requirements)} reviewers:{len(reviewer_instances)}"
            ),
            system_prompt=(
                "You are an architecture reviewer. Return JSON only with optional keys: "
                "summary (str), suggestions (list[str])."
            ),
            user_prompt=(
                (f"Round: {round_index}\nCurrent issues:\n- " + "\n- ".join(issues or ["(none)"]) + "\n")
                + "\n"
                + self._json_schema_echo_prompt(optional_keys=["summary", "suggestions"])
            ),
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
                    "Ensure every SR is mapped to at least one subsystem and "
                    "cross-subsystem SRs are explicitly shared.",
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
        src_dir.mkdir(parents=True, exist_ok=True)
        app_file = src_dir / "main.py"
        subsystem_modules = [
            self._subsystem_slug(subsystem, fallback=str(subsystem.get("id", "service")))
            for subsystem in architecture_design.get("subsystems", [])
        ]
        include_contract_lines = []
        for module in subsystem_modules:
            include_contract_lines.extend(
                [
                    f"    contracts.append({{'subsystem': '{module}', 'status': 'scaffolded'}})",
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

        index_file = src_dir / "__init__.py"
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
            subsystem_display = str(subsystem.get("name", subsystem_id))
            subsystem_slug = self._subsystem_slug(subsystem, fallback=subsystem_id)
            assignments[subsystem_id] = {
                "subsystem_architect": architect_pool[index % len(architect_pool)],
                "architecture_reviewer": reviewer_pool[index % len(reviewer_pool)],
                "subsystem": subsystem_display,
                "subsystem_english_name": str(subsystem.get("english_name", "")).strip() or subsystem_slug,
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
        max_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_design: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None
        total_rounds = self._clamp_review_rounds(min_rounds=min_rounds, max_rounds=max_rounds)

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
            components = self._select_architecture_components_for_subsystem(
                architecture_design=architecture_design,
                subsystem=subsystem,
            )

        fn_items = self._build_fn_items(sr_items, components)
        if previous_review and previous_review.get("issues"):
            comment = " | ".join(str(i) for i in previous_review.get("issues", [])[:2])
            for fn in fn_items:
                fn.setdefault("notes", [])
                if comment:
                    fn["notes"].append(f"Reviewer focus: {comment}")
        llm_detail = self._run_llm_json(
            context=context,
            purpose=(
                "subagent:subsystem_architect step:subsystem_detail_design "
                f"round:{round_index} subsystem:{self._purpose_token(str(subsystem.get('id', '')))} "
                f"owner:{self._purpose_token(str(assignment.get('subsystem_architect', '')))}"
            ),
            system_prompt=(
                "You are a subsystem architect. Return JSON only with optional keys: "
                "logic_architecture_goals (list[str]), design_strategy (list[str]), "
                "technology_choices (object with language/framework/storage), "
                "logic_architecture_views (list[object]), module_designs (list[object]), "
                "module_dependency_rules (list[str]), integration_flow_notes (list[str]).\n"
                "Rules for logic_architecture_views:\n"
                "- Prefer 3 views: layered_view, runtime_interaction_view, module_dependency_view.\n"
                "- Each view item keys: view_id, view_name, view_type, description, mermaid.\n"
                "- Mermaid must be valid text starting with flowchart/graph/sequenceDiagram.\n"
                "Rules for module_designs:\n"
                "- Each module item keys: module_name, file_name, responsibilities, "
                "depends_on_modules, classes, class_diagram_mermaid.\n"
                "- file_name must be snake_case Python filename ending with .py.\n"
                "- depends_on_modules must reference module_name values in module_designs (no unknown modules).\n"
                "- Each classes item keys: class_name, class_kind, purpose, "
                "attributes, methods, inherits, uses_classes.\n"
                "- class_diagram_mermaid must be Mermaid classDiagram text.\n"
                "- Module/class design should align semantically with SR/FN decomposition."
            ),
            user_prompt=(
                f"Subsystem: {subsystem.get('id', '')} {subsystem.get('name', '')}\n"
                f"Round: {round_index}\n"
                f"Assigned SR IDs: {', '.join(sr_ids)}\n"
                f"Subsystem APIs: {self._compact_json(subsystem.get('apis', []))}\n"
                f"Subsystem components: {self._compact_json(components)}\n"
                f"SR/FN breakdown draft: {self._compact_json(fn_items)}\n"
                "\n"
                + self._json_schema_echo_prompt(
                    optional_keys=[
                        "logic_architecture_goals",
                        "design_strategy",
                        "technology_choices",
                        "logic_architecture_views",
                        "module_designs",
                        "module_dependency_rules",
                        "integration_flow_notes",
                    ]
                )
            ),
        )

        module_designs = self._normalize_module_designs(
            value=llm_detail.get("module_designs"),
            subsystem=subsystem,
            fn_items=fn_items,
            components=components,
        )
        logic_architecture_views = self._normalize_logic_architecture_views(
            value=llm_detail.get("logic_architecture_views"),
            subsystem=subsystem,
            module_designs=module_designs,
            components=components,
        )
        sr_breakdown = self._build_module_based_sr_breakdown(sr_items=sr_items, module_designs=module_designs)

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
            "logic_architecture_views": logic_architecture_views,
            "module_designs": module_designs,
            "module_dependency_rules": self._as_str_list(
                llm_detail.get("module_dependency_rules"),
                fallback=[
                    "Higher-level orchestration modules may depend on domain modules, but avoid circular imports.",
                    "Model/schema-like classes should not depend on service orchestration modules.",
                ],
            ),
            "integration_flow_notes": self._as_str_list(
                llm_detail.get("integration_flow_notes"),
                fallback=[
                    "Use explicit module interfaces and dependency injection points for cross-module coordination.",
                ],
            ),
            "components": components,
            "apis": subsystem.get("apis", []),
            "technology_choices": self._normalize_technology_choices(llm_detail.get("technology_choices")),
            "sr_breakdown": sr_breakdown,
            "designer_response": self._build_designer_response(previous_review),
            "architecture_reference": architecture_design.get("architecture_overview", ""),
        }

    def _select_architecture_components_for_subsystem(
        self,
        *,
        architecture_design: dict[str, Any],
        subsystem: dict[str, Any],
    ) -> list[dict[str, Any]]:
        subsystem_id = str(subsystem.get("id", "")).strip()
        selected: list[dict[str, Any]] = []
        for item in architecture_design.get("components", []) if isinstance(architecture_design, dict) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("subsystem_id", "")).strip() != subsystem_id:
                continue
            selected.append(
                {
                    "id": str(item.get("id", "")),
                    "name": str(item.get("name", "")),
                    "type": str(item.get("type", "service")),
                    "responsibility": (
                        str((item.get("responsibilities") or [""])[0])
                        if isinstance(item.get("responsibilities"), list)
                        else str(item.get("responsibility", ""))
                    ),
                    "responsibilities": (
                        [str(x) for x in item.get("responsibilities", [])]
                        if isinstance(item.get("responsibilities"), list)
                        else []
                    ),
                }
            )
        return selected

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
        views = detail_design.get("logic_architecture_views", [])
        if not isinstance(views, list) or not views:
            issues.append("Missing logic_architecture_views for subsystem detail design.")
        module_designs = detail_design.get("module_designs", [])
        if not isinstance(module_designs, list) or not module_designs:
            issues.append("Missing module_designs for subsystem detail design.")
            module_designs = []
        known_modules: set[str] = set()
        for module in module_designs:
            if not isinstance(module, dict):
                continue
            module_name = str(module.get("module_name", "")).strip()
            if not module_name:
                issues.append("Module design missing module_name.")
                continue
            known_modules.add(module_name)
            classes = module.get("classes", [])
            if not isinstance(classes, list) or not classes:
                issues.append(f"Module {module_name} missing classes.")
            if not str(module.get("class_diagram_mermaid", "")).strip():
                issues.append(f"Module {module_name} missing class_diagram_mermaid.")
        for module in module_designs:
            if not isinstance(module, dict):
                continue
            module_name = str(module.get("module_name", "")).strip() or "UNKNOWN"
            deps = module.get("depends_on_modules", [])
            if not isinstance(deps, list):
                continue
            for dep in deps:
                dep_name = str(dep).strip()
                if dep_name and dep_name not in known_modules:
                    issues.append(f"Module {module_name} depends on unknown module {dep_name}.")

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
            purpose=(
                "subagent:architecture_reviewer step:subsystem_detail_review "
                f"round:{round_index} subsystem:{self._purpose_token(str(subsystem.get('id', '')))} "
                f"reviewer:{self._purpose_token(reviewer)}"
            ),
            system_prompt=(
                "You are an architecture reviewer. Return JSON only with optional keys: "
                "summary (str), suggestions (list[str])."
            ),
            user_prompt=(
                f"Subsystem: {subsystem.get('id', '')} {subsystem.get('name', '')}\n"
                f"Round: {round_index}\n"
                f"Issues:\n- "
                + "\n- ".join(issues or ["(none)"])
                + "\n"
                + "\n"
                + self._json_schema_echo_prompt(optional_keys=["summary", "suggestions"])
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
            module_name = self._subsystem_slug(subsystem, fallback=subsystem_id)
            subsystem_dir = src_dir / module_name
            subsystem_dir.mkdir(parents=True, exist_ok=True)

            detail = detail_designs.get(subsystem_id, {})
            module_designs = detail.get("module_designs", []) if isinstance(detail, dict) else []
            tech_choices = detail.get("technology_choices", {}) if isinstance(detail, dict) else {}
            language = str(tech_choices.get("language", "")).strip().lower() if isinstance(tech_choices, dict) else ""
            uses_python_modules = any(
                isinstance(item, dict) and str(item.get("file_name", "")).strip().lower().endswith(".py")
                for item in (module_designs if isinstance(module_designs, list) else [])
            )
            if "python" in language or uses_python_modules:
                init_path = subsystem_dir / "__init__.py"
                if not init_path.exists():
                    init_path.write_text('"""Generated subsystem package."""\n', encoding="utf-8")
                files.append(str(init_path))
            files.extend(
                self._generate_python_subsystem_module_skeletons(
                    subsystem_dir=subsystem_dir,
                    subsystem_slug=module_name,
                    module_designs=module_designs if isinstance(module_designs, list) else [],
                )
            )
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

    def _generate_python_subsystem_module_skeletons(
        self,
        *,
        subsystem_dir: Path,
        subsystem_slug: str,
        module_designs: list[dict[str, Any]],
    ) -> list[str]:
        files: list[str] = []
        if not module_designs:
            return files
        module_to_file: dict[str, str] = {}
        file_to_classes: dict[str, list[str]] = {}
        for module in module_designs:
            if not isinstance(module, dict):
                continue
            module_name = str(module.get("module_name", "")).strip()
            file_name = str(module.get("file_name", "")).strip()
            if not module_name or not file_name:
                continue
            module_to_file[module_name] = file_name
            class_names: list[str] = []
            for cls in module.get("classes", []) if isinstance(module.get("classes"), list) else []:
                if isinstance(cls, dict):
                    class_name = str(cls.get("class_name", "")).strip()
                    if class_name:
                        class_names.append(class_name)
            file_to_classes[file_name] = class_names

        for module in module_designs:
            if not isinstance(module, dict):
                continue
            module_name = str(module.get("module_name", "")).strip()
            file_name = str(module.get("file_name", "")).strip()
            if not module_name or not file_name:
                continue
            path = subsystem_dir / file_name
            lines = ["from __future__ import annotations", "", "from typing import Any"]
            import_lines = self._module_import_lines_from_design(
                module=module,
                module_to_file=module_to_file,
                file_to_classes=file_to_classes,
            )
            if import_lines:
                lines.extend(["", *import_lines])
            lines.extend(["", f'"""Subsystem module skeleton for {subsystem_slug}.{module_name}."""', ""])

            classes = module.get("classes", [])
            if isinstance(classes, list) and classes:
                for cls in classes:
                    if not isinstance(cls, dict):
                        continue
                    lines.extend(self._render_python_class_skeleton(cls))
                    lines.append("")
            else:
                class_name = "".join(part.capitalize() for part in module_name.split("_") if part) or "Module"
                lines.extend(
                    [
                        f"class {class_name}Service:",
                        '    """Generated subsystem skeleton class."""',
                        "",
                        "    def execute(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:",
                        '        raise NotImplementedError("Generated subsystem skeleton")',
                        "",
                    ]
                )

            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            files.append(str(path))
        return files

    def _module_import_lines_from_design(
        self,
        *,
        module: dict[str, Any],
        module_to_file: dict[str, str],
        file_to_classes: dict[str, list[str]],
    ) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()
        deps = module.get("depends_on_modules", [])
        if not isinstance(deps, list):
            return lines
        for dep in deps:
            dep_name = str(dep).strip()
            if not dep_name:
                continue
            dep_file = module_to_file.get(dep_name, "")
            if not dep_file:
                continue
            dep_stem = Path(dep_file).stem
            classes = file_to_classes.get(dep_file, [])
            stmt = f"from .{dep_stem} import {classes[0]}" if classes else f"from . import {dep_stem}"
            if stmt in seen:
                continue
            seen.add(stmt)
            lines.append(stmt)
        return lines

    def _render_python_class_skeleton(self, cls: dict[str, Any]) -> list[str]:
        class_name = str(cls.get("class_name", "")).strip() or "GeneratedClass"
        inherits = (
            [str(x).strip() for x in cls.get("inherits", []) if str(x).strip()]
            if isinstance(cls.get("inherits"), list)
            else []
        )
        base_clause = f"({', '.join(inherits)})" if inherits else ""
        lines = [f"class {class_name}{base_clause}:"]
        purpose = str(cls.get("purpose", "")).strip() or "Generated subsystem skeleton class."
        lines.append(f'    """{purpose}"""')
        methods = cls.get("methods", [])
        if not isinstance(methods, list) or not methods:
            lines.append("    pass")
            return lines
        for method in methods:
            if not isinstance(method, dict):
                continue
            method_name = str(method.get("name", "")).strip()
            if not method_name:
                continue
            params = method.get("params", [])
            rendered_params = ["self"]
            if isinstance(params, list):
                for p in params:
                    if not isinstance(p, dict):
                        continue
                    p_name = str(p.get("name", "")).strip()
                    if not p_name or p_name == "self":
                        continue
                    p_type = str(p.get("type", "Any")).strip() or "Any"
                    rendered_params.append(f"{p_name}: {p_type}")
            returns = str(method.get("returns", "Any")).strip() or "Any"
            lines.extend(
                [
                    "",
                    f"    def {method_name}({', '.join(rendered_params)}) -> {returns}:",
                    '        raise NotImplementedError("Generated subsystem skeleton")',
                ]
            )
        return lines

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
        allocation = architecture_design.get("sr_allocation", {})
        sr_to_subsystems: dict[str, list[str]] = {}
        for subsystem_id, sr_ids in allocation.items():
            sid = str(subsystem_id)
            for sr_id in sr_ids if isinstance(sr_ids, list) else []:
                key = str(sr_id).strip()
                if not key:
                    continue
                sr_to_subsystems.setdefault(key, [])
                if sid not in sr_to_subsystems[key]:
                    sr_to_subsystems[key].append(sid)
        for sr in self._normalize_requirements(system_requirements.get("requirements", [])):
            sr_id = str(sr.get("id", ""))
            subsystem_ids = sr_to_subsystems.get(sr_id) or [
                self._find_primary_subsystem_for_sr(sr_id, architecture_design)
            ]
            for subsystem_id in subsystem_ids:
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
            "allocation": allocation,
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

    def _subsystem_description_from_label(self, label: str) -> str:
        text = str(label).strip()
        return f"Subsystem boundary for {text}, aligned to the architecture layering and service responsibilities."

    def _normalize_llm_architecture_subsystems(
        self,
        value: Any,
        *,
        requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise RuntimeError("LLM architecture structure missing valid subsystems list")
        normalized: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name", item.get("subsystem", ""))).strip()
            english_name = self._normalize_subsystem_english_name(item.get("english_name"), fallback_name=raw_name)
            slug = self._slugify(english_name)
            if not slug or slug in seen_names:
                continue
            seen_names.add(slug)
            apis = self._normalize_llm_subsystem_apis(item.get("apis"), subsystem_name=raw_name or slug)
            if len(apis) < 2:
                raise RuntimeError(f"LLM subsystem `{raw_name or slug}` has insufficient API definitions")
            description = str(item.get("description", item.get("boundary", ""))).strip()
            if len(description) < 20:
                description = self._subsystem_description_from_label(raw_name or slug)
            constraints = self._as_str_list(item.get("constraints"), fallback=[])
            display_name = raw_name or english_name
            normalized.append(
                {
                    "id": f"SUBSYS-{len(normalized) + 1:03d}",
                    "name": display_name,
                    "english_name": english_name,
                    "description": description,
                    "constraints": constraints,
                    "apis": apis,
                }
            )
        if not normalized:
            raise RuntimeError("LLM architecture structure produced no valid subsystems")
        if len(normalized) == 1 and len(requirements) > 2:
            raise RuntimeError("LLM architecture structure collapsed to one subsystem for multi-SR system")
        if len(normalized) > 8:
            normalized = normalized[:8]
            for idx, subsystem in enumerate(normalized, start=1):
                subsystem["id"] = f"SUBSYS-{idx:03d}"
        return normalized

    def _normalize_subsystem_english_name(self, value: Any, *, fallback_name: str = "") -> str:
        raw = str(value or "").strip()
        candidate = raw or str(fallback_name or "").strip()
        if not candidate:
            raise RuntimeError("LLM subsystem missing english_name")

        # Accept spaces / hyphens / underscores, normalize to 1-3 ASCII words.
        words = [w for w in re.split(r"[\s_-]+", candidate) if w]
        cleaned_words: list[str] = []
        for word in words:
            cleaned = "".join(ch for ch in word.lower() if ch.isascii() and ch.isalnum())
            if cleaned:
                cleaned_words.append(cleaned)
        if not cleaned_words:
            raise RuntimeError(f"Invalid subsystem english_name: {candidate!r}")
        if len(cleaned_words) > 3:
            cleaned_words = cleaned_words[:3]
        return " ".join(cleaned_words)

    def _subsystem_slug(self, subsystem: dict[str, Any], *, fallback: str = "subsystem") -> str:
        if isinstance(subsystem, dict):
            english_name = str(subsystem.get("english_name", "")).strip()
            if english_name:
                slug = self._slugify(english_name)
                if slug:
                    return slug
            name = str(subsystem.get("name", "")).strip()
            if name:
                slug = self._slugify(name)
                if slug:
                    return slug
        return self._slugify(fallback)

    def _normalize_llm_subsystem_apis(self, value: Any, *, subsystem_name: str) -> list[dict[str, str]]:
        apis: list[dict[str, str]] = []
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                method = str(item.get("method", "GET")).strip().upper() or "GET"
                if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    method = "POST"
                path = str(item.get("path", "")).strip()
                if not path.startswith("/"):
                    path = f"/{path}" if path else ""
                description = str(item.get("description", item.get("desc", ""))).strip()
                if not path:
                    continue
                if len(description) < 8:
                    description = f"{method} {path} for {subsystem_name}"
                apis.append({"method": method, "path": path, "description": description})
        # Deduplicate by method+path.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, str]] = []
        for api in apis:
            key = (api["method"], api["path"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(api)
        return deduped

    def _normalize_llm_architecture_sr_allocation(
        self,
        value: Any,
        *,
        requirements: list[dict[str, Any]],
        subsystems: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise RuntimeError("LLM architecture structure missing valid sr_allocation object")
        required_ids = [str(item.get("id", "")).strip() for item in requirements if str(item.get("id", "")).strip()]
        required_set = set(required_ids)
        subsystem_ids = {str(s.get("id", "")) for s in subsystems}
        subsystem_names: dict[str, str] = {}
        for s in subsystems:
            sid = str(s.get("id", ""))
            for key in (
                str(s.get("name", "")).strip(),
                str(s.get("english_name", "")).strip(),
                self._subsystem_slug(s, fallback=sid),
            ):
                if key:
                    subsystem_names[key.lower()] = sid
        allocation: dict[str, list[str]] = {str(s.get("id", "")): [] for s in subsystems}

        seen_any: set[str] = set()
        for raw_key, sr_ids in value.items():
            key = str(raw_key).strip()
            normalized_key = subsystem_names.get(key.lower(), key)
            if normalized_key not in subsystem_ids:
                continue
            if not isinstance(sr_ids, list):
                continue
            for sr_id in sr_ids:
                sr = str(sr_id).strip()
                if sr not in required_set:
                    continue
                seen_any.add(sr)
                if sr not in allocation[normalized_key]:
                    allocation[normalized_key].append(sr)

        missing = [sr_id for sr_id in required_ids if sr_id not in seen_any]
        if missing:
            raise RuntimeError(f"LLM sr_allocation missing SR assignments: {', '.join(missing)}")
        return allocation

    def _normalize_llm_architecture_components(
        self,
        value: Any,
        *,
        subsystems: list[dict[str, Any]],
        sr_allocation: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise RuntimeError("LLM architecture structure missing valid components list")
        subsystem_ids = {str(s.get("id", "")) for s in subsystems}
        subsystem_names: dict[str, str] = {}
        for s in subsystems:
            sid = str(s.get("id", ""))
            for key in (
                str(s.get("name", "")).strip(),
                str(s.get("english_name", "")).strip(),
                self._subsystem_slug(s, fallback=sid),
            ):
                if key:
                    subsystem_names[key.lower()] = sid
        per_subsystem_count: dict[str, int] = {sid: 0 for sid in subsystem_ids}
        components: list[dict[str, Any]] = []

        for item in value:
            if not isinstance(item, dict):
                continue
            raw_sub = str(item.get("subsystem_id", item.get("subsystem", item.get("subsystem_id_or_name", "")))).strip()
            subsystem_id = subsystem_names.get(raw_sub.lower(), raw_sub)
            if subsystem_id not in subsystem_ids:
                continue
            name = self._slugify(str(item.get("name", "")).strip())
            if not name:
                continue
            comp_type = str(item.get("type", "service")).strip().lower() or "service"
            if comp_type not in {"service", "repository", "adapter", "worker", "component", "gateway"}:
                comp_type = "service"
            responsibilities = self._as_str_list(item.get("responsibilities"), fallback=[])
            if not responsibilities:
                one = str(item.get("responsibility", "")).strip()
                if one:
                    responsibilities = [one]
            if not responsibilities:
                raise RuntimeError(f"LLM component `{name}` missing responsibilities")
            per_subsystem_count[subsystem_id] = per_subsystem_count.get(subsystem_id, 0) + 1
            comp_index = per_subsystem_count[subsystem_id]
            components.append(
                {
                    "id": f"COMP-{subsystem_id}-{comp_index:02d}",
                    "name": name,
                    "type": comp_type,
                    "subsystem_id": subsystem_id,
                    "responsibilities": responsibilities[:6],
                    "sr_ids": list(sr_allocation.get(subsystem_id, [])),
                }
            )

        if not components:
            raise RuntimeError("LLM architecture structure produced no valid components")
        missing_subsystems = [sid for sid, count in per_subsystem_count.items() if count == 0]
        if missing_subsystems:
            raise RuntimeError(
                "LLM architecture structure produced no components for subsystems: "
                + ", ".join(sorted(missing_subsystems))
            )
        return components

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

    def _build_module_based_sr_breakdown(
        self,
        *,
        sr_items: list[dict[str, Any]],
        module_designs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        breakdown: list[dict[str, Any]] = []
        normalized_modules = [m for m in module_designs if isinstance(m, dict)]
        for sr in sr_items:
            sr_id = str(sr.get("id", "")).strip() or "SR-UNKNOWN"
            sr_title = str(sr.get("title", sr.get("requirement_overview", ""))).strip() or sr_id
            functions: list[dict[str, Any]] = []
            for idx, module in enumerate(normalized_modules, start=1):
                module_name = str(module.get("module_name", f"module_{idx}")).strip() or f"module_{idx}"
                responsibilities = (
                    [str(x).strip() for x in module.get("responsibilities", [])]
                    if isinstance(module.get("responsibilities"), list)
                    else []
                )
                desc = f"{module_name} module collaborates to deliver {sr_title}" + (
                    f"; focus: {responsibilities[0]}" if responsibilities else ""
                )
                spec = (
                    "Implement module responsibilities for the SR, expose callable module/class API, "
                    "and coordinate with dependent modules according to the subsystem design."
                )
                functions.append(
                    {
                        "id": f"FN-{sr_id}-{idx:02d}",
                        "source_sr": sr_id,
                        "component": module_name,
                        "module": module_name,
                        "file_name": str(module.get("file_name", "")),
                        "description": desc,
                        "spec": spec,
                    }
                )
            breakdown.append({"sr_id": sr_id, "title": sr_title, "functions": functions})
        return breakdown

    def _normalize_logic_architecture_views(
        self,
        *,
        value: Any,
        subsystem: dict[str, Any],
        module_designs: list[dict[str, Any]],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                view_type = str(item.get("view_type", "")).strip() or "module_dependency_view"
                mermaid = str(item.get("mermaid", "")).strip()
                if not mermaid:
                    continue
                rows.append(
                    {
                        "view_id": str(item.get("view_id", view_type)).strip() or view_type,
                        "view_name": str(item.get("view_name", view_type)).strip() or view_type,
                        "view_type": view_type,
                        "description": str(item.get("description", "")).strip(),
                        "mermaid": mermaid,
                    }
                )
        if rows:
            return rows
        return self._default_logic_architecture_views(
            subsystem=subsystem,
            module_designs=module_designs,
            components=components,
        )

    def _default_logic_architecture_views(
        self,
        *,
        subsystem: dict[str, Any],
        module_designs: list[dict[str, Any]],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        subsystem_name = str(subsystem.get("name", subsystem.get("id", "subsystem")))
        component_names = [
            str(c.get("name", "")) for c in components if isinstance(c, dict) and str(c.get("name", "")).strip()
        ]
        module_names = [
            str(m.get("module_name", ""))
            for m in module_designs
            if isinstance(m, dict) and str(m.get("module_name", "")).strip()
        ]
        layered_lines = [
            "flowchart TB",
            "  Client[Client / Upstream]",
            "  API[Interface Layer]",
            "  App[Application Services]",
            "  Domain[Domain Models]",
            "  Infra[Infrastructure Adapters]",
            "  Client --> API --> App --> Domain",
            "  App --> Infra",
        ]
        if component_names:
            for idx, name in enumerate(component_names[:6], start=1):
                slug = self._slugify(name) or f"comp_{idx}"
                layered_lines.append(f"  C{idx}[{slug}]:::comp")
                layered_lines.append(f"  App --> C{idx}")
            layered_lines.append("  classDef comp fill:#eef,stroke:#99c")

        dep_lines = ["flowchart LR"]
        if module_names:
            for mod in module_names:
                dep_lines.append(f"  {self._slugify(mod) or 'module'}[{mod}]")
            for module in module_designs:
                if not isinstance(module, dict):
                    continue
                src = str(module.get("module_name", "")).strip()
                if not src:
                    continue
                for dst in (
                    module.get("depends_on_modules", []) if isinstance(module.get("depends_on_modules"), list) else []
                ):
                    dst_text = str(dst).strip()
                    if not dst_text:
                        continue
                    dep_lines.append(f"  {self._slugify(src)} --> {self._slugify(dst_text)}")
        else:
            dep_lines.extend(["  module_a[Module A]", "  module_b[Module B]", "  module_a --> module_b"])

        seq_lines = [
            "sequenceDiagram",
            "  participant Caller as Upstream",
            "  participant Entry as Entry Module",
            "  participant Core as Core Service",
            "  participant Repo as Repository/Adapter",
            "  Caller->>Entry: invoke subsystem capability",
            "  Entry->>Core: validate and orchestrate",
            "  Core->>Repo: load/save data",
            "  Repo-->>Core: data/result",
            "  Core-->>Entry: response DTO/domain result",
            "  Entry-->>Caller: subsystem response",
        ]
        return [
            {
                "view_id": "layered_view",
                "view_name": f"{subsystem_name} Layered View",
                "view_type": "layered_view",
                "description": "Shows subsystem layers and major interaction direction.",
                "mermaid": "\n".join(layered_lines),
            },
            {
                "view_id": "runtime_interaction_view",
                "view_name": f"{subsystem_name} Runtime Interaction View",
                "view_type": "runtime_interaction_view",
                "description": "Shows runtime call flow among entry/core/infrastructure elements.",
                "mermaid": "\n".join(seq_lines),
            },
            {
                "view_id": "module_dependency_view",
                "view_name": f"{subsystem_name} Module Dependency View",
                "view_type": "module_dependency_view",
                "description": "Shows planned module-level dependencies inside the subsystem.",
                "mermaid": "\n".join(dep_lines),
            },
        ]

    def _normalize_module_designs(
        self,
        *,
        value: Any,
        subsystem: dict[str, Any],
        fn_items: list[dict[str, Any]],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return self._default_module_designs(subsystem=subsystem, fn_items=fn_items, components=components)
        rows: list[dict[str, Any]] = []
        known_names: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            module_name = self._slugify(str(item.get("module_name", "")).strip())
            file_name_raw = str(item.get("file_name", "")).strip()
            file_stem = self._slugify(Path(file_name_raw or module_name or "module").stem)
            if not module_name and file_stem:
                module_name = file_stem
            if not module_name:
                continue
            file_name = f"{file_stem or module_name}.py"
            if module_name in known_names:
                continue
            known_names.add(module_name)
            rows.append(
                {
                    "module_name": module_name,
                    "file_name": file_name,
                    "responsibilities": self._as_str_list(
                        item.get("responsibilities"),
                        fallback=[f"Implement module {module_name} responsibilities for assigned SRs."],
                    ),
                    "depends_on_modules": [self._slugify(str(x)) for x in item.get("depends_on_modules", [])]
                    if isinstance(item.get("depends_on_modules"), list)
                    else [],
                    "classes": self._normalize_module_classes(item.get("classes"), module_name=module_name),
                    "class_diagram_mermaid": str(item.get("class_diagram_mermaid", "")).strip(),
                }
            )
        if not rows:
            return self._default_module_designs(subsystem=subsystem, fn_items=fn_items, components=components)

        valid_names = {str(row.get("module_name", "")) for row in rows}
        for row in rows:
            deps = row.get("depends_on_modules", [])
            deps_list = deps if isinstance(deps, list) else []
            row["depends_on_modules"] = [
                d
                for d in (self._slugify(str(x)) for x in deps_list)
                if d and d in valid_names and d != row["module_name"]
            ]
            if not str(row.get("class_diagram_mermaid", "")).strip():
                row["class_diagram_mermaid"] = self._build_default_class_diagram_mermaid(
                    module_name=str(row["module_name"]),
                    classes=row.get("classes", []),
                )
        return rows

    def _normalize_module_classes(self, value: Any, *, module_name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                class_name = str(item.get("class_name", "")).strip()
                if not class_name:
                    continue
                rows.append(
                    {
                        "class_name": class_name,
                        "class_kind": str(item.get("class_kind", "class")).strip() or "class",
                        "purpose": str(item.get("purpose", "")).strip() or f"Support {module_name} behaviors.",
                        "attributes": self._normalize_class_attributes(item.get("attributes")),
                        "methods": self._normalize_class_methods(item.get("methods")),
                        "inherits": [str(x).strip() for x in item.get("inherits", []) if str(x).strip()]
                        if isinstance(item.get("inherits"), list)
                        else [],
                        "uses_classes": [str(x).strip() for x in item.get("uses_classes", []) if str(x).strip()]
                        if isinstance(item.get("uses_classes"), list)
                        else [],
                    }
                )
        if rows:
            return rows
        class_base = "".join(part.capitalize() for part in module_name.split("_") if part) or "Module"
        return [
            {
                "class_name": f"{class_base}Service",
                "class_kind": "class",
                "purpose": f"Implements {module_name} orchestration and business interactions.",
                "attributes": [{"name": "logger", "type": "Any", "visibility": "-", "description": "Runtime logger"}],
                "methods": [
                    {
                        "name": "execute",
                        "params": [{"name": "input_data", "type": "dict[str, Any] | None"}],
                        "returns": "dict[str, Any]",
                        "visibility": "+",
                        "description": "Execute module use case and return standard response payload.",
                    }
                ],
                "inherits": [],
                "uses_classes": [],
            }
        ]

    def _normalize_class_attributes(self, value: Any) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                rows.append(
                    {
                        "name": name,
                        "type": str(item.get("type", "Any")).strip() or "Any",
                        "visibility": str(item.get("visibility", "-")).strip() or "-",
                        "description": str(item.get("description", "")).strip(),
                    }
                )
        return rows

    def _normalize_class_methods(self, value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                params = item.get("params", [])
                norm_params = []
                if isinstance(params, list):
                    for p in params:
                        if not isinstance(p, dict):
                            continue
                        p_name = str(p.get("name", "")).strip()
                        if not p_name:
                            continue
                        norm_params.append({"name": p_name, "type": str(p.get("type", "Any")).strip() or "Any"})
                rows.append(
                    {
                        "name": name,
                        "params": norm_params,
                        "returns": str(item.get("returns", "Any")).strip() or "Any",
                        "visibility": str(item.get("visibility", "+")).strip() or "+",
                        "description": str(item.get("description", "")).strip(),
                    }
                )
        return rows

    def _default_module_designs(
        self,
        *,
        subsystem: dict[str, Any],
        fn_items: list[dict[str, Any]],
        components: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        component_by_name = {
            self._slugify(str(c.get("name", ""))): c
            for c in components
            if isinstance(c, dict) and str(c.get("name", "")).strip()
        }
        for fn in fn_items:
            if not isinstance(fn, dict):
                continue
            comp_name = self._slugify(str(fn.get("component", "")))
            module_name = comp_name or self._slugify(str(fn.get("id", ""))) or "module"
            if module_name in seen:
                continue
            seen.add(module_name)
            comp = component_by_name.get(module_name, {})
            class_base = "".join(part.capitalize() for part in module_name.split("_") if part) or "Module"
            classes = [
                {
                    "class_name": f"{class_base}Service",
                    "class_kind": "class",
                    "purpose": str(comp.get("responsibility", "")).strip()
                    or f"Implements {module_name} responsibilities for subsystem {subsystem.get('id', '')}.",
                    "attributes": [
                        {"name": "logger", "type": "Any", "visibility": "-", "description": "Runtime logger"}
                    ],
                    "methods": [
                        {
                            "name": "execute",
                            "params": [{"name": "input_data", "type": "dict[str, Any] | None"}],
                            "returns": "dict[str, Any]",
                            "visibility": "+",
                            "description": "Execute primary use case.",
                        }
                    ],
                    "inherits": [],
                    "uses_classes": [],
                }
            ]
            rows.append(
                {
                    "module_name": module_name,
                    "file_name": f"{module_name}.py",
                    "responsibilities": [
                        str(comp.get("responsibility", "")).strip() or f"Handle {module_name} operations."
                    ],
                    "depends_on_modules": [],
                    "classes": classes,
                    "class_diagram_mermaid": self._build_default_class_diagram_mermaid(
                        module_name=module_name,
                        classes=classes,
                    ),
                }
            )
        # Add simple chain dependencies to ensure non-isolated references in generated scaffold.
        for idx, row in enumerate(rows):
            if idx > 0:
                row["depends_on_modules"] = [str(rows[idx - 1]["module_name"])]
                classes = row.get("classes", [])
                if isinstance(classes, list) and classes and isinstance(classes[0], dict):
                    uses = classes[0].get("uses_classes")
                    if not isinstance(uses, list):
                        uses = []
                        classes[0]["uses_classes"] = uses
                    prev_classes = rows[idx - 1].get("classes", [])
                    if isinstance(prev_classes, list) and prev_classes and isinstance(prev_classes[0], dict):
                        prev_class = str(prev_classes[0].get("class_name", "")).strip()
                        if prev_class and prev_class not in uses:
                            uses.append(prev_class)
                row["class_diagram_mermaid"] = self._build_default_class_diagram_mermaid(
                    module_name=str(row["module_name"]),
                    classes=row.get("classes", []),
                )
        return rows

    def _build_default_class_diagram_mermaid(self, *, module_name: str, classes: Any) -> str:
        lines = ["classDiagram"]
        for item in classes if isinstance(classes, list) else []:
            if not isinstance(item, dict):
                continue
            class_name = str(item.get("class_name", "")).strip()
            if not class_name:
                continue
            lines.append(f"  class {class_name} {{")
            for attr in item.get("attributes", []) if isinstance(item.get("attributes"), list) else []:
                if not isinstance(attr, dict):
                    continue
                a_name = str(attr.get("name", "")).strip()
                if not a_name:
                    continue
                a_type = str(attr.get("type", "Any")).strip() or "Any"
                lines.append(f"    {a_type} {a_name}")
            for method in item.get("methods", []) if isinstance(item.get("methods"), list) else []:
                if not isinstance(method, dict):
                    continue
                m_name = str(method.get("name", "")).strip()
                if not m_name:
                    continue
                m_ret = str(method.get("returns", "Any")).strip() or "Any"
                lines.append(f"    {m_name}() {m_ret}")
            lines.append("  }")
            for parent in item.get("inherits", []) if isinstance(item.get("inherits"), list) else []:
                p = str(parent).strip()
                if p:
                    lines.append(f"  {p} <|-- {class_name}")
            for used in item.get("uses_classes", []) if isinstance(item.get("uses_classes"), list) else []:
                u = str(used).strip()
                if u:
                    lines.append(f"  {class_name} ..> {u}")
        if len(lines) == 1:
            base = "".join(part.capitalize() for part in module_name.split("_") if part) or "Module"
            lines.extend(
                [f"  class {base}Service", f"  class {base}Repository", f"  {base}Service ..> {base}Repository"]
            )
        return "\n".join(lines)

    def _render_mermaid_block(self, diagram: str) -> list[str]:
        text = str(diagram or "").strip()
        if not text:
            return ["```mermaid", "flowchart LR", "  A[Empty] --> B[Diagram]", "```"]
        return ["```mermaid", text, "```"]

    def _build_overall_architecture_c4_diagram(self, architecture_design: dict[str, Any]) -> str:
        lines = [
            "C4Container",
            "title System Architecture (C4 Container View)",
            'Person(user, "User", "Primary end user / operator")',
            'System_Boundary(app, "Application System") {',
        ]
        subsystems = [s for s in architecture_design.get("subsystems", []) if isinstance(s, dict)]
        for idx, subsystem in enumerate(subsystems, start=1):
            sid = str(subsystem.get("id", f"SUBSYS-{idx:03d}"))
            name = str(subsystem.get("name", sid))
            desc = str(subsystem.get("description", "")).strip() or f"Subsystem {sid}"
            alias = f"s{idx}"
            tech = "Python module set"
            safe_desc = desc.replace('"', "'")
            safe_name = name.replace('"', "'")
            lines.append(f'  Container({alias}, "{safe_name}", "{tech}", "{safe_desc}")')
        lines.append("}")
        for idx, _ in enumerate(subsystems, start=1):
            lines.append(f'Rel(user, s{idx}, "Uses related capabilities")')
        allocation = architecture_design.get("sr_allocation", {}) if isinstance(architecture_design, dict) else {}
        sr_to_subs: dict[str, list[str]] = {}
        alias_by_sid = {str(s.get("id", "")): f"s{i}" for i, s in enumerate(subsystems, start=1)}
        for sid, sr_ids in allocation.items():
            for sr_id in sr_ids if isinstance(sr_ids, list) else []:
                key = str(sr_id).strip()
                if not key:
                    continue
                sr_to_subs.setdefault(key, [])
                if str(sid) not in sr_to_subs[key]:
                    sr_to_subs[key].append(str(sid))
        for sr_id, sids in sr_to_subs.items():
            if len(sids) < 2:
                continue
            for left, right in zip(sids, sids[1:]):
                l_alias = alias_by_sid.get(left)
                r_alias = alias_by_sid.get(right)
                if l_alias and r_alias:
                    lines.append(f'Rel({l_alias}, {r_alias}, "Collaborates for {sr_id}")')
        return "\n".join(lines)

    def _describe_subsystem_dependencies(self, architecture_design: dict[str, Any]) -> list[str]:
        subsystems = [s for s in architecture_design.get("subsystems", []) if isinstance(s, dict)]
        allocation = architecture_design.get("sr_allocation", {}) if isinstance(architecture_design, dict) else {}
        sr_to_subs: dict[str, list[str]] = {}
        for sid, sr_ids in allocation.items():
            for sr_id in sr_ids if isinstance(sr_ids, list) else []:
                sr_key = str(sr_id).strip()
                if not sr_key:
                    continue
                sr_to_subs.setdefault(sr_key, [])
                if str(sid) not in sr_to_subs[sr_key]:
                    sr_to_subs[sr_key].append(str(sid))
        lines: list[str] = []
        for subsystem in subsystems:
            sid = str(subsystem.get("id", ""))
            name = str(subsystem.get("name", sid))
            desc = str(subsystem.get("description", "")).strip() or "Provides subsystem capabilities."
            apis = subsystem.get("apis", []) if isinstance(subsystem.get("apis"), list) else []
            api_summary = (
                ", ".join(
                    f"{str(api.get('method', 'GET')).upper()} {str(api.get('path', '/'))}"
                    for api in apis[:4]
                    if isinstance(api, dict)
                )
                or "no explicit APIs yet"
            )
            shared_srs = [sr for sr, sids in sr_to_subs.items() if sid in sids and len(sids) > 1]
            dependency_note = (
                f"Cross-subsystem collaboration required for SRs: {', '.join(shared_srs)}."
                if shared_srs
                else "Primarily handles SRs within its own boundary."
            )
            lines.append(f"- `{sid}` {name}: {desc} Exposed interfaces include {api_summary}. {dependency_note}")
        return lines or ["- (none)"]

    def _reverse_sr_allocation(self, architecture_design: dict[str, Any]) -> dict[str, list[str]]:
        sr_to_subsystems: dict[str, list[str]] = {}
        allocation = architecture_design.get("sr_allocation", {}) if isinstance(architecture_design, dict) else {}
        for subsystem_id, sr_ids in allocation.items():
            sid = str(subsystem_id).strip()
            for sr_id in sr_ids if isinstance(sr_ids, list) else []:
                sr = str(sr_id).strip()
                if not sr:
                    continue
                sr_to_subsystems.setdefault(sr, [])
                if sid not in sr_to_subsystems[sr]:
                    sr_to_subsystems[sr].append(sid)
        return sr_to_subsystems

    def _build_cross_subsystem_sr_sequence_diagram(
        self,
        *,
        sr_id: str,
        subsystem_ids: list[str],
        subsystem_names: dict[str, str],
    ) -> str:
        lines = ["sequenceDiagram", "  autonumber", "  actor User as User"]
        for sid in subsystem_ids:
            alias = self._slugify(sid) or "subsystem"
            label = subsystem_names.get(sid, sid).replace('"', "'")
            lines.append(f"  participant {alias} as {label}")
        if subsystem_ids:
            first = self._slugify(subsystem_ids[0]) or "subsystem"
            lines.append(f"  User->>{first}: Trigger {sr_id}")
            for left, right in zip(subsystem_ids, subsystem_ids[1:]):
                left_alias = self._slugify(left) or "left"
                right_alias = self._slugify(right) or "right"
                lines.append(f"  {left_alias}->>{right_alias}: Request capability for {sr_id}")
                lines.append(f"  {right_alias}-->>{left_alias}: Return result/status")
            lines.append(f"  {first}-->>User: Aggregate response for {sr_id}")
        return "\n".join(lines)

    def _build_subsystem_component_c4_diagram(
        self,
        *,
        subsystem: dict[str, Any],
        module_designs: list[dict[str, Any]],
    ) -> str:
        subsystem_name = str(subsystem.get("name", subsystem.get("id", "Subsystem"))).replace('"', "'")
        lines = ["C4Component", f"title {subsystem_name} Subsystem (C4 Component View)"]
        lines.append('Container_Boundary(subsys, "Subsystem") {')
        alias_by_module: dict[str, str] = {}
        for idx, module in enumerate(module_designs, start=1):
            if not isinstance(module, dict):
                continue
            module_name = str(module.get("module_name", f"module_{idx}")).strip() or f"module_{idx}"
            alias = f"m{idx}"
            alias_by_module[module_name] = alias
            file_name = str(module.get("file_name", f"{module_name}.py"))
            responsibilities = (
                ", ".join([str(x) for x in module.get("responsibilities", [])[:2]])
                if isinstance(module.get("responsibilities"), list)
                else ""
            )
            desc = (responsibilities or "Module responsibilities").replace('"', "'")
            lines.append(f'  Component({alias}, "{module_name}", "{file_name}", "{desc}")')
        lines.append("}")
        for module in module_designs:
            if not isinstance(module, dict):
                continue
            src_name = str(module.get("module_name", "")).strip()
            src_alias = alias_by_module.get(src_name)
            if not src_alias:
                continue
            for dep in (
                module.get("depends_on_modules", []) if isinstance(module.get("depends_on_modules"), list) else []
            ):
                dep_alias = alias_by_module.get(str(dep).strip())
                if dep_alias and dep_alias != src_alias:
                    lines.append(f'Rel({src_alias}, {dep_alias}, "depends on")')
        return "\n".join(lines)

    def _build_module_api_rows(self, module: dict[str, Any]) -> list[str]:
        rows: list[str] = []
        classes = module.get("classes", []) if isinstance(module.get("classes"), list) else []
        for cls in classes:
            if not isinstance(cls, dict):
                continue
            class_name = str(cls.get("class_name", "")).strip() or "Class"
            methods = cls.get("methods", []) if isinstance(cls.get("methods"), list) else []
            for method in methods:
                if not isinstance(method, dict):
                    continue
                params = method.get("params", [])
                param_text = ""
                if isinstance(params, list) and params:
                    param_text = ", ".join(
                        f"{str(p.get('name', 'arg'))}: {str(p.get('type', 'Any'))}"
                        for p in params
                        if isinstance(p, dict)
                    )
                rows.append(
                    f"- `{class_name}.{method.get('name', 'method')}({param_text}) -> {method.get('returns', 'Any')}`: "
                    f"{method.get('description', '')}"
                )
        return rows or ["- (none)"]

    def _build_subsystem_sr_sequence_diagram(
        self,
        *,
        subsystem_slug: str,
        sr_id: str,
        functions: list[dict[str, Any]],
    ) -> str:
        participants: list[str] = []
        for fn in functions:
            if not isinstance(fn, dict):
                continue
            mod = str(fn.get("module", fn.get("component", ""))).strip()
            if mod and mod not in participants:
                participants.append(mod)
        if not participants:
            participants = ["orchestrator"]
        lines = ["sequenceDiagram", "  autonumber", "  actor Caller"]
        aliases: dict[str, str] = {}
        for idx, name in enumerate(participants, start=1):
            alias = f"m{idx}"
            aliases[name] = alias
            lines.append(f"  participant {alias} as {name}")
        first_alias = aliases[participants[0]]
        lines.append(f"  Caller->>{first_alias}: Trigger {sr_id}")
        for left, right in zip(participants, participants[1:]):
            lines.append(f"  {aliases[left]}->>{aliases[right]}: Collaborate for {sr_id}")
            lines.append(f"  {aliases[right]}-->>{aliases[left]}: Return module result")
        lines.append(f"  {first_alias}-->>Caller: Compose SR result")
        return "\n".join(lines)

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
        sr_items = self._normalize_requirements(system_requirements.get("requirements", []))
        sr_to_subsystems = self._reverse_sr_allocation(architecture_design)
        subsystem_names = {
            str(s.get("id", "")): str(s.get("name", s.get("id", "")))
            for s in architecture_design.get("subsystems", [])
            if isinstance(s, dict)
        }
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
            "",
        ]
        lines.extend(self._render_mermaid_block(self._build_overall_architecture_c4_diagram(architecture_design)))
        lines.extend(
            [
                "",
                "### Subsystem Responsibilities, Dependencies, and Interactions",
                "",
                *self._describe_subsystem_dependencies(architecture_design),
                "",
                f"- Diagram: {architecture_design.get('architecture_diagram', '')}",
                "",
            ]
        )
        raw_arch_diagram = str(architecture_design.get("architecture_diagram", "")).strip()
        if raw_arch_diagram and any(
            raw_arch_diagram.startswith(prefix) for prefix in ("flowchart", "graph", "sequenceDiagram", "C4")
        ):
            lines.extend(self._render_mermaid_block(raw_arch_diagram))
            lines.append("")
        lines.extend(
            [
                "## Layered Expansion",
                "",
                *[f"- {layer}" for layer in architecture_design.get("layering", [])],
                "",
                "## Subsystems",
                "",
            ]
        )

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

        lines.extend(["## Requirements Split", ""])
        for sr in sr_items:
            sr_id = str(sr.get("id", ""))
            sr_title = str(sr.get("title", sr.get("requirement_overview", ""))).strip()
            subsystem_ids = sr_to_subsystems.get(sr_id, [])
            lines.extend(
                [
                    f"### {sr_id} - {sr_title}",
                    f"- Requirement Overview: {sr.get('requirement_overview', '')}",
                    f"- Scenario: {sr.get('scenario', '')}",
                    f"- Assigned Subsystems: {', '.join(subsystem_ids) if subsystem_ids else '(none)'}",
                ]
            )
            if subsystem_ids:
                impl_lines: list[str] = []
                for sid in subsystem_ids:
                    assignment = assignments.get(sid, {})
                    impl_lines.append(
                        f"{sid} ({subsystem_names.get(sid, sid)}): "
                        f"implemented by subsystem architect {assignment.get('subsystem_architect', '')} "
                        f"through subsystem APIs/components mapped to this SR."
                    )
                lines.extend(["- Implementation by Subsystem:", *[f"  - {x}" for x in impl_lines]])
            else:
                lines.extend(["- Implementation by Subsystem:", "  - (none)"])
            if len(subsystem_ids) > 1:
                lines.extend(
                    [
                        "- Cross-Subsystem Interaction Sequence:",
                        "",
                    ]
                )
                lines.extend(
                    self._render_mermaid_block(
                        self._build_cross_subsystem_sr_sequence_diagram(
                            sr_id=sr_id,
                            subsystem_ids=subsystem_ids,
                            subsystem_names=subsystem_names,
                        )
                    )
                )
                lines.extend(
                    [
                        "",
                        "- Cross-Subsystem Description:",
                        (
                            "  - "
                            f"{subsystem_names.get(subsystem_ids[0], subsystem_ids[0])} "
                            "receives the SR entry request and orchestrates the flow."
                        ),
                        *[
                            (
                                f"  - {subsystem_names.get(left, left)} calls "
                                f"{subsystem_names.get(right, right)} to complete "
                                f"delegated capability for {sr_id}."
                            )
                            for left, right in zip(subsystem_ids, subsystem_ids[1:])
                        ],
                        "  - Responses are composed and returned to the caller with SR-level status.",
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
        subsystem_slug = self._subsystem_slug(subsystem, fallback=str(subsystem.get("id", "subsystem")))
        lines = [
            f"# subsystem-{subsystem_slug}-design.md",
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
            "## Logical Architecture Views",
            "",
        ]

        logic_views = detail_design.get("logic_architecture_views", [])
        if isinstance(logic_views, list) and logic_views:
            for view in logic_views:
                if not isinstance(view, dict):
                    continue
                lines.extend(
                    [
                        f"### {view.get('view_name', view.get('view_id', 'view'))}",
                        f"- View Type: {view.get('view_type', '')}",
                    ]
                )
                description = str(view.get("description", "")).strip()
                if description:
                    lines.append(f"- Description: {description}")
                lines.append("")
                lines.extend(self._render_mermaid_block(str(view.get("mermaid", ""))))
                lines.append("")
        else:
            lines.extend(["- (none)", ""])

        module_designs = detail_design.get("module_designs", [])
        lines.extend(["## Subsystem Architecture (C4 Component View)", ""])
        if isinstance(module_designs, list) and module_designs:
            lines.extend(
                self._render_mermaid_block(
                    self._build_subsystem_component_c4_diagram(
                        subsystem=subsystem,
                        module_designs=module_designs,
                    )
                )
            )
            lines.extend(["", "### Component Responsibilities and Dependencies", ""])
            for module in module_designs:
                if not isinstance(module, dict):
                    continue
                module_name = str(module.get("module_name", "")).strip() or "module"
                deps = [str(x).strip() for x in (module.get("depends_on_modules", []) or []) if str(x).strip()]
                responsibilities = (
                    "; ".join([str(x) for x in module.get("responsibilities", [])])
                    if isinstance(module.get("responsibilities"), list)
                    else ""
                )
                lines.append(
                    f"- `{module_name}` (`{module.get('file_name', '')}`): "
                    f"{responsibilities or 'Module responsibilities TBD'} "
                    f"Dependencies: {', '.join(deps) if deps else '(none)'}."
                )
            lines.append("")
        else:
            lines.extend(["- (none)", ""])
        lines.extend(["## Module Logical Architecture", ""])
        if isinstance(module_designs, list) and module_designs:
            for module in module_designs:
                if not isinstance(module, dict):
                    continue
                module_name = str(module.get("module_name", "")).strip() or "module"
                deps = [str(x).strip() for x in (module.get("depends_on_modules", []) or []) if str(x).strip()]
                lines.extend(
                    [
                        f"### {module_name}",
                        f"- File: `{module.get('file_name', '')}`",
                        "- Responsibilities:",
                        *self._bullet_or_default(module.get("responsibilities", []), default="(none)"),
                        f"- Depends On Modules: {', '.join(deps) if deps else '(none)'}",
                        "",
                    ]
                )
        else:
            lines.extend(["- (none)", ""])

        lines.extend(["### Module Dependency Rules", ""])
        lines.extend(self._bullet_or_default(detail_design.get("module_dependency_rules", []), default="(none)"))
        lines.append("")
        lines.extend(["### Integration Flow Notes", ""])
        lines.extend(self._bullet_or_default(detail_design.get("integration_flow_notes", []), default="(none)"))
        lines.extend(["", "## Module Class Designs", ""])

        if isinstance(module_designs, list) and module_designs:
            for module in module_designs:
                if not isinstance(module, dict):
                    continue
                module_name = str(module.get("module_name", "")).strip() or "module"
                lines.extend(
                    [
                        f"### {module_name}",
                        f"- File: `{module.get('file_name', '')}`",
                        "- Responsibilities:",
                        *self._bullet_or_default(module.get("responsibilities", []), default="(none)"),
                        "",
                    ]
                )
                classes = module.get("classes", [])
                if isinstance(classes, list) and classes:
                    for cls in classes:
                        if not isinstance(cls, dict):
                            continue
                        lines.extend(
                            [
                                f"#### Class `{cls.get('class_name', '')}`",
                                f"- Kind: {cls.get('class_kind', 'class')}",
                                f"- Purpose: {cls.get('purpose', '')}",
                                "- Attributes:",
                            ]
                        )
                        attributes = cls.get("attributes", [])
                        if isinstance(attributes, list) and attributes:
                            for attr in attributes:
                                if not isinstance(attr, dict):
                                    continue
                                lines.append(
                                    "  - "
                                    f"{attr.get('visibility', 'private')} {attr.get('name', '')}: "
                                    f"{attr.get('type', 'Any')} - {attr.get('description', '')}"
                                )
                        else:
                            lines.append("  - (none)")
                        lines.append("- Methods:")
                        methods = cls.get("methods", [])
                        if isinstance(methods, list) and methods:
                            for method in methods:
                                if not isinstance(method, dict):
                                    continue
                                params = method.get("params", [])
                                param_text = ""
                                if isinstance(params, list) and params:
                                    param_text = ", ".join(
                                        f"{str(p.get('name', 'arg'))}: {str(p.get('type', 'Any'))}"
                                        for p in params
                                        if isinstance(p, dict)
                                    )
                                lines.append(
                                    "  - "
                                    f"{method.get('visibility', 'public')} {method.get('name', '')}"
                                    f"({param_text}) -> {method.get('returns', 'Any')}: "
                                    f"{method.get('description', '')}"
                                )
                        else:
                            lines.append("  - (none)")
                        inherits = [str(x).strip() for x in (cls.get("inherits", []) or []) if str(x).strip()]
                        uses = [str(x).strip() for x in (cls.get("uses_classes", []) or []) if str(x).strip()]
                        lines.append(f"- Inherits: {', '.join(inherits) if inherits else '(none)'}")
                        lines.append(f"- Uses Classes: {', '.join(uses) if uses else '(none)'}")
                        lines.append("")
                lines.extend(self._render_mermaid_block(str(module.get("class_diagram_mermaid", ""))))
                lines.append("")
        else:
            lines.extend(["- (none)", ""])

        lines.extend(["## Module APIs", ""])
        if isinstance(module_designs, list) and module_designs:
            for module in module_designs:
                if not isinstance(module, dict):
                    continue
                module_name = str(module.get("module_name", "")).strip() or "module"
                lines.extend(
                    [
                        f"### {module_name}",
                        f"- File: `{module.get('file_name', '')}`",
                        "- API Surface:",
                        *self._build_module_api_rows(module),
                        "",
                    ]
                )
        else:
            lines.extend(["- (none)", ""])

        lines.extend(
            [
                "## Components / Services",
                "",
            ]
        )

        for component in detail_design.get("components", []):
            responsibility_text = str(component.get("responsibility", "")).strip() or ", ".join(
                component.get("responsibilities", [])
            )
            lines.extend(
                [
                    f"### {component.get('id', '')} - {component.get('name', '')}",
                    f"- Type: {component.get('type', '')}",
                    f"- Responsibility: {responsibility_text}",
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
                    "- Module Collaboration Sequence:",
                    "",
                ]
            )
            lines.extend(
                self._render_mermaid_block(
                    self._build_subsystem_sr_sequence_diagram(
                        subsystem_slug=subsystem_slug,
                        sr_id=str(sr_item.get("sr_id", "")),
                        functions=sr_item.get("functions", []) if isinstance(sr_item.get("functions"), list) else [],
                    )
                )
            )
            lines.extend(
                [
                    "",
                    "- Module Collaboration Description:",
                    "  - The first module receives the SR trigger and coordinates downstream module calls.",
                    "  - Each module in this SR contributes one FN and collaborates through module APIs and imports.",
                    "  - Results are composed to satisfy the SR end-to-end behavior.",
                    "- Functions:",
                ]
            )
            for fn in sr_item.get("functions", []):
                lines.extend(
                    [
                        f"  - {fn.get('id', '')}",
                        f"    - Module: {fn.get('module', fn.get('component', ''))}",
                        f"    - File: {fn.get('file_name', '')}",
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
            if ch.isascii() and ch.isalnum():
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

    def _resolve_review_round_bounds(self, *, input_data: dict[str, Any], context: SkillContext) -> tuple[int, int]:
        limits = input_data.get("_review_round_limits")
        if not isinstance(limits, dict):
            limits = context.parameters.get("workflow_review_round_limits")
        min_rounds = int((limits or {}).get("min_rounds", 2) or 2)
        max_rounds = int((limits or {}).get("max_rounds", 3) or 3)
        min_rounds = max(1, min_rounds)
        max_rounds = max(1, max_rounds)
        if min_rounds > max_rounds:
            min_rounds, max_rounds = max_rounds, min_rounds
        return min_rounds, max_rounds

    def _clamp_review_rounds(self, *, min_rounds: int, max_rounds: int) -> int:
        low = max(1, int(min_rounds or 1))
        high = max(1, int(max_rounds or low))
        if low > high:
            low, high = high, low
        return low

    def _purpose_token(self, text: str) -> str:
        token = self._slugify(text)
        return token[:80] if token else "na"

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

    def _step_task_memory_context(
        self,
        *,
        task_key: str,
        docs_dir: Path,
        src_dir: Path,
        available_input_keys: list[str],
    ) -> dict[str, Any]:
        hint_map: dict[str, list[str]] = {
            "architect.deep_architecture_workflow.step1.design": [
                "system_design_doc",
                "system_requirements_doc",
                "review_feedback",
            ],
            "architect.deep_architecture_workflow.step1.review": [
                "system_architecture_doc",
                "system_requirements_doc",
            ],
            "architect.deep_architecture_workflow.step2_3": [
                "system_architecture_doc",
                "system_requirements_doc",
            ],
            "architect.deep_architecture_workflow.step4.design": [
                "subsystem_info",
                "system_requirements_doc",
                "system_architecture_doc",
            ],
            "architect.deep_architecture_workflow.step4.review": [
                "subsystem_detail_design_doc",
                "system_requirements_doc",
            ],
            "architect.deep_architecture_workflow.step5": ["subsystem_detail_design_doc"],
        }
        input_hints = list(hint_map.get(task_key, []))
        file_map: dict[str, Path] = {
            "system_design_doc": docs_dir / "system-design.md",
            "system_requirements_doc": docs_dir / "system-requirements.md",
            "system_architecture_doc": docs_dir / "system-architecture.md",
            "source_dir": src_dir,
        }
        doc_refs: list[dict[str, Any]] = []
        for hint in input_hints:
            if hint == "subsystem_detail_design_doc":
                matches: list[Path] = []
                if docs_dir.exists():
                    matches.extend(sorted(docs_dir.glob("subsystem-*-design.md")))
                    matches.extend(sorted(docs_dir.glob("*-detail-design.md")))
                doc_refs.append(
                    {
                        "role": hint,
                        "path": "docs",
                        "name": "docs",
                        "exists": bool(matches),
                        "glob": "subsystem-*-design.md|*-detail-design.md",
                    }
                )
                continue
            if hint == "subsystem_info":
                continue
            p = file_map.get(hint)
            if p is None:
                continue
            rel = f"docs/{p.name}" if p.parent == docs_dir else p.name
            doc_refs.append({"role": hint, "path": rel, "name": p.name, "exists": p.exists()})
        return {
            "input_hints": input_hints,
            "input_keys": input_hints,
            "available_input_keys": available_input_keys,
            "doc_refs": doc_refs,
        }

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

    def _json_schema_echo_prompt(
        self,
        *,
        required_keys: list[str] | None = None,
        optional_keys: list[str] | None = None,
    ) -> str:
        required = [str(key).strip() for key in (required_keys or []) if str(key).strip()]
        optional = [str(key).strip() for key in (optional_keys or []) if str(key).strip()]
        lines = ["JSON format guardrails:"]
        if required:
            lines.append(f"- required_keys (schema echo): {', '.join(required)}")
        if optional:
            lines.append(f"- optional_keys (schema echo): {', '.join(optional)}")
        lines.append(
            "- First build a complete JSON skeleton with the listed key names as placeholders, "
            "then fill values before sending the final answer."
        )
        if required:
            lines.append("- Include every required key even if a value is empty string/list/object.")
        if optional:
            lines.append("- If you include optional keys, use the exact key names and keep unknown keys out.")
        lines.append("- Return exactly one final JSON object only (no markdown, no comments, no prose).")
        return "\n".join(lines) + "\n"

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
        json_contract = (
            "\n\nOutput contract:\n"
            "- Return exactly one JSON object only.\n"
            "- Do not return markdown fences, comments, or explanatory prose.\n"
            "- Do not wrap the object under extra keys such as "
            "data/result/output/payload unless explicitly requested.\n"
            "- Use exact key names and nested key names specified in the prompt schema (no translation/synonyms).\n"
            "- Use exact enum/keyword literals specified in the prompt "
            "(for example approve/revise, layer names, etc.).\n"
            "- Match the expected value types in the schema "
            "(string/list/object/boolean), do not stringify nested JSON.\n"
        )
        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt + json_contract},
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
        candidates: list[str] = [text]
        block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if block:
            candidates.append(block.group(1))

        extracted = self._extract_first_json_object(text)
        if extracted:
            candidates.append(extracted)

        for candidate in candidates:
            parsed = self._try_parse_json_object(candidate)
            if parsed is not None:
                return parsed

            repaired = self._repair_common_json_issues(candidate)
            if repaired != candidate:
                parsed = self._try_parse_json_object(repaired)
                if parsed is not None:
                    return parsed

            truncated = self._repair_truncated_top_level_object(repaired)
            if truncated is not None:
                parsed = self._try_parse_json_object(truncated)
                if parsed is not None:
                    return parsed

        return None

    def _try_parse_json_object(self, text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _extract_first_json_object(self, text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        for idx, ch in enumerate(text[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]

        return None

    def _repair_common_json_issues(self, text: str) -> str:
        repaired = text.strip()
        # Common model formatting error: comma + quote then newline before the next key.
        # Example: `... ],"\nnext_key": ...` -> `... ],\n"next_key": ...`
        repaired = re.sub(r',"\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)"', r',\n"\1"', repaired)
        return repaired

    def _repair_truncated_top_level_object(self, text: str) -> str | None:
        """Drop the last incomplete top-level field when JSON is truncated.

        This is primarily to recover useful fields from long architecture outputs
        when the model is cut off mid-field (often inside architecture_diagram).
        """
        source = text.strip()
        if not source.startswith("{"):
            return None
        if source.endswith("}"):
            return None

        commas: list[int] = []
        depth = 0
        in_string = False
        escape = False
        for idx, ch in enumerate(source):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch in "{[":
                depth += 1
                continue
            if ch in "}]":
                depth = max(0, depth - 1)
                continue
            if ch == "," and depth == 1:
                commas.append(idx)

        # Try trimming to progressively earlier top-level commas, then close object.
        for comma_idx in reversed(commas):
            candidate = source[:comma_idx].rstrip()
            if not candidate.startswith("{"):
                continue
            candidate = candidate + "\n}"
            if self._try_parse_json_object(candidate) is not None:
                return candidate

        # As a last resort, if there was a single complete key-value pair and no top-level comma,
        # attempt to close the object directly after trimming trailing incomplete syntax.
        fallback = re.sub(r"[,\s]+$", "", source)
        if fallback.startswith("{") and fallback != source:
            fallback = fallback + "}"
            if self._try_parse_json_object(fallback) is not None:
                return fallback
        return None
