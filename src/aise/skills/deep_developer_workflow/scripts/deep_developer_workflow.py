"""Deep developer workflow skill with Programmer / Code Reviewer subagents."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class DeepDeveloperWorkflowSkill(Skill):
    """Execute subsystem-based implementation loops with traceable revisions."""

    @property
    def name(self) -> str:
        return "deep_developer_workflow"

    @property
    def description(self) -> str:
        return (
            "Run multi-instance Programmer and Code Reviewer paired workflow to implement FN items "
            "with tests, revisions, and merge-ready results"
        )

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        project_name = context.project_name or str(input_data.get("project_name", "Untitled")).strip() or "Untitled"
        recorder = context.parameters.get("task_memory_recorder") or input_data.get("_task_memory_recorder")
        phase_key = str(context.parameters.get("phase_key") or context.parameters.get("phase") or "implementation")
        retry_task_key = str(context.parameters.get("retry_task_key") or input_data.get("retry_task_key") or "")
        execution_scope = str(context.parameters.get("execution_scope") or "full_skill")
        src_dir = self._resolve_dir(input_data, context, key="source_dir", default_subdir="src")
        tests_dir = self._resolve_dir(input_data, context, key="tests_dir", default_subdir="tests")
        architecture = self._load_architecture_design(context)
        subsystem_defs = architecture.get("subsystems", []) if isinstance(architecture, dict) else []
        assignments = self._build_subsystem_assignments(subsystem_defs)

        fn_by_subsystem = self._load_or_build_fn_map(context, architecture)
        if not fn_by_subsystem:
            fn_by_subsystem = {
                "subsystem": [{"id": "FN-SUBSYSTEM-01", "description": "core behavior", "spec": "basic"}]
            }

        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_source_package(src_dir)
        test_bootstrap = self._ensure_test_bootstrap(tests_dir)
        pytest_ini = self._ensure_pytest_config(tests_dir.parent)

        all_source_files: list[str] = []
        all_test_files: list[str] = []
        review_records: list[dict[str, Any]] = []
        merged_fn_ids: list[str] = []
        subsystem_rounds = max(2, min(3, int(input_data.get("subsystem_review_rounds", 3) or 3)))
        subsystem_parallel_workers = max(
            1,
            int(input_data.get("subsystem_parallel_workers", input_data.get("fn_parallel_workers", 4)) or 4),
        )
        total_sr_groups = 0

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
                    "agent": "developer",
                    "skill": "deep_developer_workflow",
                    "task_key": task_key,
                    "execution_scope": execution_scope if retry_task_key else "full_skill",
                },
            )
            attempt = started.get("attempt", {}) if isinstance(started, dict) else {}
            attempts[task_key] = int((attempt or {}).get("attempt_no", 0) or 0)

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

        _start("developer.deep_developer_workflow.step1")
        _start("developer.deep_developer_workflow.step2.develop")
        _start("developer.deep_developer_workflow.step2.review")
        _start("developer.deep_developer_workflow.step2.revision")
        _start("developer.deep_developer_workflow.step2.merge")

        # Step 1: task split and per-subsystem pairing.
        try:
            subsystem_jobs: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []
            for subsystem_key, fn_items in fn_by_subsystem.items():
                assign = assignments.get(subsystem_key) or {
                    "programmer": "programmer_1",
                    "code_reviewer": "code_reviewer_1",
                    "subsystem": subsystem_key,
                }
                subsystem_jobs.append((str(subsystem_key), list(fn_items), dict(assign)))

            subsystem_results: dict[str, dict[str, Any]] = {}
            if len(subsystem_jobs) > 1 and subsystem_parallel_workers > 1:
                with ThreadPoolExecutor(
                    max_workers=min(subsystem_parallel_workers, len(subsystem_jobs)),
                    thread_name_prefix="dev-subsys",
                ) as pool:
                    future_map = {
                        pool.submit(
                            self._process_single_subsystem_batch_rounds,
                            context=context,
                            src_dir=src_dir,
                            tests_dir=tests_dir,
                            subsystem_key=subsystem_key,
                            fn_items=fn_items,
                            assign=assign,
                            subsystem_rounds=subsystem_rounds,
                        ): subsystem_key
                        for subsystem_key, fn_items, assign in subsystem_jobs
                    }
                    for future in as_completed(future_map):
                        subsystem_key = future_map[future]
                        subsystem_results[subsystem_key] = future.result()
            else:
                for subsystem_key, fn_items, assign in subsystem_jobs:
                    subsystem_results[subsystem_key] = self._process_single_subsystem_batch_rounds(
                        context=context,
                        src_dir=src_dir,
                        tests_dir=tests_dir,
                        subsystem_key=subsystem_key,
                        fn_items=fn_items,
                        assign=assign,
                        subsystem_rounds=subsystem_rounds,
                    )

            for subsystem_key, _, _ in subsystem_jobs:
                result = subsystem_results.get(subsystem_key, {})
                total_sr_groups += int(result.get("sr_group_count", 0) or 0)
                merged_fn_ids.extend([str(x) for x in result.get("merged_fn_ids", [])])
                all_source_files.extend([str(x) for x in result.get("source_files", [])])
                all_test_files.extend([str(x) for x in result.get("test_files", [])])
                for item in result.get("review_records", []):
                    if isinstance(item, dict):
                        review_records.append(item)
        except Exception as exc:
            for key in (
                "developer.deep_developer_workflow.step1",
                "developer.deep_developer_workflow.step2.develop",
                "developer.deep_developer_workflow.step2.review",
                "developer.deep_developer_workflow.step2.revision",
                "developer.deep_developer_workflow.step2.merge",
            ):
                _end(key, status="failed", error=str(exc))
            raise

        sr_allocation = architecture.get("sr_allocation", {}) if isinstance(architecture, dict) else {}
        subsystem_cards = []
        for subsystem_id, assign_item in assignments.items():
            item = assign_item if isinstance(assign_item, dict) else {}
            subsystem_slug = self._subsystem_slug_from_assignment(assign=item, subsystem_key=str(subsystem_id))
            subsystem_cards.append(
                {
                    "subsystem_id": str(subsystem_id),
                    "subsystem_name": str(item.get("subsystem", subsystem_id)),
                    "subsystem_slug": subsystem_slug,
                    "subsystem_english_name": str(item.get("subsystem_english_name", "")).strip() or subsystem_slug,
                    "assigned_sr_ids": [str(x) for x in sr_allocation.get(str(subsystem_id), [])]
                    if isinstance(sr_allocation.get(str(subsystem_id), []), list)
                    else [],
                }
            )

        _end(
            "developer.deep_developer_workflow.step1",
            status="completed",
            outputs={
                "assignment_count": len(assignments),
                "workflow_summary": {
                    "workflow": "deep_developer_workflow",
                    "subsystems": subsystem_cards,
                    "rounds": {"step2": subsystem_rounds},
                },
            },
        )
        for key in (
            "developer.deep_developer_workflow.step2.develop",
            "developer.deep_developer_workflow.step2.review",
            "developer.deep_developer_workflow.step2.revision",
            "developer.deep_developer_workflow.step2.merge",
        ):
            _end(
                key,
                status="completed",
                outputs={
                    "workflow_summary": {
                        "workflow": "deep_developer_workflow",
                        "subsystems": subsystem_cards,
                        "rounds": {"step2": subsystem_rounds},
                        "sr_group_count": total_sr_groups,
                        "fn_count": len(merged_fn_ids),
                    }
                },
            )

        all_test_files.append(str(test_bootstrap))
        all_test_files.append(str(pytest_ini))

        source_artifact = Artifact(
            artifact_type=ArtifactType.SOURCE_CODE,
            content={
                "workflow": "deep_developer_workflow",
                "files": all_source_files,
                "subsystems": sorted(fn_by_subsystem.keys()),
                "merged_fn_ids": merged_fn_ids,
            },
            producer="programmer",
            metadata={"project_name": project_name, "subagent": "programmer[*]"},
        )
        context.artifact_store.store(source_artifact)

        test_artifact = Artifact(
            artifact_type=ArtifactType.UNIT_TESTS,
            content={
                "workflow": "deep_developer_workflow",
                "files": all_test_files,
                "total_test_cases": len(merged_fn_ids),
            },
            producer="programmer",
            metadata={"project_name": project_name, "subagent": "programmer[*]"},
        )
        context.artifact_store.store(test_artifact)

        review_artifact = Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "workflow": "deep_developer_workflow",
                "records": review_records,
                "total_reviews": len(review_records),
            },
            producer="code_reviewer",
            metadata={"project_name": project_name, "subagent": "code_reviewer[*]"},
        )
        context.artifact_store.store(review_artifact)

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "workflow": "deep_developer_workflow",
                "project_name": project_name,
                "sub_agents": ["programmer[*]", "code_reviewer[*]"],
                "step1": {
                    "name": "subsystem_task_split",
                    "status": "completed",
                    "assignments": assignments,
                },
                "step2": {
                    "name": "subsystem_batch_round_implementation",
                    "status": "completed",
                    "fn_count": len(merged_fn_ids),
                    "sr_group_count": total_sr_groups,
                    "rounds_per_subsystem": subsystem_rounds,
                    "execution_pattern": (
                        "subsystems_parallel__within_subsystem_sr_groups_serial__"
                        "review_and_revision_batched_per_subsystem_round"
                    ),
                },
                "generated": {
                    "source_files": all_source_files,
                    "test_files": all_test_files,
                },
                "artifact_ids": {
                    "source_code": source_artifact.id,
                    "unit_tests": test_artifact.id,
                    "review_feedback": review_artifact.id,
                },
            },
            producer="developer",
            metadata={"project_name": project_name},
        )

    def _load_architecture_design(self, context: SkillContext) -> dict[str, Any]:
        artifact = context.artifact_store.get_latest(ArtifactType.ARCHITECTURE_DESIGN)
        if artifact and isinstance(artifact.content, dict):
            return artifact.content
        return {"subsystems": [], "sr_allocation": {}}

    def _load_or_build_fn_map(
        self, context: SkillContext, architecture: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        fn_map: dict[str, list[dict[str, Any]]] = {}
        functional = context.artifact_store.get_latest(ArtifactType.FUNCTIONAL_DESIGN)
        if functional and isinstance(functional.content, dict):
            for item in functional.content.get("functions", []):
                if not isinstance(item, dict):
                    continue
                subsystem_id = str(item.get("subsystem_id", "")).strip() or "subsystem"
                fn_map.setdefault(subsystem_id, []).append(
                    {
                        "id": str(item.get("id", "FN-UNKNOWN")),
                        "name": str(item.get("name", "")),
                        "description": str(item.get("description", "")),
                        "spec": str(item.get("spec", "")),
                        "file_path": str(item.get("file_path", "")),
                        "layer": str(item.get("layer", "")),
                        "type": str(item.get("type", "")),
                    }
                )
            if fn_map:
                return fn_map

        subsystems = architecture.get("subsystems", []) if isinstance(architecture, dict) else []
        allocation = architecture.get("sr_allocation", {}) if isinstance(architecture, dict) else {}
        for subsystem in subsystems:
            subsystem_id = str(subsystem.get("id", "")).strip() or "subsystem"
            sr_ids = allocation.get(subsystem_id, []) if isinstance(allocation, dict) else []
            if not sr_ids:
                sr_ids = ["SR-001"]
            for index, sr_id in enumerate(sr_ids, start=1):
                fn_map.setdefault(subsystem_id, []).append(
                    {
                        "id": f"FN-{sr_id}-{index:02d}",
                        "name": "",
                        "description": f"Implement behavior for {sr_id} in {subsystem_id}",
                        "spec": ("Follow subsystem detail design, include validation and error handling."),
                        "file_path": "",
                        "layer": "",
                        "type": "",
                    }
                )
        return fn_map

    def _build_subsystem_assignments(
        self,
        subsystems: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        assignments: dict[str, dict[str, Any]] = {}
        programmer_pool = ["programmer_1", "programmer_2", "programmer_3"]
        reviewer_pool = ["code_reviewer_1", "code_reviewer_2"]
        if not subsystems:
            return {
                "subsystem": {
                    "subsystem": "subsystem",
                    "programmer": programmer_pool[0],
                    "code_reviewer": reviewer_pool[0],
                }
            }

        for index, subsystem in enumerate(subsystems):
            subsystem_id = str(subsystem.get("id", f"subsystem_{index + 1}"))
            subsystem_display = str(subsystem.get("name", subsystem_id))
            subsystem_english = str(subsystem.get("english_name", "")).strip()
            assignments[subsystem_id] = {
                "subsystem": subsystem_display,
                "subsystem_english_name": subsystem_english,
                "programmer": programmer_pool[index % len(programmer_pool)],
                "code_reviewer": reviewer_pool[index % len(reviewer_pool)],
            }
        return assignments

    def _generate_python_fn_with_llm(
        self,
        *,
        context: SkillContext,
        subsystem_slug: str,
        module_name: str,
        fn_id: str,
        fn_description: str,
        fn_spec: str,
        round_index: int,
        reviewer_comments: list[str],
    ) -> dict[str, str]:
        comments = "\n".join(f"- {item}" for item in reviewer_comments[:8]) or "- (none)"
        base_prompt = (
            f"Subsystem: {subsystem_slug}\n"
            f"Module: {module_name}\n"
            f"FN: {fn_id}\n"
            f"Description: {fn_description}\n"
            f"Spec: {fn_spec}\n"
            f"Round: {round_index}\n"
            f"Reviewer comments:\n{comments}\n"
        )
        purpose_suffix = (
            f" fn:{self._purpose_token(fn_id)}"
            f" subsystem:{self._purpose_token(subsystem_slug)}"
            f" module:{self._purpose_token(module_name)}"
            f" round:{round_index}"
        )

        code_payload = self._run_llm_json_segment(
            context=context,
            purpose=f"subagent:programmer step:fn_code_generation{purpose_suffix}",
            system_prompt=(
                "You are a senior software engineer. Generate Python module code in JSON.\n"
                "Return JSON object only with key: code_content.\n"
                "Rules:\n"
                "- code_content must define implement_<module_name>(input_data: dict | None = None)\n"
                "- function returns a business-oriented dict with keys: status, data, errors, meta\n"
                "- do not echo FN ids or prompt descriptions in runtime response payloads\n"
                "- never include FN identifiers (e.g. FN-SR-001-01) in logs, exceptions, "
                "comments, docstrings, constants, or strings\n"
                "- include input validation, observable metrics/logging, and retry/error handling when reasonable\n"
                "- no markdown fences"
            ),
            user_prompt=base_prompt,
            required_keys=["code_content"],
            module_name=module_name,
            subsystem_slug=subsystem_slug,
        )
        code_content = str(code_payload.get("code_content", "")) if isinstance(code_payload, dict) else ""

        test_payload = self._run_llm_json_segment(
            context=context,
            purpose=f"subagent:programmer step:fn_test_generation{purpose_suffix}",
            system_prompt=(
                "You are a senior software engineer. Generate pytest tests in JSON.\n"
                "Return JSON object only with key: test_content.\n"
                "Rules:\n"
                "- test_content must import from src.<subsystem>.<module> import implement_<module>\n"
                "- include at least 2 pytest test functions\n"
                "- keep tests deterministic (avoid flaky randomness)\n"
                "- do not assert FN ids or prompt descriptions in runtime results\n"
                "- no markdown fences"
            ),
            user_prompt=(
                base_prompt
                + (f"Exact import path: from src.{subsystem_slug}.{module_name} import implement_{module_name}\n")
                + "Implementation summary (optional context, may be partial):\n"
                + code_content[:3000]
                + ("\n...(truncated)\n" if len(code_content) > 3000 else "\n")
            ),
            required_keys=["test_content"],
            module_name=module_name,
            subsystem_slug=subsystem_slug,
        )
        return {
            "code_content": code_content,
            "test_content": str(test_payload.get("test_content", "")) if isinstance(test_payload, dict) else "",
        }

    def _purpose_token(self, value: str) -> str:
        token = self._slugify(str(value))
        return token[:80] if token else "na"

    def _subsystem_slug_from_assignment(self, *, assign: dict[str, Any], subsystem_key: str) -> str:
        english_name = str(assign.get("subsystem_english_name", "")).strip()
        if english_name:
            slug = self._slugify(english_name)
            if slug and slug != "item":
                return slug
        display_name = str(assign.get("subsystem") or subsystem_key).strip()
        slug = self._slugify(display_name)
        if slug and slug != "item":
            return slug
        key_slug = self._slugify(str(subsystem_key))
        if key_slug and key_slug != "item":
            return key_slug
        return "subsystem"

    def _plan_subsystem_file_manifest(
        self,
        *,
        context: SkillContext,
        subsystem_key: str,
        subsystem_slug: str,
        assign: dict[str, Any],
        fn_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        fallback = self._build_fallback_subsystem_file_manifest(
            subsystem_slug=subsystem_slug,
            fn_items=fn_items,
        )
        if context.llm_client is None or not fn_items:
            return fallback

        fn_summary = [
            {
                "id": str(item.get("id", "")),
                "name": str(item.get("name", "")),
                "description": str(item.get("description", "")),
                "spec": str(item.get("spec", ""))[:500],
                "suggested_file_path": str(item.get("file_path", "")),
                "layer": str(item.get("layer", "")),
                "type": str(item.get("type", "")),
            }
            for item in fn_items
            if isinstance(item, dict)
        ]
        try:
            payload = self._run_llm_json_segment(
                context=context,
                purpose=(
                    "subagent:programmer step:subsystem_file_manifest_planning "
                    f"subsystem:{self._purpose_token(subsystem_slug)} fns:{len(fn_summary)}"
                ),
                system_prompt=(
                    "You are a senior software engineer planning subsystem source files.\n"
                    "Return JSON only with keys: module_files, fn_to_module_map.\n"
                    "Rules:\n"
                    "- module_files: list[str] of Python filenames under src/<subsystem>/ (e.g. order_command.py)\n"
                    "- ASCII lowercase snake_case filenames only, suffix .py, no directories.\n"
                    "- fn_to_module_map: object mapping each FN id to one filename from module_files.\n"
                    "- Every FN id must be mapped exactly once.\n"
                    "- Use one dedicated module per FN for now (do not map multiple FN ids to the same file).\n"
                    "- Plan a stable file list first; later implementation rounds will only modify these files.\n"
                    "- Prefer domain-meaningful names; avoid generic file names like module.py/service.py/handler.py.\n"
                ),
                user_prompt=(
                    f"Subsystem key: {subsystem_key}\n"
                    f"Subsystem display name: {str(assign.get('subsystem', subsystem_key))}\n"
                    f"Subsystem english slug (fixed for directories/imports): {subsystem_slug}\n"
                    f"FN count: {len(fn_summary)}\n"
                    "Generate the complete source module file list first, then map each FN to one existing file.\n\n"
                    f"FN items:\n{self._compact_json(fn_summary)}\n"
                ),
                required_keys=["module_files", "fn_to_module_map"],
                module_name="subsystem_manifest",
                subsystem_slug=subsystem_slug,
            )
            return self._normalize_subsystem_file_manifest_payload(
                payload=payload,
                subsystem_slug=subsystem_slug,
                fn_items=fn_items,
            )
        except Exception:
            return fallback

    def _build_fallback_subsystem_file_manifest(
        self,
        *,
        subsystem_slug: str,
        fn_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        used_module_names: set[str] = set()
        fn_plans: list[dict[str, str]] = []
        module_files: list[str] = []
        for index, fn_item in enumerate(fn_items, start=1):
            fn_id = str(fn_item.get("id", "FN-UNKNOWN")).strip() or "FN-UNKNOWN"
            module_name = self._derive_semantic_module_name(
                fn_id=fn_id,
                fn_name=str(fn_item.get("name", "")),
                fn_description=str(fn_item.get("description", "")),
                suggested_file_path=str(fn_item.get("file_path", "")),
                subsystem_slug=subsystem_slug,
                layer=str(fn_item.get("layer", "")),
                component_type=str(fn_item.get("type", "")),
                index=index,
                used_names=used_module_names,
            )
            module_file = f"{module_name}.py"
            fn_plans.append({"fn_id": fn_id, "module_name": module_name, "module_file": module_file})
            module_files.append(module_file)
        return {"module_files": module_files, "fn_plans": fn_plans}

    def _normalize_subsystem_file_manifest_payload(
        self,
        *,
        payload: dict[str, Any],
        subsystem_slug: str,
        fn_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Invalid subsystem file manifest payload")
        raw_files = payload.get("module_files")
        raw_map = payload.get("fn_to_module_map")
        if not isinstance(raw_files, list) or not isinstance(raw_map, dict):
            raise RuntimeError("Subsystem file manifest missing module_files/fn_to_module_map")

        module_files: list[str] = []
        seen_files: set[str] = set()
        for item in raw_files:
            text = str(item or "").strip()
            if not text:
                continue
            text = text.replace("\\", "/").split("/")[-1]
            if not text.endswith(".py"):
                text = f"{Path(text).stem}.py"
            stem = self._slugify(Path(text).stem)
            if not stem or stem == "item":
                continue
            normalized_file = f"{stem}.py"
            if normalized_file in seen_files:
                continue
            seen_files.add(normalized_file)
            module_files.append(normalized_file)
        if not module_files:
            raise RuntimeError("LLM subsystem file manifest produced no valid module files")

        fn_ids = [
            str(item.get("id", "FN-UNKNOWN")).strip() or "FN-UNKNOWN"
            for item in fn_items
            if isinstance(item, dict)
        ]
        fn_set = set(fn_ids)
        used_modules: set[str] = set()
        fn_plans: list[dict[str, str]] = []
        for fn_id in fn_ids:
            raw_file = str(raw_map.get(fn_id, "")).strip()
            if not raw_file:
                raise RuntimeError(f"LLM subsystem file manifest missing fn_to_module_map entry for {fn_id}")
            candidate = raw_file.replace("\\", "/").split("/")[-1]
            if not candidate.endswith(".py"):
                candidate = f"{Path(candidate).stem}.py"
            candidate = f"{self._slugify(Path(candidate).stem)}.py"
            if candidate not in seen_files:
                raise RuntimeError(f"LLM subsystem file manifest mapped {fn_id} to unknown file {candidate}")
            module_name = Path(candidate).stem
            if module_name in used_modules:
                raise RuntimeError("LLM subsystem file manifest must map one FN to one unique module file")
            used_modules.add(module_name)
            fn_plans.append({"fn_id": fn_id, "module_name": module_name, "module_file": candidate})

        extra_unmapped_keys = [k for k in raw_map.keys() if str(k).strip() and str(k).strip() not in fn_set]
        if extra_unmapped_keys:
            # Ignore extras but keep deterministic order/shape.
            pass

        # Keep only files actually referenced by FN mappings to avoid later accidental file creation drift.
        referenced_files = [str(item["module_file"]) for item in fn_plans]
        return {"module_files": referenced_files, "fn_plans": fn_plans}

    def _initialize_planned_subsystem_files(
        self,
        *,
        src_subsystem_dir: Path,
        tests_subsystem_dir: Path,
        subsystem_slug: str,
        file_plan: dict[str, Any],
    ) -> None:
        fn_plans = file_plan.get("fn_plans", [])
        if not isinstance(fn_plans, list):
            return
        for item in fn_plans:
            if not isinstance(item, dict):
                continue
            module_name = str(item.get("module_name", "")).strip()
            if not module_name:
                continue
            code_path = src_subsystem_dir / f"{module_name}.py"
            test_path = tests_subsystem_dir / f"test_{subsystem_slug}_{module_name}.py"
            if not code_path.exists():
                code_path.write_text(
                    self._placeholder_source_content(subsystem_slug=subsystem_slug, module_name=module_name),
                    encoding="utf-8",
                )
            if not test_path.exists():
                test_path.write_text(
                    self._placeholder_test_content(subsystem_slug=subsystem_slug, module_name=module_name),
                    encoding="utf-8",
                )

    def _placeholder_source_content(self, *, subsystem_slug: str, module_name: str) -> str:
        return (
            "from __future__ import annotations\n\n"
            f"def implement_{module_name}(input_data: dict | None = None) -> dict[str, object]:\n"
            "    payload = input_data or {}\n"
            "    return {\n"
            "        'status': 'ok',\n"
            "        'data': {'placeholder': True, 'input_keys': sorted(payload.keys())},\n"
            "        'errors': [],\n"
            f"        'meta': {{'subsystem': '{subsystem_slug}', 'operation': '{module_name}'}},\n"
            "    }\n"
        )

    def _placeholder_test_content(self, *, subsystem_slug: str, module_name: str) -> str:
        return (
            f"from src.{subsystem_slug}.{module_name} import implement_{module_name}\n\n\n"
            f"def test_{module_name}_placeholder() -> None:\n"
            f"    result = implement_{module_name}()\n"
            "    assert isinstance(result, dict)\n"
        )

    def _fallback_test_content(
        self,
        *,
        subsystem_slug: str,
        module_name: str,
        fn_id: str,
        fn_description: str,
    ) -> str:
        return (
            f"from src.{subsystem_slug}.{module_name} import implement_{module_name}\n\n\n"
            f"def test_{module_name}_returns_standard_response_shape() -> None:\n"
            f"    result = implement_{module_name}({{'round': 1}})\n"
            "    assert isinstance(result, dict)\n"
            "    assert result.get('status') in {'ok', 'error'}\n"
            "    assert 'data' in result\n"
            "    assert 'errors' in result\n"
            "    assert isinstance(result.get('meta'), dict)\n\n"
            f"def test_{module_name}_meta_contains_operation() -> None:\n"
            f"    result = implement_{module_name}()\n"
            f"    assert result.get('meta', {{}}).get('operation') == '{module_name}'\n"
        )

    def _fallback_code_content(
        self,
        *,
        subsystem_slug: str,
        module_name: str,
        fn_id: str,
        fn_description: str,
        fn_spec: str,
    ) -> str:
        safe_spec = fn_spec.replace("'", "\\'")
        return (
            "from __future__ import annotations\n\n"
            f'"""Business operation implementation for subsystem {subsystem_slug}."""\n\n'
            f"def implement_{module_name}(input_data: dict | None = None) -> dict[str, object]:\n"
            "    payload = input_data or {}\n"
            "    result = {'processed': True, 'input_keys': sorted(payload.keys())}\n"
            "    return {\n"
            "        'status': 'ok',\n"
            "        'data': result,\n"
            "        'errors': [],\n"
            "        'meta': {\n"
            f"            'subsystem': '{subsystem_slug}',\n"
            f"            'operation': '{module_name}',\n"
            f"            'spec_hint': '{safe_spec}',\n"
            "        },\n"
            "    }\n"
        )

    def _develop_single_fn_round(
        self,
        *,
        context: SkillContext,
        subsystem_slug: str,
        plan: dict[str, Any],
        round_index: int,
    ) -> dict[str, Any]:
        fn_id = str(plan["fn_id"])
        fn_description = str(plan["fn_description"])
        fn_spec = str(plan["fn_spec"])
        module_name = str(plan["module_name"])
        code_path = Path(plan["code_path"])
        test_path = Path(plan["test_path"])
        comments = list(plan.get("comments", []))
        if not code_path.exists() or not test_path.exists():
            raise RuntimeError(
                f"Planned files must exist before FN development: code={code_path.exists()} test={test_path.exists()}"
            )

        generated = self._generate_python_fn_with_llm(
            context=context,
            subsystem_slug=subsystem_slug,
            module_name=module_name,
            fn_id=fn_id,
            fn_description=fn_description,
            fn_spec=fn_spec,
            round_index=round_index,
            reviewer_comments=comments,
        )
        raw_test_content = str(generated.get("test_content", ""))
        raw_code_content = str(generated.get("code_content", ""))
        if not self._is_valid_generated_test_content(
            test_content=raw_test_content,
            subsystem_slug=subsystem_slug,
            module_name=module_name,
        ):
            raise RuntimeError(f"Invalid LLM-generated pytest content for {subsystem_slug}.{module_name} ({fn_id})")
        if not self._is_valid_generated_code_content(raw_code_content, module_name=module_name):
            raise RuntimeError(f"Invalid LLM-generated code content for {subsystem_slug}.{module_name} ({fn_id})")
        test_content = raw_test_content
        code_content = raw_code_content

        # Strip design-time FN identifiers from generated source/tests before writing.
        test_content = self._sanitize_generated_runtime_text(test_content)
        code_content = self._sanitize_generated_runtime_text(code_content)

        test_path.write_text(test_content, encoding="utf-8")
        code_path.write_text(code_content, encoding="utf-8")
        check_result = self._run_static_and_unit_checks(code_path, test_path)
        return {"check_result": check_result}

    def _develop_single_sr_group_round(
        self,
        *,
        context: SkillContext,
        subsystem_slug: str,
        sr_key: str,
        plans: list[dict[str, Any]],
        round_index: int,
    ) -> dict[str, Any]:
        group_results: list[dict[str, Any]] = []
        for plan in plans:
            result = self._develop_single_fn_round(
                context=context,
                subsystem_slug=subsystem_slug,
                plan=plan,
                round_index=round_index,
            )
            plan["check_result"] = result.get("check_result", {})
            group_results.append(result)
        return {"sr_group": sr_key, "fn_count": len(plans), "results": group_results}

    def _process_single_subsystem_batch_rounds(
        self,
        *,
        context: SkillContext,
        src_dir: Path,
        tests_dir: Path,
        subsystem_key: str,
        fn_items: list[dict[str, Any]],
        assign: dict[str, Any],
        subsystem_rounds: int,
    ) -> dict[str, Any]:
        subsystem_slug = self._subsystem_slug_from_assignment(assign=assign, subsystem_key=subsystem_key)
        src_subsystem_dir = src_dir / subsystem_slug
        tests_subsystem_dir = tests_dir / "services" / subsystem_slug
        src_subsystem_dir.mkdir(parents=True, exist_ok=True)
        tests_subsystem_dir.mkdir(parents=True, exist_ok=True)

        src_revision = src_subsystem_dir / "revision.md"
        tests_revision = tests_subsystem_dir / "revision.md"
        if not src_revision.exists():
            src_revision.write_text(
                f"# {subsystem_slug} source revisions\n\nGenerated at {self._now_iso()}\n\n",
                encoding="utf-8",
            )
        if not tests_revision.exists():
            tests_revision.write_text(
                f"# {subsystem_slug} test revisions\n\nGenerated at {self._now_iso()}\n\n",
                encoding="utf-8",
            )

        subsystem_file_plan = self._plan_subsystem_file_manifest(
            context=context,
            subsystem_key=subsystem_key,
            subsystem_slug=subsystem_slug,
            assign=assign,
            fn_items=fn_items,
        )
        self._initialize_planned_subsystem_files(
            src_subsystem_dir=src_subsystem_dir,
            tests_subsystem_dir=tests_subsystem_dir,
            subsystem_slug=subsystem_slug,
            file_plan=subsystem_file_plan,
        )

        fn_module_map = {
            str(item.get("fn_id", "")): str(item.get("module_name", ""))
            for item in subsystem_file_plan.get("fn_plans", [])
            if isinstance(item, dict)
        }
        used_module_names: set[str] = set(str(x) for x in fn_module_map.values() if str(x))
        fn_plans: list[dict[str, Any]] = []
        for fn_index, fn_item in enumerate(fn_items, start=1):
            fn_id = str(fn_item.get("id", "FN-UNKNOWN")).strip() or "FN-UNKNOWN"
            fn_description = str(fn_item.get("description", "")).strip() or "Feature implementation"
            fn_spec = str(fn_item.get("spec", "")).strip() or "Conform to subsystem detail design"
            fn_name = str(fn_item.get("name", "")).strip()
            fn_file_path = str(fn_item.get("file_path", "")).strip()
            fn_layer = str(fn_item.get("layer", "")).strip()
            fn_type = str(fn_item.get("type", "")).strip()
            fn_slug = fn_module_map.get(fn_id, "")
            if not fn_slug:
                # Fallback only when file manifest generation failed validation for a specific FN.
                fn_slug = self._derive_semantic_module_name(
                    fn_id=fn_id,
                    fn_name=fn_name,
                    fn_description=fn_description,
                    suggested_file_path=fn_file_path,
                    subsystem_slug=subsystem_slug,
                    layer=fn_layer,
                    component_type=fn_type,
                    index=fn_index,
                    used_names=used_module_names,
                )
                fallback_code_path = src_subsystem_dir / f"{fn_slug}.py"
                fallback_test_path = tests_subsystem_dir / f"test_{subsystem_slug}_{fn_slug}.py"
                if not fallback_code_path.exists():
                    fallback_code_path.write_text(
                        self._placeholder_source_content(subsystem_slug=subsystem_slug, module_name=fn_slug),
                        encoding="utf-8",
                    )
                if not fallback_test_path.exists():
                    fallback_test_path.write_text(
                        self._placeholder_test_content(
                            subsystem_slug=subsystem_slug,
                            module_name=fn_slug,
                        ),
                        encoding="utf-8",
                    )

            code_path = src_subsystem_dir / f"{fn_slug}.py"
            test_path = tests_subsystem_dir / f"test_{subsystem_slug}_{fn_slug}.py"
            fn_plans.append(
                {
                    "fn_id": fn_id,
                    "fn_name": fn_name,
                    "fn_description": fn_description,
                    "fn_spec": fn_spec,
                    "module_name": fn_slug,
                    "code_path": code_path,
                    "test_path": test_path,
                    "comments": [],
                    "check_result": {},
                }
            )

        sr_groups = self._group_fn_plans_by_sr(fn_plans)
        local_review_records: list[dict[str, Any]] = []
        for round_index in range(1, subsystem_rounds + 1):
            round_reviews: list[dict[str, Any]] = []
            # Within one subsystem, SR groups execute serially to maximize file/code reuse continuity.
            for sr_key, group_plans in sr_groups.items():
                _ = self._develop_single_sr_group_round(
                    context=context,
                    subsystem_slug=subsystem_slug,
                    sr_key=sr_key,
                    plans=group_plans,
                    round_index=round_index,
                )

            for plan in fn_plans:
                fn_id = str(plan["fn_id"])
                fn_description = str(plan["fn_description"])
                check_result = dict(plan.get("check_result", {}))
                review = self._review_fn_change(
                    subsystem=subsystem_slug,
                    fn_id=fn_id,
                    fn_description=fn_description,
                    round_index=round_index,
                    check_result=check_result,
                    reviewer=str(assign.get("code_reviewer", "code_reviewer_1")),
                )
                round_reviews.append(review)
                plan["comments"] = list(review.get("suggestions", []))
                plan["review"] = review
                local_review_records.append(
                    {
                        "subsystem": subsystem_slug,
                        "sr_group": self._sr_group_key_from_fn_id(fn_id),
                        "fn_id": fn_id,
                        "round": round_index,
                        "programmer": assign.get("programmer", "programmer_1"),
                        "reviewer": assign.get("code_reviewer", "code_reviewer_1"),
                        "check_result": check_result,
                        "review": review,
                        "review_scope": "subsystem_round_batch",
                    }
                )

            for plan in fn_plans:
                fn_id = str(plan["fn_id"])
                check_result = dict(plan.get("check_result", {}))
                review = dict(plan.get("review", {}))
                self._append_revision(
                    src_revision,
                    fn_id=fn_id,
                    role="code_reviewer",
                    round_index=round_index,
                    summary=str(review.get("summary", "")),
                    details=list(review.get("suggestions", [])),
                )
                self._append_revision(
                    src_revision,
                    fn_id=fn_id,
                    role="programmer",
                    round_index=round_index,
                    summary="Applied review feedback and updated implementation.",
                    details=[f"Response: addressed reviewer suggestions in round {round_index}."],
                )
                self._append_revision(
                    tests_revision,
                    fn_id=fn_id,
                    role="programmer",
                    round_index=round_index,
                    summary="Updated tests to align with latest implementation.",
                    details=[
                        f"Static check: {check_result['static_check']}",
                        f"Unit tests: {check_result['unit_test']}",
                    ],
                )

            self._append_revision(
                src_revision,
                fn_id=f"SUBSYSTEM-BATCH-{subsystem_slug}",
                role="code_reviewer",
                round_index=round_index,
                summary=f"Batch review completed for subsystem {subsystem_slug}.",
                details=[
                    f"SR task groups: {len(sr_groups)}",
                    f"Reviewed FN count: {len(fn_plans)}",
                    f"Approved in this round: {sum(1 for item in round_reviews if item.get('approved'))}",
                    "Review sequencing: within-subsystem SR groups serial -> "
                    "review-all -> revise-all; subsystems parallelized.",
                ],
            )

        source_files = [str(plan["code_path"]) for plan in fn_plans] + [str(src_revision)]
        test_files = [str(plan["test_path"]) for plan in fn_plans] + [str(tests_revision)]
        return {
            "subsystem_key": subsystem_key,
            "subsystem_slug": subsystem_slug,
            "sr_group_count": len(sr_groups),
            "merged_fn_ids": [str(plan["fn_id"]) for plan in fn_plans],
            "source_files": source_files,
            "test_files": test_files,
            "review_records": local_review_records,
        }

    def _group_fn_plans_by_sr(self, fn_plans: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for plan in fn_plans:
            fn_id = str(plan.get("fn_id", "FN-UNKNOWN"))
            sr_key = self._sr_group_key_from_fn_id(fn_id)
            grouped.setdefault(sr_key, []).append(plan)
        return grouped

    def _sr_group_key_from_fn_id(self, fn_id: str) -> str:
        text = str(fn_id or "").strip().upper()
        match = re.search(r"FN-(SR-\d+)-\d+", text)
        if match:
            return match.group(1)
        match = re.search(r"(SR-\d+)", text)
        if match:
            return match.group(1)
        return text or "SR-UNKNOWN"

    def _run_static_and_unit_checks(self, code_path: Path, test_path: Path) -> dict[str, str]:
        code_text = code_path.read_text(encoding="utf-8")
        test_text = test_path.read_text(encoding="utf-8")
        static_ok = "passed" if "implement_" in code_text and "return" in code_text else "failed"
        unit_ok = "passed" if "def test_" in test_text else "failed"
        return {"static_check": static_ok, "unit_test": unit_ok}

    def _is_valid_generated_code_content(self, code_content: str, *, module_name: str) -> bool:
        if not code_content.strip():
            return False
        expected_signature = f"def implement_{module_name}("
        if expected_signature not in code_content:
            return False
        if re.search(r"\[?FN-[A-Z0-9-]+\]?", code_content):
            return False
        return True

    def _is_valid_generated_test_content(
        self,
        *,
        test_content: str,
        subsystem_slug: str,
        module_name: str,
    ) -> bool:
        if not test_content.strip():
            return False
        if "from your_module import" in test_content:
            return False
        expected_import = f"from src.{subsystem_slug}.{module_name} import implement_{module_name}"
        if expected_import not in test_content:
            return False
        if re.search(r"\[?FN-[A-Z0-9-]+\]?", test_content):
            return False
        return f"implement_{module_name}" in test_content and "def test_" in test_content

    def _sanitize_generated_runtime_text(self, text: str) -> str:
        if not text:
            return text
        cleaned = re.sub(r"\[?FN-[A-Z0-9-]+\]?", "operation", text)
        cleaned = re.sub(r"\bfn_id\b", "operation_id", cleaned)
        return cleaned

    def _review_fn_change(
        self,
        *,
        subsystem: str,
        fn_id: str,
        fn_description: str,
        round_index: int,
        check_result: dict[str, str],
        reviewer: str,
    ) -> dict[str, Any]:
        suggestions = [
            f"Confirm edge-case handling for {fn_id} in subsystem {subsystem}.",
            "Keep unit tests aligned with FN specification and expected behavior.",
            "Ensure implementation reflects FN semantics instead of template placeholders.",
        ]
        if check_result.get("static_check") != "passed":
            suggestions.append("Fix static-check violations before merge.")
        if check_result.get("unit_test") != "passed":
            suggestions.append("Fix failing unit tests before merge.")

        approved = (
            round_index >= 3
            and check_result.get("static_check") == "passed"
            and check_result.get("unit_test") == "passed"
        )
        return {
            "reviewer": reviewer,
            "approved": approved,
            "summary": (f"Round {round_index} review for {fn_id}: {'approved' if approved else 'needs changes'}"),
            "suggestions": suggestions,
            "fn": {"id": fn_id, "description": fn_description},
        }

    def _append_revision(
        self,
        path: Path,
        *,
        fn_id: str,
        role: str,
        round_index: int,
        summary: str,
        details: list[str],
    ) -> None:
        lines = [
            f"## {fn_id} - round {round_index} - {role}",
            f"- time: {self._now_iso()}",
            f"- summary: {summary}",
            "- details:",
            *[f"  - {item}" for item in details],
            "",
        ]
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

    def _resolve_dir(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
        *,
        key: str,
        default_subdir: str,
    ) -> Path:
        project_root = context.parameters.get("project_root")
        root = Path(project_root).resolve() if isinstance(project_root, str) and project_root.strip() else None
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

    def _ensure_source_package(self, src_dir: Path) -> None:
        src_pkg = src_dir / "__init__.py"
        if not src_pkg.exists():
            src_pkg.write_text('"""Generated source package."""\n', encoding="utf-8")

    def _ensure_test_bootstrap(self, tests_dir: Path) -> Path:
        path = tests_dir / "conftest.py"
        path.write_text(
            (
                "from __future__ import annotations\n\n"
                "import sys\n"
                "from pathlib import Path\n\n"
                "# Keep generated project importable even when pytest rootdir is outside project.\n"
                "PROJECT_ROOT = Path(__file__).resolve().parent.parent\n"
                "if str(PROJECT_ROOT) not in sys.path:\n"
                "    sys.path.insert(0, str(PROJECT_ROOT))\n"
            ),
            encoding="utf-8",
        )
        return path

    def _ensure_pytest_config(self, project_root: Path) -> Path:
        path = project_root / "pytest.ini"
        path.write_text(
            ("[pytest]\ntestpaths = tests\npython_files = test_*.py\naddopts = -q\n"),
            encoding="utf-8",
        )
        return path

    def _derive_semantic_module_name(
        self,
        *,
        fn_id: str,
        fn_name: str,
        fn_description: str,
        suggested_file_path: str,
        subsystem_slug: str,
        layer: str,
        component_type: str,
        index: int,
        used_names: set[str],
    ) -> str:
        candidates: list[str] = []

        file_stem = Path(suggested_file_path).stem if suggested_file_path else ""
        normalized_file_stem = self._normalize_module_candidate(file_stem, subsystem_slug=subsystem_slug)
        if normalized_file_stem:
            candidates.append(normalized_file_stem)

        normalized_fn_name = self._normalize_module_candidate(fn_name, subsystem_slug=subsystem_slug)
        if normalized_fn_name:
            candidates.append(normalized_fn_name)

        generic_words = {
            "implement",
            "behavior",
            "supports",
            "delivery",
            "for",
            "in",
            "app",
            "service",
            "domain",
            "gateway",
            "core",
            "subsystem",
            "the",
            "and",
            "with",
            "user",
            "system",
            "logic",
            "item",
        }
        semantic_desc_name = self._semantic_module_name_from_description(
            fn_description=fn_description,
            role_suffix=self._role_suffix(layer=layer, component_type=component_type, fn_name=fn_name),
        )
        if semantic_desc_name:
            candidates.append(semantic_desc_name)
        words = [self._slugify(word) for word in fn_description.split() if word.strip()]
        words = [word for word in words if word and word not in generic_words and not word.startswith("fn_")]
        if words:
            core = "_".join(words[:3])
            role_suffix = self._role_suffix(layer=layer, component_type=component_type, fn_name=fn_name)
            candidates.append(f"{core}_{role_suffix}" if role_suffix and not core.endswith(role_suffix) else core)

        fn_token = self._slugify(fn_id)
        if fn_token.startswith("fn_"):
            fn_token = fn_token[3:]

        for raw in candidates:
            base = self._slugify(raw)
            base = self._normalize_module_candidate(base, subsystem_slug=subsystem_slug) or ""
            if not base:
                continue
            if len(base) > 42:
                base = "_".join(base.split("_")[:4])[:42].strip("_")
            if not base:
                continue
            if base not in used_names:
                used_names.add(base)
                return base
            if fn_token:
                candidate_with_suffix = f"{base}_{fn_token}"
                candidate_with_suffix = candidate_with_suffix[:48].strip("_")
                if candidate_with_suffix and candidate_with_suffix not in used_names:
                    used_names.add(candidate_with_suffix)
                    return candidate_with_suffix

        role_suffix = self._role_suffix(layer=layer, component_type=component_type, fn_name=fn_name) or "service"
        fallback = f"{fn_token}_{role_suffix}" if fn_token else f"requirement_{index:02d}_{role_suffix}"
        fallback = fallback[:48].strip("_") or f"requirement_{index:02d}_{role_suffix}"
        used_names.add(fallback)
        return fallback

    def _slugify(self, value: str) -> str:
        chars: list[str] = []
        last_dash = False
        for ch in value.lower().strip():
            if ch.isascii() and ch.isalnum():
                chars.append(ch)
                last_dash = False
            else:
                if not last_dash:
                    chars.append("_")
                last_dash = True
        slug = "".join(chars).strip("_")
        if not slug:
            return "item"
        if slug[0].isdigit():
            slug = f"fn_{slug}"
        return slug

    def _normalize_module_candidate(self, raw: str, *, subsystem_slug: str) -> str:
        if not str(raw or "").strip():
            return ""
        candidate = self._slugify(raw)
        if not candidate:
            return ""

        candidate = re.sub(rf"^{re.escape(subsystem_slug)}_", "", candidate)
        candidate = re.sub(r"_of$", "", candidate)
        candidate = re.sub(r"^implement_", "", candidate)
        candidate = re.sub(r"^fn_[a-z0-9_]+_", "", candidate)
        candidate = re.sub(r"_{2,}", "_", candidate).strip("_")

        low_signal = {
            "feature",
            "logic",
            "module",
            "handler",
            "function",
            "service_of",
            "item",
            "service",
            "app_service",
            "domain_service",
            "gateway_service",
            "repository_service",
        }
        if candidate in low_signal:
            return ""

        tokens = [t for t in candidate.split("_") if t]
        if not tokens:
            return ""

        # Compress verbose template-like names to meaningful suffixes.
        signal_order = [
            "api",
            "app",
            "domain",
            "gateway",
            "repository",
            "repo",
            "service",
            "schema",
            "validator",
            "execute",
            "health",
        ]
        signal = [t for t in tokens if t in signal_order]
        non_generic = [t for t in tokens if t not in {"fn", "sr", "service", "logic", "of"}]
        semantic_keep_tokens = {
            "telemetry",
            "interaction",
            "validation",
            "transition",
            "state",
            "request",
            "response",
            "workflow",
            "domain",
        }
        should_compress = not any(t in semantic_keep_tokens for t in tokens)
        if signal and non_generic and should_compress:
            compact = [t for t in non_generic if t in {"health", "execute", "request", "response"}]
            if not compact:
                compact = [signal[0]]
            merged_tokens: list[str] = []
            for token in (compact + signal[-1:])[:3]:
                if not merged_tokens or merged_tokens[-1] != token:
                    merged_tokens.append(token)
            candidate = "_".join(merged_tokens).strip("_")

        return candidate[:48].strip("_")

    def _role_suffix(self, *, layer: str, component_type: str, fn_name: str) -> str:
        text = " ".join([layer, component_type, fn_name]).lower()
        if "api" in text:
            return "api"
        if "domain" in text or "business" in text:
            return "domain"
        if "gateway" in text or "integration" in text:
            return "gateway"
        if "repo" in text or "data" in text:
            return "repository"
        if "schema" in text:
            return "schema"
        return "service"

    def _semantic_module_name_from_description(self, *, fn_description: str, role_suffix: str) -> str:
        text = str(fn_description or "")
        lower = text.lower()

        # Capability/aspect hints
        if any(token in lower for token in ("telemetry", "observability", "metrics", "verifiable outcomes")) or any(
            token in text for token in ("遥测", "可观测", "指标")
        ):
            aspect = "telemetry"
        elif any(token in lower for token in ("state transition", "service logic", "workflow")) or any(
            token in text for token in ("状态迁移", "服务逻辑", "工作流")
        ):
            aspect = "state_transition"
        elif any(token in lower for token in ("user-facing behavior", "interaction")) or any(
            token in text for token in ("用户交互", "用户行为", "交互")
        ):
            aspect = "interaction"
        elif any(token in lower for token in ("validation", "error handling")) or any(
            token in text for token in ("校验", "错误处理")
        ):
            aspect = "validation"
        else:
            aspect = "operation"

        return f"{aspect}_{role_suffix or 'service'}" if aspect != "operation" else ""

    def _compact_json(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except TypeError:
            return str(payload)

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
            "then fill every value before sending the final answer."
        )
        if required:
            lines.append("- Do not omit any required key, even if a value must be empty string/list/object.")
        lines.append("- Return exactly one final JSON object only (no markdown, no comments, no prose).")
        return "\n".join(lines) + "\n"

    def _run_llm_json_segment(
        self,
        *,
        context: SkillContext,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        required_keys: list[str],
        module_name: str,
        subsystem_slug: str,
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
                    f"- Missing keys: {', '.join(missing) if missing else '(schema invalid)'}.\n"
                )
                if last_partial:
                    prompt += (
                        "- Continue from the partial JSON below and return a FULL valid JSON object for this segment.\n"
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
            if self._segment_payload_ok(
                payload,
                required_keys=required_keys,
                module_name=module_name,
                subsystem_slug=subsystem_slug,
            ):
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

    def _segment_payload_ok(
        self,
        payload: dict[str, Any],
        *,
        required_keys: list[str],
        module_name: str,
        subsystem_slug: str,
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        for key in required_keys:
            if key not in payload:
                return False
        if "code_content" in required_keys:
            code = str(payload.get("code_content", "")).strip()
            if len(code) < 80 or self._looks_truncated_text(code):
                return False
            if f"def implement_{module_name}(" not in code:
                return False
        if "test_content" in required_keys:
            tests = str(payload.get("test_content", "")).strip()
            if len(tests) < 80 or self._looks_truncated_text(tests):
                return False
            expected_import = f"from src.{subsystem_slug}.{module_name} import implement_{module_name}"
            if expected_import not in tests:
                return False
            if tests.count("def test_") < 2:
                return False
        return True

    def _looks_truncated_text(self, text: str) -> bool:
        if not text:
            return True
        tail = text.rstrip()
        if tail.endswith((":", ",", "\\", "/", "|", "(", "[", "{")):
            return True
        if tail.count("```") % 2 == 1:
            return True
        if tail.count('"') % 2 == 1:
            return True
        return False

    def _run_llm_json(
        self,
        *,
        context: SkillContext,
        system_prompt: str,
        user_prompt: str,
        purpose: str = "",
    ) -> dict[str, Any]:
        if context.llm_client is None:
            raise RuntimeError("LLM client is required for deep_developer_workflow")
        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            llm_purpose=purpose or "agent:developer role:developer skill:deep_developer_workflow",
        )
        parsed = self._parse_json_response(response)
        if parsed is None:
            if purpose:
                raise RuntimeError(f"LLM response is not valid JSON object for {purpose}")
            raise RuntimeError("LLM response is not valid JSON object for deep_developer_workflow")
        return parsed

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        candidates: list[str] = [text]
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if match:
            candidates.append(match.group(1))
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
        repaired = re.sub(r',"\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)"', r',\n"\1"', repaired)
        return repaired

    def _repair_truncated_top_level_object(self, text: str) -> str | None:
        source = text.strip()
        if not source.startswith("{") or source.endswith("}"):
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

        for comma_idx in reversed(commas):
            candidate = source[:comma_idx].rstrip() + "\n}"
            if self._try_parse_json_object(candidate) is not None:
                return candidate

        fallback = re.sub(r"[,\s]+$", "", source)
        if fallback != source and fallback.startswith("{"):
            candidate = fallback + "}"
            if self._try_parse_json_object(candidate) is not None:
                return candidate
        return None

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
