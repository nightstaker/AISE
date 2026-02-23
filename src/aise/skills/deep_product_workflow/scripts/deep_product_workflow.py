"""Deep Product workflow skill with paired Product Designer / Product Reviewer subagents."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class DeepProductWorkflowSkill(Skill):
    """Run PM deep workflow and generate revision-traceable design documents."""

    @property
    def name(self) -> str:
        return "deep_product_workflow"

    @property
    def description(self) -> str:
        return (
            "Run Product Designer and Product Reviewer paired workflow to generate "
            "system-design.md and system-requirements.md with full revision history"
        )

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not str(input_data.get("raw_requirements", "")).strip():
            errors.append("'raw_requirements' field is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        project_name = context.project_name or str(input_data.get("project_name", "Untitled")).strip() or "Untitled"
        raw_requirements = str(input_data.get("raw_requirements", "")).strip()
        user_memory = self._normalize_memory(input_data.get("user_memory") or context.parameters.get("user_memory"))
        recorder = context.parameters.get("task_memory_recorder") or input_data.get("_task_memory_recorder")
        phase_key = str(context.parameters.get("phase_key") or context.parameters.get("phase") or "requirements")
        retry_task_key = str(context.parameters.get("retry_task_key") or input_data.get("retry_task_key") or "")
        execution_scope = str(context.parameters.get("execution_scope") or "full_skill")
        output_dir = self._resolve_output_dir(input_data, context)
        output_dir.mkdir(parents=True, exist_ok=True)

        attempts: dict[str, int] = {}

        def _step_start(task_key: str, *, notes: list[str] | None = None) -> None:
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
                    "agent": "product_manager",
                    "skill": "deep_product_workflow",
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
                    context={
                        "input_keys": sorted(input_data.keys()),
                        "notes": list(notes or []),
                    },
                )

        def _step_end(task_key: str, *, status: str, error: str = "", outputs: dict[str, Any] | None = None) -> None:
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

        # Step 1: Product Designer expands understanding from raw requirements + memory.
        _step_start(
            "product_manager.deep_product_workflow.step1",
            notes=[f"requested_scope={execution_scope}"] if retry_task_key else None,
        )
        try:
            expanded = self._designer_expand_requirements(
                raw_requirements=raw_requirements,
                user_memory=user_memory,
                project_name=project_name,
                context=context,
            )
            _step_end("product_manager.deep_product_workflow.step1", status="completed")
        except Exception as exc:
            _step_end("product_manager.deep_product_workflow.step1", status="failed", error=str(exc))
            raise

        # Step 2: Product design with paired review loop (at least two rounds).
        _step_start("product_manager.deep_product_workflow.step2.design")
        _step_start("product_manager.deep_product_workflow.step2.review")
        try:
            design_rounds = self._run_product_design_review_rounds(expanded=expanded, context=context, min_rounds=2)
            _step_end(
                "product_manager.deep_product_workflow.step2.design",
                status="completed",
                outputs={"rounds": len(design_rounds)},
            )
            _step_end(
                "product_manager.deep_product_workflow.step2.review",
                status="completed",
                outputs={"rounds": len(design_rounds)},
            )
        except Exception as exc:
            _step_end("product_manager.deep_product_workflow.step2.design", status="failed", error=str(exc))
            _step_end("product_manager.deep_product_workflow.step2.review", status="failed", error=str(exc))
            raise
        latest_design = design_rounds[-1]["design"]

        # Step 3: System requirements with paired review loop (at least two rounds).
        _step_start("product_manager.deep_product_workflow.step3.design")
        _step_start("product_manager.deep_product_workflow.step3.review")
        try:
            requirements_rounds = self._run_system_requirement_review_rounds(
                expanded=expanded,
                latest_design=latest_design,
                context=context,
                min_rounds=2,
            )
            _step_end(
                "product_manager.deep_product_workflow.step3.design",
                status="completed",
                outputs={"rounds": len(requirements_rounds)},
            )
            _step_end(
                "product_manager.deep_product_workflow.step3.review",
                status="completed",
                outputs={"rounds": len(requirements_rounds)},
            )
        except Exception as exc:
            _step_end("product_manager.deep_product_workflow.step3.design", status="failed", error=str(exc))
            _step_end("product_manager.deep_product_workflow.step3.review", status="failed", error=str(exc))
            raise
        latest_requirements = requirements_rounds[-1]["system_requirements"]

        design_doc_path = output_dir / "system-design.md"
        req_doc_path = output_dir / "system-requirements.md"
        design_doc_path.write_text(
            self._render_system_design_doc(
                project_name=project_name,
                expanded=expanded,
                latest_design=latest_design,
                rounds=design_rounds,
            ),
            encoding="utf-8",
        )
        req_doc_path.write_text(
            self._render_system_requirements_doc(
                project_name=project_name,
                expanded=expanded,
                latest_design=latest_design,
                latest_requirements=latest_requirements,
                rounds=requirements_rounds,
            ),
            encoding="utf-8",
        )
        _step_end(
            "product_manager.deep_product_workflow.step3.design",
            status="completed",
            outputs={"generated_files": [str(design_doc_path), str(req_doc_path)]},
        ) if False else None

        requirements_artifact = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "raw_requirements": raw_requirements,
                "analysis_mode": expanded.get("analysis_mode", "deep_product_workflow"),
                "expanded_understanding": expanded,
                "functional_requirements": [
                    {"id": sf["id"], "description": sf["goal"], "priority": sf.get("priority", "medium")}
                    for sf in latest_design.get("system_features", [])
                ],
                "non_functional_requirements": [
                    {"id": f"NFR-{idx:03d}", "description": c, "priority": "high"}
                    for idx, c in enumerate(expanded.get("constraints", []), start=1)
                ],
                "constraints": [
                    {"id": f"C-{idx:03d}", "description": c}
                    for idx, c in enumerate(expanded.get("constraints", []), start=1)
                ],
            },
            producer="product_designer",
            metadata={"project_name": project_name, "subagent": "product_designer", "step": "requirement_expansion"},
        )
        context.artifact_store.store(requirements_artifact)

        system_design_artifact = Artifact(
            artifact_type=ArtifactType.SYSTEM_DESIGN,
            content=self._to_system_design_artifact_content(project_name, latest_design),
            producer="product_designer",
            metadata={"project_name": project_name, "subagent": "product_designer", "step": "product_design"},
        )
        context.artifact_store.store(system_design_artifact)

        system_requirements_artifact = Artifact(
            artifact_type=ArtifactType.SYSTEM_REQUIREMENTS,
            content=self._to_system_requirements_artifact_content(project_name, latest_requirements),
            producer="product_designer",
            metadata={
                "project_name": project_name,
                "subagent": "product_designer",
                "step": "system_requirement_design",
            },
        )
        context.artifact_store.store(system_requirements_artifact)

        latest_review = requirements_rounds[-1].get("review", {}) if requirements_rounds else {}
        review_artifact = Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "approved": bool(latest_review.get("approved", False)),
                "reviewer": "product_reviewer",
                "target": "system_requirements",
                "issues": latest_review.get("issues", []),
                "summary": latest_review.get("summary", ""),
            },
            producer="product_reviewer",
            metadata={"project_name": project_name, "subagent": "product_reviewer", "step": "review"},
        )
        context.artifact_store.store(review_artifact)

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "workflow": "deep_product_workflow",
                "project_name": project_name,
                "sub_agents": ["product_designer", "product_reviewer"],
                "step1": {
                    "name": "requirement_expansion",
                    "status": "completed",
                    "memory_items": len(user_memory),
                },
                "step2": {
                    "name": "product_design_review_loop",
                    "status": "completed",
                    "rounds": len(design_rounds),
                    "revision_history": [r["review"].get("summary", "") for r in design_rounds],
                },
                "step3": {
                    "name": "system_requirement_review_loop",
                    "status": "completed",
                    "rounds": len(requirements_rounds),
                    "revision_history": [r["review"].get("summary", "") for r in requirements_rounds],
                },
                "generated_files": [str(design_doc_path), str(req_doc_path)],
                "artifact_ids": {
                    "requirements": requirements_artifact.id,
                    "system_design": system_design_artifact.id,
                    "system_requirements": system_requirements_artifact.id,
                    "review_feedback": review_artifact.id,
                },
            },
            producer="product_manager",
            metadata={"project_name": project_name},
        )

    def _resolve_output_dir(self, input_data: dict[str, Any], context: SkillContext) -> Path:
        project_root = context.parameters.get("project_root")
        root_path = Path(project_root).resolve() if isinstance(project_root, str) and project_root.strip() else None
        output_dir = input_data.get("output_dir")
        safe_default = (root_path / "docs") if root_path is not None else Path("docs")
        if isinstance(output_dir, str) and output_dir.strip():
            output_path = Path(output_dir)
            if root_path is not None:
                # Keep writes inside project root to avoid permission errors and sandbox escapes.
                candidate = (
                    (root_path / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
                )
                try:
                    candidate.relative_to(root_path)
                    return candidate
                except ValueError:
                    return safe_default
            return output_path.resolve()
        return safe_default

    def _normalize_memory(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            output: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    output.append(text)
            return output
        return []

    def _designer_expand_requirements(
        self,
        *,
        raw_requirements: str,
        user_memory: list[str],
        project_name: str,
        context: SkillContext,
    ) -> dict[str, Any]:
        memory_text = "\n".join(f"- {m}" for m in user_memory) or "- (none)"
        common_prompt = (
            f"Project: {project_name}\nRaw requirements:\n{raw_requirements}\n\nUser memory:\n{memory_text}\n"
        )
        llm_core = self._run_llm_json_segment(
            context=context,
            purpose=(
                f"subagent:product_designer step:requirement_expansion.core project:{self._purpose_token(project_name)}"
            ),
            system_prompt=(
                "You are Product Designer.\n"
                "Task: expand and clarify user raw requirements with user memory.\n"
                "Return JSON only with keys: intent_summary, business_goals."
            ),
            user_prompt=common_prompt,
            required_keys=["intent_summary", "business_goals"],
        )
        llm_context = self._run_llm_json_segment(
            context=context,
            purpose=(
                "subagent:product_designer step:requirement_expansion.context "
                f"project:{self._purpose_token(project_name)}"
            ),
            system_prompt=(
                "You are Product Designer.\n"
                "Task: derive delivery context and risks from user requirements.\n"
                "Return JSON only with keys: users, scenarios, constraints, assumptions, risks."
            ),
            user_prompt=(
                common_prompt + f"\nIntent summary (may be partial): {str(llm_core.get('intent_summary', ''))[:1000]}\n"
            ),
            required_keys=["users", "scenarios", "constraints", "assumptions", "risks"],
        )
        llm_data = {**llm_core, **llm_context}
        if llm_data:
            return {
                "analysis_mode": "llm",
                "raw_requirements": raw_requirements,
                "user_memory": user_memory,
                "intent_summary": str(llm_data.get("intent_summary", "")).strip()
                or "Clarify and deliver the requested system.",
                "business_goals": self._as_str_list(llm_data.get("business_goals")),
                "users": self._as_str_list(llm_data.get("users")),
                "scenarios": self._as_str_list(llm_data.get("scenarios")),
                "constraints": self._as_str_list(llm_data.get("constraints")),
                "assumptions": self._as_str_list(llm_data.get("assumptions")),
                "risks": self._as_str_list(llm_data.get("risks")),
            }

        goals = self._extract_requirement_points(raw_requirements)[:8]
        users = ["End users", "Operations team"]
        scenarios = ["Primary usage flow", "Error handling and recovery"]
        constraints = ["Cross-platform support", "Scalable architecture"]
        has_ai = any(key in raw_requirements.lower() for key in ("ai", "bot", "智能"))
        has_multi = any(key in raw_requirements.lower() for key in ("multiplayer", "多人", "联机", "协作"))
        if has_multi:
            users.append("Session host")
            scenarios.append("Collaboration flow with participant synchronization")
        if has_ai:
            scenarios.append("AI-assisted flow with explainable decisions")
        constraints.extend(
            [
                "Core state transitions should be reproducible and testable",
                "Key events and failure reasons should be observable",
            ]
        )
        return {
            "analysis_mode": "heuristic",
            "raw_requirements": raw_requirements,
            "user_memory": user_memory,
            "intent_summary": f"Deliver project based on {len(goals)} core requirement points.",
            "business_goals": goals,
            "users": users,
            "scenarios": scenarios,
            "constraints": constraints,
            "assumptions": ["Requirements can evolve through review loops"],
            "risks": ["Ambiguity in platform-specific behavior"],
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
        for attempt in range(1, max(1, max_attempts) + 1):
            prompt = user_prompt
            if attempt > 1:
                missing = [key for key in required_keys if key not in last_partial]
                prompt += (
                    "\n\nRetry guidance:\n"
                    "- Previous response was incomplete/truncated or missing required keys.\n"
                    f"- Required keys: {', '.join(required_keys)}\n"
                    f"- Missing keys: {', '.join(missing) if missing else '(schema invalid)'}\n"
                )
                if last_partial:
                    prompt += f"Partial response:\n{self._compact_json(last_partial)}\n"
                prompt += "Return compact valid JSON only.\n"
            try:
                payload = self._run_llm_json(
                    context=context,
                    purpose=purpose,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                )
            except Exception:
                continue
            if isinstance(payload, dict):
                last_partial = payload
            if self._segment_payload_ok(payload, required_keys):
                return payload
        return last_partial

    def _segment_payload_ok(self, payload: dict[str, Any], required_keys: list[str]) -> bool:
        if not isinstance(payload, dict):
            return False
        for key in required_keys:
            if key not in payload:
                return False
        if "intent_summary" in required_keys and len(str(payload.get("intent_summary", "")).strip()) < 20:
            return False
        for list_key in ("business_goals", "users", "scenarios", "constraints", "assumptions", "risks"):
            if list_key in required_keys:
                value = self._as_str_list(payload.get(list_key))
                if not value:
                    return False
        return True

    def _compact_json(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(payload)

    def _run_product_design_review_rounds(
        self,
        *,
        expanded: dict[str, Any],
        context: SkillContext,
        min_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_design: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None

        for round_index in range(1, max(2, min_rounds) + 1):
            design = self._designer_build_product_design(
                expanded=expanded,
                previous_design=previous_design,
                previous_review=previous_review,
                round_index=round_index,
                context=context,
            )
            review = self._reviewer_review_product_design(
                expanded=expanded,
                design=design,
                round_index=round_index,
                context=context,
            )
            rounds.append({"round": round_index, "design": design, "review": review})
            previous_design = design
            previous_review = review
        return rounds

    def _run_system_requirement_review_rounds(
        self,
        *,
        expanded: dict[str, Any],
        latest_design: dict[str, Any],
        context: SkillContext,
        min_rounds: int,
    ) -> list[dict[str, Any]]:
        rounds: list[dict[str, Any]] = []
        previous_req: dict[str, Any] | None = None
        previous_review: dict[str, Any] | None = None

        for round_index in range(1, max(2, min_rounds) + 1):
            req_doc = self._designer_build_system_requirements(
                expanded=expanded,
                design=latest_design,
                previous_requirements=previous_req,
                previous_review=previous_review,
                round_index=round_index,
                context=context,
            )
            review = self._reviewer_review_system_requirements(
                design=latest_design,
                system_requirements=req_doc,
                round_index=round_index,
                context=context,
            )
            rounds.append({"round": round_index, "system_requirements": req_doc, "review": review})
            previous_req = req_doc
            previous_review = review
        return rounds

    def _designer_build_product_design(
        self,
        *,
        expanded: dict[str, Any],
        previous_design: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        features = previous_design.get("system_features", []) if previous_design else []
        if not features:
            features = []
            for idx, goal in enumerate(expanded.get("business_goals", []), start=1):
                functions = self._goal_to_functions(goal)
                features.append(
                    {
                        "id": f"SF-{idx:03d}",
                        "name": self._to_title(goal, fallback=f"Feature {idx}"),
                        "goal": goal,
                        "functions": functions,
                        "constraints": expanded.get("constraints", []),
                        "priority": "high" if idx <= 2 else "medium",
                    }
                )

        if previous_review and previous_review.get("issues"):
            issue_texts = [str(issue) for issue in previous_review.get("issues", [])]
            for feature in features:
                feature.setdefault("constraints", [])
                for issue in issue_texts[:2]:
                    if issue not in feature["constraints"]:
                        feature["constraints"].append(issue)

        overview = " ".join(
            [
                expanded.get("intent_summary", "").strip(),
                "This design consolidates large-grain system features and traceable product intent.",
            ]
        ).strip()

        return {
            "round": round_index,
            "overview": overview,
            "overall_solution": [
                "Use modular architecture with consistent UX across target platforms.",
                "Feature-first delivery with traceability from intent to implementation.",
            ],
            "system_features": features,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _reviewer_review_product_design(
        self,
        *,
        expanded: dict[str, Any],
        design: dict[str, Any],
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        features = design.get("system_features", [])
        issues: list[str] = []
        if not features:
            issues.append("No system features were produced.")
        for sf in features:
            if not sf.get("goal"):
                issues.append(f"{sf.get('id', 'SF-UNKNOWN')} missing goal.")
            if not sf.get("functions"):
                issues.append(f"{sf.get('id', 'SF-UNKNOWN')} missing functional details.")
            if not sf.get("constraints"):
                issues.append(f"{sf.get('id', 'SF-UNKNOWN')} missing constraint details.")

        approved = round_index >= 2 and not issues
        if round_index == 1 and not issues:
            issues.append("Round 1 baseline completed; run one refinement pass before approval.")
            approved = False

        return {
            "reviewer": "product_reviewer",
            "approved": approved,
            "summary": "Approved" if approved else "Needs revision",
            "issues": issues,
            "suggestions": [
                "Ensure each SF has explicit goal/function/constraint fields.",
                "Record reviewer comments and designer responses in revision history.",
            ],
            "decision": "approve" if approved else "revise",
            "expanded_context_used": bool(expanded.get("intent_summary")),
        }

    def _designer_build_system_requirements(
        self,
        *,
        expanded: dict[str, Any],
        design: dict[str, Any],
        previous_requirements: dict[str, Any] | None,
        previous_review: dict[str, Any] | None,
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        srs = previous_requirements.get("requirements", []) if previous_requirements else []
        if not srs:
            srs = []
            sr_index = 1
            for sf_idx, sf in enumerate(design.get("system_features", []), start=1):
                sf_srs = self._decompose_sf_to_system_requirements(
                    sf=sf,
                    sf_index=sf_idx,
                    users=expanded.get("users", ["End users"]),
                    start_index=sr_index,
                )
                srs.extend(sf_srs)
                sr_index += len(sf_srs)

        if previous_review and previous_review.get("issues"):
            comment_note = " | ".join(str(i) for i in previous_review.get("issues", [])[:2])
            for sr in srs:
                sr.setdefault("use_case_description", "")
                if comment_note and comment_note not in sr["use_case_description"]:
                    sr["use_case_description"] = (
                        sr["use_case_description"] + " Reviewer focus: " + comment_note
                    ).strip()

        return {
            "round": round_index,
            "design_goals": [
                "Translate SF into complete SR with implementation-oriented details.",
                "Maintain strict traceability between SF and SR.",
                "Decompose each SF into multiple independent, verifiable SR entries.",
            ],
            "design_approach": [
                "Feature to requirement decomposition",
                "Function-level SR splitting under each SF",
                "Scenario-driven interaction design",
                "Measurable constraints and verification targets",
            ],
            "requirements": srs,
            "designer_response": self._build_designer_response(previous_review),
        }

    def _reviewer_review_system_requirements(
        self,
        *,
        design: dict[str, Any],
        system_requirements: dict[str, Any],
        round_index: int,
        context: SkillContext,
    ) -> dict[str, Any]:
        requirements = system_requirements.get("requirements", [])
        issues: list[str] = []
        if not requirements:
            issues.append("No SR entries generated.")
        sf_ids = [str(sf.get("id", "")).strip() for sf in design.get("system_features", []) if isinstance(sf, dict)]
        sf_counts: dict[str, int] = {sf_id: 0 for sf_id in sf_ids if sf_id}
        seen_titles: set[str] = set()
        for sr in requirements:
            required_fields = [
                "requirement_overview",
                "scenario",
                "users",
                "interaction_process",
                "expected_result",
                "spec_targets",
                "constraints",
                "use_case_diagram",
                "use_case_description",
            ]
            for field in required_fields:
                value = sr.get(field)
                if value is None or (isinstance(value, (str, list)) and len(value) == 0):
                    issues.append(f"{sr.get('id', 'SR-UNKNOWN')} missing {field}.")
            source_sfs = sr.get("source_sfs", [])
            if not isinstance(source_sfs, list) or not source_sfs:
                issues.append(f"{sr.get('id', 'SR-UNKNOWN')} missing source_sfs mapping.")
            else:
                if len(source_sfs) != 1:
                    issues.append(
                        f"{sr.get('id', 'SR-UNKNOWN')} should map to exactly one "
                        "primary SF for independent verification."
                    )
                for sf_id in source_sfs:
                    sf_key = str(sf_id).strip()
                    if sf_key:
                        sf_counts[sf_key] = sf_counts.get(sf_key, 0) + 1
            if len(sr.get("spec_targets", [])) < 2:
                issues.append(f"{sr.get('id', 'SR-UNKNOWN')} should include at least 2 measurable spec targets.")
            if not str(sr.get("verification_method", "")).strip():
                issues.append(f"{sr.get('id', 'SR-UNKNOWN')} missing verification_method.")
            title_key = str(sr.get("title", "")).strip().lower()
            if title_key:
                if title_key in seen_titles:
                    issues.append(f"{sr.get('id', 'SR-UNKNOWN')} has duplicated title '{sr.get('title', '')}'.")
                seen_titles.add(title_key)
        for sf_id in sf_ids:
            if sf_counts.get(sf_id, 0) < 2:
                issues.append(f"{sf_id} should decompose into at least 2 independent SR entries.")

        approved = round_index >= 2 and not issues
        if round_index == 1 and not issues:
            issues.append("Round 1 baseline completed; run one refinement pass before approval.")
            approved = False

        return {
            "reviewer": "product_reviewer",
            "approved": approved,
            "summary": "Approved" if approved else "Needs revision",
            "issues": issues,
            "suggestions": [
                "Ensure every SR includes complete scenario, interaction, and use case details.",
                "Keep revision response aligned with reviewer concerns.",
            ],
            "decision": "approve" if approved else "revise",
            "reviewed_sf_count": len(design.get("system_features", [])),
        }

    def _decompose_sf_to_system_requirements(
        self,
        *,
        sf: dict[str, Any],
        sf_index: int,
        users: list[str],
        start_index: int,
    ) -> list[dict[str, Any]]:
        sf_id = str(sf.get("id", f"SF-{sf_index:03d}")).strip() or f"SF-{sf_index:03d}"
        sf_name = str(sf.get("name", f"Feature {sf_index}")).strip() or f"Feature {sf_index}"
        sf_goal = str(sf.get("goal", sf_name)).strip() or sf_name
        functions = self._as_str_list(sf.get("functions"))
        constraints = self._as_str_list(sf.get("constraints"))
        priority = str(sf.get("priority", "medium"))

        slices: list[tuple[str, str, str]] = []
        for fn in functions[:4]:
            cleaned = str(fn).strip()
            if not cleaned:
                continue
            title = self._short_requirement_title_from_function(sf_name, cleaned)
            slices.append((title, cleaned, "integration_test"))

        # Guarantee multiple SRs per SF even when upstream functions are sparse.
        if len(slices) < 2:
            slices.append(
                (
                    f"{sf_name} input validation and error handling",
                    (
                        "System validates inputs, rejects invalid requests, and "
                        f"returns deterministic error handling for {sf_goal}."
                    ),
                    "negative_integration_test",
                )
            )
        if len(slices) < 2:
            slices.append(
                (
                    f"{sf_name} observability and measurable outcomes",
                    (
                        "System emits auditable state transitions and metrics for "
                        f"{sf_goal} to support verification and operations."
                    ),
                    "integration_test",
                )
            )

        requirements: list[dict[str, Any]] = []
        for offset, (title, focus_text, verification_method) in enumerate(slices, start=0):
            sr_num = start_index + offset
            sr_id = f"SR-{sr_num:03d}"
            interaction_process = self._goal_to_interactions(focus_text)
            expected = f"System independently satisfies: {focus_text}"
            spec_targets = self._build_sr_spec_targets(sf_goal=sf_goal, focus_text=focus_text)
            requirements.append(
                {
                    "id": sr_id,
                    "source_sfs": [sf_id],
                    "title": title,
                    "requirement_overview": focus_text,
                    "scenario": f"As a user/system actor, I need the system to support: {focus_text}",
                    "users": users if isinstance(users, list) and users else ["End users"],
                    "interaction_process": interaction_process,
                    "expected_result": expected,
                    "spec_targets": spec_targets,
                    "constraints": constraints,
                    "use_case_diagram": f"UseCase({sr_id}) -> Actor(User/System) -> System({sf_name})",
                    "use_case_description": (
                        f"{sr_id} is an independently verifiable system requirement decomposed from {sf_id} "
                        f"covering one concrete behavior slice: {focus_text}"
                    ),
                    "type": "functional",
                    "category": "Product Capability",
                    "priority": priority,
                    "verification_method": verification_method,
                }
            )
        return requirements

    def _short_requirement_title_from_function(self, sf_name: str, function_text: str) -> str:
        text = str(function_text).strip()
        lower = text.lower()
        if "user-facing behavior" in lower:
            return f"{sf_name} - user interaction behavior"
        if "service logic and state transition" in lower:
            return f"{sf_name} - service logic and state transition"
        if "verifiable outcomes and telemetry" in lower:
            return f"{sf_name} - observability and verification telemetry"
        if ":" in text:
            text = text.split(":", 1)[1].strip()
        text = re.sub(r"\s+", " ", text)
        # Keep title compact and specific.
        if len(text) > 72:
            text = text[:72].rstrip()
        base = f"{sf_name} - {text}" if sf_name and text else (sf_name or text or "System Requirement")
        return base

    def _build_sr_spec_targets(self, *, sf_goal: str, focus_text: str) -> list[str]:
        text = f"{sf_goal} {focus_text}".lower()
        targets = [
            "Functional correctness >= 95% pass rate in integration test suite for this SR",
            "Deterministic expected result and error code coverage for defined scenario paths",
        ]
        if any(token in text for token in ("多人", "multiplayer", "sync", "同步", "realtime", "real-time")):
            targets.append("P95 state synchronization/update latency <= 100ms under target load")
        elif any(token in text for token in ("ai", "bot", "智能")):
            targets.append("P95 decision response time <= 300ms with observable decision trace")
        else:
            targets.append("P95 request/response processing time <= 300ms for this scenario")
        return targets[:3]

    def _to_system_design_artifact_content(self, project_name: str, design: dict[str, Any]) -> dict[str, Any]:
        all_features = []
        for sf in design.get("system_features", []):
            all_features.append(
                {
                    "id": sf.get("id", ""),
                    "description": sf.get("goal", sf.get("name", "")),
                    "type": "external",
                    "category": "Product Capability",
                }
            )
        return {
            "project_name": project_name,
            "overview": design.get("overview", ""),
            "external_features": all_features,
            "internal_dfx_features": [],
            "all_features": all_features,
            "system_features": design.get("system_features", []),
        }

    def _to_system_requirements_artifact_content(self, project_name: str, req_doc: dict[str, Any]) -> dict[str, Any]:
        requirements = req_doc.get("requirements", [])
        matrix: dict[str, list[str]] = {}
        for sr in requirements:
            for sf_id in sr.get("source_sfs", []):
                matrix.setdefault(str(sf_id), []).append(str(sr.get("id", "")))
        coverage_total = len(matrix)
        covered = len([k for k, v in matrix.items() if v])
        return {
            "project_name": project_name,
            "overview": "System requirements generated by deep product workflow.",
            "requirements": requirements,
            "coverage_summary": {
                "total_sfs": coverage_total,
                "covered_sfs": covered,
                "uncovered_sfs": [],
                "coverage_percentage": (covered / coverage_total * 100) if coverage_total else 0,
            },
            "traceability_matrix": matrix,
        }

    def _render_system_design_doc(
        self,
        *,
        project_name: str,
        expanded: dict[str, Any],
        latest_design: dict[str, Any],
        rounds: list[dict[str, Any]],
    ) -> str:
        lines = [
            "# system-design.md",
            "",
            f"Generated at: {self._now_iso()}",
            f"Project: {project_name}",
            "",
            "## Product Intent Expansion",
            "",
            f"- Summary: {expanded.get('intent_summary', '')}",
            "- Business Goals:",
            *[f"  - {item}" for item in expanded.get("business_goals", [])],
            "- Users:",
            *[f"  - {item}" for item in expanded.get("users", [])],
            "- Constraints:",
            *[f"  - {item}" for item in expanded.get("constraints", [])],
            "",
            "## Overall Product Design",
            "",
            f"{latest_design.get('overview', '')}",
            "",
            "### Design Approach",
            *[f"- {item}" for item in latest_design.get("overall_solution", [])],
            "",
            "## System Features (SF)",
            "",
        ]
        for sf in latest_design.get("system_features", []):
            lines.extend(
                [
                    f"### {sf.get('id', 'SF-UNKNOWN')} - {sf.get('name', '')}",
                    f"- Feature Goal: {sf.get('goal', '')}",
                    "- Functions:",
                    *[f"  - {item}" for item in sf.get("functions", [])],
                    "- Constraints:",
                    *[f"  - {item}" for item in sf.get("constraints", [])],
                    "",
                ]
            )

        lines.extend(["## Revision History", ""])
        for item in rounds:
            review = item.get("review", {})
            design = item.get("design", {})
            lines.extend(
                [
                    f"### Round {item.get('round', '')}",
                    f"- Reviewer Decision: {review.get('decision', '')}",
                    f"- Reviewer Summary: {review.get('summary', '')}",
                    "- Reviewer Issues:",
                    *self._bullet_or_default(review.get("issues", []), default="(none)"),
                    "- Reviewer Suggestions:",
                    *self._bullet_or_default(review.get("suggestions", []), default="(none)"),
                    "- Designer Response:",
                    *self._bullet_or_default(design.get("designer_response", []), default="Initial draft"),
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def _render_system_requirements_doc(
        self,
        *,
        project_name: str,
        expanded: dict[str, Any],
        latest_design: dict[str, Any],
        latest_requirements: dict[str, Any],
        rounds: list[dict[str, Any]],
    ) -> str:
        lines = [
            "# system-requirements.md",
            "",
            f"Generated at: {self._now_iso()}",
            f"Project: {project_name}",
            "",
            "## System Design Context",
            "",
            f"- Intent Summary: {expanded.get('intent_summary', '')}",
            f"- SF Count: {len(latest_design.get('system_features', []))}",
            "",
            "## System Requirement Design",
            "",
            "### Design Goals",
            *[f"- {g}" for g in latest_requirements.get("design_goals", [])],
            "",
            "### Design Approach",
            *[f"- {a}" for a in latest_requirements.get("design_approach", [])],
            "",
            "## System Requirements (SR)",
            "",
        ]
        for sr in latest_requirements.get("requirements", []):
            lines.extend(
                [
                    f"### {sr.get('id', 'SR-UNKNOWN')} - {sr.get('title', '')}",
                    f"- Requirement Overview: {sr.get('requirement_overview', '')}",
                    f"- Scenario: {sr.get('scenario', '')}",
                    f"- Users: {', '.join(sr.get('users', []))}",
                    "- Interaction Process:",
                    *[f"  - {step}" for step in sr.get("interaction_process", [])],
                    f"- Expected: {sr.get('expected_result', '')}",
                    "- Spec Targets:",
                    *[f"  - {target}" for target in sr.get("spec_targets", [])],
                    "- Constraints:",
                    *[f"  - {c}" for c in sr.get("constraints", [])],
                    f"- UseCase Diagram: {sr.get('use_case_diagram', '')}",
                    f"- UseCase Description: {sr.get('use_case_description', '')}",
                    "",
                ]
            )

        lines.extend(
            [
                "## Traceability Matrix",
                "",
                "| SF | SR |",
                "|----|----|",
            ]
        )
        for sr in latest_requirements.get("requirements", []):
            sr_id = str(sr.get("id", "SR-UNKNOWN"))
            source_sfs = sr.get("source_sfs", [])
            if isinstance(source_sfs, list) and source_sfs:
                for sf_id in source_sfs:
                    lines.append(f"| {sf_id} | {sr_id} |")
            else:
                lines.append(f"| (unmapped) | {sr_id} |")
        lines.append("")

        lines.extend(["## Revision History", ""])
        for item in rounds:
            review = item.get("review", {})
            req_doc = item.get("system_requirements", {})
            lines.extend(
                [
                    f"### Round {item.get('round', '')}",
                    f"- Reviewer Decision: {review.get('decision', '')}",
                    f"- Reviewer Summary: {review.get('summary', '')}",
                    "- Reviewer Issues:",
                    *self._bullet_or_default(review.get("issues", []), default="(none)"),
                    "- Reviewer Suggestions:",
                    *self._bullet_or_default(review.get("suggestions", []), default="(none)"),
                    "- Designer Response:",
                    *self._bullet_or_default(req_doc.get("designer_response", []), default="Initial draft"),
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def _build_designer_response(self, previous_review: dict[str, Any] | None) -> list[str]:
        if not previous_review:
            return ["Initial design draft based on expanded requirements."]
        issues = [str(i) for i in previous_review.get("issues", [])]
        if not issues:
            return ["All reviewer comments addressed; no outstanding issues."]
        return [f"Addressed reviewer issue: {issue}" for issue in issues[:4]]

    def _run_llm_json(
        self,
        *,
        context: SkillContext,
        system_prompt: str,
        user_prompt: str,
        purpose: str = "",
    ) -> dict[str, Any]:
        if context.llm_client is None:
            raise RuntimeError("LLM client is required for deep_product_workflow")
        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            llm_purpose=purpose or "agent:product_manager role:product_manager skill:deep_product_workflow",
        )
        parsed = self._parse_json_response(response)
        if parsed is None:
            if purpose:
                raise RuntimeError(f"LLM response is not valid JSON object for {purpose}")
            raise RuntimeError("LLM response is not valid JSON object for deep_product_workflow")
        return parsed

    def _purpose_token(self, value: str) -> str:
        token = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
        return (token or "na")[:80]

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _split_lines(self, text: str) -> list[str]:
        return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]

    def _extract_requirement_points(self, text: str) -> list[str]:
        raw_lines = self._split_lines(text)
        if not raw_lines:
            return []
        combined = " ".join(raw_lines)
        segments = re.split(r"[。.!?\n]|，|,|；|;|、|并且|并|还要|且", combined)
        points: list[str] = []
        stop_phrases = (
            "请提供",
            "提供",
            "清晰文档",
            "可运行代码",
            "pytest测试",
            "测试用例",
            "文档",
            "代码",
        )
        for segment in segments:
            normalized = segment.strip().strip("-").strip()
            if len(normalized) < 4:
                continue
            if any(phrase in normalized for phrase in stop_phrases):
                continue
            if normalized in points:
                continue
            points.append(normalized)
        if not points:
            return raw_lines[:8]
        return points[:12]

    def _goal_to_functions(self, goal: str) -> list[str]:
        result = [
            f"Define user-facing behavior for: {goal}",
            f"Implement service logic and state transition for: {goal}",
            f"Expose verifiable outcomes and telemetry for: {goal}",
        ]
        return result

    def _goal_to_interactions(self, goal: str) -> list[str]:
        interactions = [
            "User selects mode/configuration and starts session",
            "System validates input and initializes runtime state",
            "System processes game/service loop and updates score/state",
            "System returns latest state and final settlement",
        ]
        if "多人" in goal or "multiplayer" in goal.lower():
            interactions.insert(2, "System synchronizes shared state between players")
        if "人机" in goal or "ai" in goal.lower():
            interactions.insert(2, "System computes AI decision and merges with player action")
        return interactions

    def _as_str_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            output: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    output.append(text)
            return output
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            # Try JSON array encoded as string first.
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            # Split numbered list / semicolon / newline forms often returned by models.
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            normalized = re.sub(r"\s+", " ", normalized)
            # Insert hard separators before common enumerators so one-line lists can be split.
            normalized = re.sub(r"\s(?=\d+\s*[\)\.、:])", "\n", normalized)
            normalized = re.sub(r"\s(?=[A-Za-z]\))", "\n", normalized)
            chunks = re.split(r"\n|；|;", normalized)
            output: list[str] = []
            for chunk in chunks:
                item = chunk.strip()
                item = re.sub(r"^\d+\s*[\)\.、:]\s*", "", item)
                item = re.sub(r"^[A-Za-z]\)\s*", "", item)
                item = item.strip(" -")
                if not item:
                    continue
                if item not in output:
                    output.append(item)
            if output:
                return output
            return [text]
        return []

    def _to_title(self, text: str, *, fallback: str) -> str:
        cleaned = str(text).strip()
        if not cleaned:
            return fallback
        return cleaned[:1].upper() + cleaned[1:80]

    def _bullet_or_default(self, values: Any, *, default: str) -> list[str]:
        if not isinstance(values, list):
            return [f"  - {default}"]
        bullets = [f"  - {str(item)}" for item in values if str(item).strip()]
        return bullets if bullets else [f"  - {default}"]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
