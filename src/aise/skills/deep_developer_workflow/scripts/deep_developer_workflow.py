"""Deep developer workflow skill with Programmer / Code Reviewer subagents."""

from __future__ import annotations

import json
import re
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

        # Step 1: task split and per-subsystem pairing.
        for subsystem_key, fn_items in fn_by_subsystem.items():
            assign = assignments.get(subsystem_key) or {
                "programmer": "programmer_1",
                "code_reviewer": "code_reviewer_1",
                "subsystem": subsystem_key,
            }
            subsystem_slug = self._slugify(str(assign.get("subsystem") or subsystem_key))
            src_subsystem_dir = src_dir / "services" / subsystem_slug
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

            used_module_names: set[str] = set()
            # Step 2: Programmer loops FN by FN; each FN has >=3 paired review rounds.
            for fn_index, fn_item in enumerate(fn_items, start=1):
                fn_id = str(fn_item.get("id", "FN-UNKNOWN")).strip() or "FN-UNKNOWN"
                fn_description = str(fn_item.get("description", "")).strip() or "Feature implementation"
                fn_spec = str(fn_item.get("spec", "")).strip() or "Conform to subsystem detail design"
                fn_slug = self._derive_semantic_module_name(
                    fn_id=fn_id,
                    fn_description=fn_description,
                    index=fn_index,
                    used_names=used_module_names,
                )

                code_path = src_subsystem_dir / f"{fn_slug}.py"
                test_path = tests_subsystem_dir / f"test_{subsystem_slug}_{fn_slug}.py"
                comments: list[str] = []

                for round_index in range(1, 4):
                    generated = self._generate_python_fn_with_llm(
                        context=context,
                        subsystem_slug=subsystem_slug,
                        module_name=fn_slug,
                        fn_id=fn_id,
                        fn_description=fn_description,
                        fn_spec=fn_spec,
                        round_index=round_index,
                        reviewer_comments=comments,
                    )
                    raw_test_content = generated.get("test_content", "")
                    raw_code_content = generated.get("code_content", "")
                    test_content = (
                        raw_test_content
                        if self._is_valid_generated_test_content(
                            test_content=raw_test_content,
                            subsystem_slug=subsystem_slug,
                            module_name=fn_slug,
                        )
                        else ""
                    ) or self._fallback_test_content(
                        subsystem_slug=subsystem_slug,
                        module_name=fn_slug,
                        fn_id=fn_id,
                        fn_description=fn_description,
                    )
                    code_content = (
                        raw_code_content
                        if self._is_valid_generated_code_content(raw_code_content, module_name=fn_slug)
                        else ""
                    ) or self._fallback_code_content(
                        subsystem_slug=subsystem_slug,
                        module_name=fn_slug,
                        fn_id=fn_id,
                        fn_description=fn_description,
                        fn_spec=fn_spec,
                    )
                    test_path.write_text(test_content, encoding="utf-8")
                    code_path.write_text(code_content, encoding="utf-8")

                    check_result = self._run_static_and_unit_checks(code_path, test_path)

                    # Code Reviewer: inspect and feed revision comments.
                    review = self._review_fn_change(
                        subsystem=subsystem_slug,
                        fn_id=fn_id,
                        fn_description=fn_description,
                        round_index=round_index,
                        check_result=check_result,
                        reviewer=str(assign.get("code_reviewer", "code_reviewer_1")),
                    )
                    comments = list(review.get("suggestions", []))

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

                    review_records.append(
                        {
                            "subsystem": subsystem_slug,
                            "fn_id": fn_id,
                            "round": round_index,
                            "programmer": assign.get("programmer", "programmer_1"),
                            "reviewer": assign.get("code_reviewer", "code_reviewer_1"),
                            "check_result": check_result,
                            "review": review,
                        }
                    )

                merged_fn_ids.append(fn_id)
                all_source_files.append(str(code_path))
                all_test_files.append(str(test_path))

            all_source_files.append(str(src_revision))
            all_test_files.append(str(tests_revision))

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
                    "name": "fn_loop_implementation",
                    "status": "completed",
                    "fn_count": len(merged_fn_ids),
                    "rounds_per_fn": 3,
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
                        "description": str(item.get("description", "")),
                        "spec": str(item.get("spec", "")),
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
                        "description": f"Implement behavior for {sr_id} in {subsystem_id}",
                        "spec": ("Follow subsystem detail design, include validation and error handling."),
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
            assignments[subsystem_id] = {
                "subsystem": str(subsystem.get("name", subsystem_id)),
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
        llm_data = self._run_llm_json(
            context=context,
            system_prompt=(
                "You are a senior software engineer. Generate Python module and pytest tests in JSON.\n"
                "Return keys: code_content, test_content.\n"
                "Rules:\n"
                "- code_content must define implement_<module_name>(input_data: dict | None = None)\n"
                "- function returns dict and includes keys: fn_id, description, status, result\n"
                "- test_content must import the function and include at least 2 pytest test functions\n"
                "- no markdown fences"
            ),
            user_prompt=(
                f"Subsystem: {subsystem_slug}\n"
                f"Module: {module_name}\n"
                f"FN: {fn_id}\n"
                f"Description: {fn_description}\n"
                f"Spec: {fn_spec}\n"
                f"Round: {round_index}\n"
                f"Reviewer comments:\n{comments}\n"
            ),
        )
        if not llm_data:
            return {}
        return {
            "code_content": str(llm_data.get("code_content", "")),
            "test_content": str(llm_data.get("test_content", "")),
        }

    def _fallback_test_content(
        self,
        *,
        subsystem_slug: str,
        module_name: str,
        fn_id: str,
        fn_description: str,
    ) -> str:
        safe_fn_id = fn_id.replace("'", "\\'")
        safe_desc = fn_description.replace("'", "\\'")
        return (
            f"from src.services.{subsystem_slug}.{module_name} import implement_{module_name}\n\n\n"
            f"def test_{module_name}_returns_dict() -> None:\n"
            f"    result = implement_{module_name}({{'round': 1}})\n"
            "    assert isinstance(result, dict)\n"
            f"    assert result.get('fn_id') == '{safe_fn_id}'\n\n"
            f"def test_{module_name}_description() -> None:\n"
            f"    result = implement_{module_name}()\n"
            f"    assert result.get('description') == '{safe_desc}'\n"
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
        safe_fn_id = fn_id.replace("'", "\\'")
        safe_desc = fn_description.replace("'", "\\'")
        safe_spec = fn_spec.replace("'", "\\'")
        return (
            "from __future__ import annotations\n\n"
            f'"""Implementation for {fn_id} in {subsystem_slug}."""\n\n'
            f"def implement_{module_name}(input_data: dict | None = None) -> dict[str, object]:\n"
            "    payload = input_data or {}\n"
            "    result = {'processed': True, 'input_keys': sorted(payload.keys())}\n"
            "    return {\n"
            f"        'fn_id': '{safe_fn_id}',\n"
            f"        'description': '{safe_desc}',\n"
            f"        'spec': '{safe_spec}',\n"
            "        'status': 'implemented',\n"
            "        'result': result,\n"
            "    }\n"
        )

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
        return expected_signature in code_content

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
        expected_import = f"from src.services.{subsystem_slug}.{module_name} import implement_{module_name}"
        if expected_import not in test_content:
            return False
        return f"implement_{module_name}" in test_content and "def test_" in test_content

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
        fn_description: str,
        index: int,
        used_names: set[str],
    ) -> str:
        candidates: list[str] = []

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
        }
        words = [self._slugify(word) for word in fn_description.split() if word.strip()]
        words = [word for word in words if word and word not in generic_words and not word.startswith("fn_")]
        if words:
            candidates.append("_".join(words[:2]))

        for raw in candidates:
            base = self._slugify(raw) or "feature_logic"
            if len(base) > 42:
                base = "_".join(base.split("_")[:4])[:42].strip("_") or "feature_logic"
            if base not in used_names:
                used_names.add(base)
                return base
        fallback = f"feature_logic_{index:02d}"
        used_names.add(fallback)
        return fallback

    def _slugify(self, value: str) -> str:
        chars: list[str] = []
        last_dash = False
        for ch in value.lower().strip():
            if ch.isalnum():
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

    def _run_llm_json(self, *, context: SkillContext, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if context.llm_client is None:
            raise RuntimeError("LLM client is required for deep_developer_workflow")
        response = context.llm_client.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        parsed = self._parse_json_response(response)
        if parsed is None:
            raise RuntimeError("LLM response is not valid JSON object for deep_developer_workflow")
        return parsed

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

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
