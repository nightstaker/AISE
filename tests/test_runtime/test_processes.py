from __future__ import annotations

from pathlib import Path

from aise.runtime.process import ProcessDefinition, ProcessRepository


def test_process_repository_scans_builtin_process_files() -> None:
    repo = ProcessRepository()
    processes = repo.list_processes()
    assert len(processes) >= 2
    ids = {p.process_id for p in processes}
    assert "runtime_design_standard" in ids


def test_process_repository_selects_matching_process_by_summary_keywords() -> None:
    repo = ProcessRepository()
    selection = repo.select_process("请帮我设计一个agent runtime架构和任务计划")
    assert selection is not None
    assert selection.process.process_id == "runtime_design_standard"
    assert selection.score > 0

    no_match = repo.select_process("weather lookup in city", min_score=99)
    assert no_match is None


def test_process_definition_requirement_override_precedence() -> None:
    repo = ProcessRepository()
    process = repo.get_process("runtime_design_standard")
    assert isinstance(process, ProcessDefinition)
    # process global says output_format: markdown, step overrides output_format: json_summary
    reqs = process.resolve_agent_requirements(
        agent_type="analysis_worker",
        step_id="req_analysis",
        agent_md_requirements=["output_format: text", "tone: strict"],
    )
    joined = "\n".join(reqs)
    assert "output_format: json_summary" in joined
    assert "output_format: markdown" not in joined
    assert "output_format: text" not in joined
    assert "tone: strict" in joined


def test_process_repository_parses_custom_process_markdown(tmp_path: Path) -> None:
    file_path = tmp_path / "custom.process.md"
    file_path.write_text(
        """# Custom Process
- process_id: custom_proc
- work_type: custom_work
- keywords: custom, workflow
- summary: custom summary

## Global Agent Requirements
### generic_worker
- output_format: markdown

## Steps
### step1: First Step
- agents: generic_worker, master_agent
- description: do something
#### Responsibilities
##### generic_worker
- execute custom task
#### Requirements
##### generic_worker
- output_format: json
""",
        encoding="utf-8",
    )
    repo = ProcessRepository(process_dir=tmp_path)
    p = repo.get_process("custom_proc")
    assert p is not None
    assert p.steps[0].participating_agents[0] == "generic_worker"
    assert "execute custom task" in p.steps[0].agent_responsibilities["generic_worker"][0]
    assert p.resolve_agent_requirements(agent_type="generic_worker", step_id="step1") == ["output_format: json"]
