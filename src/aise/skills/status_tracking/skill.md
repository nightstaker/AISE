# Skill Spec: status_tracking

## 1. Metadata
- `skill_id`: `status_tracking`
- `module`: `aise.skills.status_tracking.scripts.status_tracking`
- `class`: `StatusTrackingSkill`
- `implementation`: `src/aise/skills/status_tracking/scripts/status_tracking.py`
- `license`: `Apache-2.0` (see `LICENSE.txt`)

## 2. Purpose
Generate complete SF-SR-AR-FN traceability and status information

## 3. Inputs
- `input_data`: `dict[str, Any]`
- Required fields from `validate_input`: 无强制字段
- `context`: `SkillContext` (artifact store, project_name, parameters, model_config, llm_client)

## 4. Dependencies
- Required artifact types: `[]`
- External dependencies: 见实现文件中的 import 与 `context.parameters` 使用

## 5. Outputs
- Output artifact type: `ArtifactType.STATUS_TRACKING`
- Producer: `architect`
- Storage: 由 Agent 框架在执行后写入 `ArtifactStore`

## 6. Execution Contract
1. Validate input via `validate_input(input_data)`.
2. Read required artifacts from `context.artifact_store` as needed.
3. Execute deterministic logic and/or LLM-assisted logic.
4. Return an `Artifact` object with complete `content` and `metadata`.

## 7. Error Handling
- Input validation errors must return clear missing-field messages.
- Runtime exceptions should preserve actionable context (project, ids, cause).

## 8. Notes
- This file is normalized to a shared template across all skills.
- Skill-specific deep rules should be maintained in code/comments or dedicated `references/` files when needed.
