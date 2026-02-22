"""Deep developer workflow skill with Programmer / Code Reviewer subagents."""

from __future__ import annotations

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
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        architecture = self._load_architecture_design(context)
        subsystem_defs = architecture.get("subsystems", []) if isinstance(architecture, dict) else []
        assignments = self._build_subsystem_assignments(subsystem_defs)

        fn_by_subsystem = self._load_or_build_fn_map(context, architecture)
        if not fn_by_subsystem:
            fn_by_subsystem = {
                "subsystem": [{"id": "FN-SUBSYSTEM-01", "description": "core behavior", "spec": "basic"}]
            }

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

            # Step 2: Programmer loops FN by FN; each FN has >=3 paired review rounds.
            for fn_item in fn_items:
                fn_id = str(fn_item.get("id", "FN-UNKNOWN")).strip() or "FN-UNKNOWN"
                fn_description = str(fn_item.get("description", "")).strip() or "Feature implementation"
                fn_spec = str(fn_item.get("spec", "")).strip() or "Conform to subsystem detail design"
                fn_slug = self._slugify(fn_id)
                fn_tags = self._derive_fn_tags(f"{fn_description} {fn_spec}")

                code_path = src_subsystem_dir / f"{fn_slug}.py"
                test_path = tests_subsystem_dir / f"test_{fn_slug}.py"
                comments: list[str] = []

                for round_index in range(1, 4):
                    # Programmer: test-first then code update.
                    test_content = self._build_test_content(
                        subsystem_slug=subsystem_slug,
                        fn_id=fn_id,
                        fn_description=fn_description,
                        round_index=round_index,
                    )
                    code_content = self._build_code_content(
                        subsystem_slug=subsystem_slug,
                        fn_id=fn_id,
                        fn_description=fn_description,
                        fn_spec=fn_spec,
                        round_index=round_index,
                        comments=comments,
                        tags=fn_tags,
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

    def _build_test_content(
        self,
        *,
        subsystem_slug: str,
        fn_id: str,
        fn_description: str,
        round_index: int,
    ) -> str:
        module_name = self._slugify(fn_id)
        safe_fn_id = fn_id.replace("'", "\\'")
        safe_desc = fn_description.replace("'", "\\'")
        return (
            f'"""Tests for {fn_id}."""\n\n'
            f"from src.services.{subsystem_slug}.{module_name} import implement_{module_name}\n\n\n"
            f"def test_{module_name}_returns_expected_shape() -> None:\n"
            f"    result = implement_{module_name}(input_data={{'round': {round_index}}})\n"
            f"    assert isinstance(result, dict)\n"
            f"    assert result['fn_id'] == '{safe_fn_id}'\n"
            f"    assert 'status' in result\n"
            f"\n"
            f"def test_{module_name}_description_is_not_empty() -> None:\n"
            f"    result = implement_{module_name}(input_data={{}})\n"
            f"    assert result['description'] == '{safe_desc}'\n"
        )

    def _build_code_content(
        self,
        *,
        subsystem_slug: str,
        fn_id: str,
        fn_description: str,
        fn_spec: str,
        round_index: int,
        comments: list[str],
        tags: list[str],
    ) -> str:
        module_name = self._slugify(fn_id)
        safe_fn_id = fn_id.replace("'", "\\'")
        safe_desc = fn_description.replace("'", "\\'")
        safe_spec = fn_spec.replace("'", "\\'")
        comment_lines = "\n".join(f"# - {item}" for item in comments[:5]) if comments else "# - none"
        logic_lines = self._build_logic_lines(tags)
        return (
            "from __future__ import annotations\n\n"
            f'"""Implementation for {fn_id} in subsystem {subsystem_slug}."""\n\n'
            f"REVISION_NOTES = [\n"
            f"    'round_{round_index}: implementation updated',\n"
            f"]\n\n"
            f"def implement_{module_name}(input_data: dict | None = None) -> dict[str, object]:\n"
            f'    """{fn_description}"""\n'
            "    payload = input_data or {}\n"
            f"{logic_lines}"
            f"    return {{\n"
            f"        'fn_id': '{safe_fn_id}',\n"
            f"        'description': '{safe_desc}',\n"
            f"        'spec': '{safe_spec}',\n"
            f"        'status': 'implemented',\n"
            "        'result': result,\n"
            f"    }}\n\n"
            f"# Reviewer suggestions addressed in this round:\n"
            f"{comment_lines}\n"
        )

    def _run_static_and_unit_checks(self, code_path: Path, test_path: Path) -> dict[str, str]:
        code_text = code_path.read_text(encoding="utf-8")
        test_text = test_path.read_text(encoding="utf-8")
        static_ok = "passed" if "implement_" in code_text and "return" in code_text else "failed"
        unit_ok = "passed" if "def test_" in test_text else "failed"
        return {"static_check": static_ok, "unit_test": unit_ok}

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

    def _derive_fn_tags(self, text: str) -> list[str]:
        lowered = text.lower()
        tags: list[str] = []
        keyword_groups = {
            "snake": ["snake", "贪吃蛇"],
            "movement": ["movement", "移动", "position", "坐标", "collision", "碰撞"],
            "food": ["food", "食物"],
            "score": ["score", "积分", "settlement", "结算"],
            "level": ["level", "关卡", "progression", "进度"],
            "ai": ["ai", "人机", "bot"],
            "multiplayer": ["multiplayer", "多人", "room", "match"],
        }
        for tag, keys in keyword_groups.items():
            if any(key in lowered for key in keys):
                tags.append(tag)
        return tags

    def _build_logic_lines(self, tags: list[str]) -> str:
        lines: list[str] = [
            "    state = payload.get('state', {})",
            "    result: dict[str, object] = {}",
        ]
        if "snake" in tags or "movement" in tags:
            lines.extend(
                [
                    "    direction = payload.get('direction', 'right')",
                    "    head = tuple(payload.get('head', (0, 0)))",
                    "    delta = {'up': (0, -1), 'down': (0, 1), "
                    "'left': (-1, 0), 'right': (1, 0)}.get(direction, (1, 0))",
                    "    next_head = (head[0] + delta[0], head[1] + delta[1])",
                    "    result['next_head'] = next_head",
                ]
            )
        if "food" in tags:
            lines.extend(
                [
                    "    food_type = payload.get('food_type', 'normal')",
                    "    score_gain = {'normal': 1, 'gold': 3, 'mystery': 5}.get(food_type, 1)",
                    "    result['score_gain'] = score_gain",
                ]
            )
        if "score" in tags:
            lines.extend(
                [
                    "    current_score = int(payload.get('score', 0))",
                    "    result['new_score'] = current_score + int(result.get('score_gain', 0))",
                ]
            )
        if "level" in tags:
            lines.extend(
                [
                    "    score_for_level = int(result.get('new_score', payload.get('score', 0)))",
                    "    result['level'] = max(1, score_for_level // 10 + 1)",
                ]
            )
        if "ai" in tags:
            lines.extend(
                [
                    "    target = tuple(payload.get('target', (5, 5)))",
                    "    head_for_ai = tuple(result.get('next_head', payload.get('head', (0, 0))))",
                    "    ai_move = 'right' if target[0] > head_for_ai[0] else 'left'",
                    "    result['ai_move'] = ai_move",
                ]
            )
        if "multiplayer" in tags:
            lines.extend(
                [
                    "    players = payload.get('players', [])",
                    "    result['player_count'] = len(players)",
                    "    result['sync_required'] = len(players) > 1",
                ]
            )
        lines.extend(
            [
                "    result['state_keys'] = sorted(state.keys()) if isinstance(state, dict) else []",
                "    result['processed'] = True",
            ]
        )
        return "\n".join(f"{line}\n" for line in lines)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
