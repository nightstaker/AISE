"""ProjectSession — the bridge that makes project_manager actually work.

Provides LangChain tools that the project_manager's deepagent can call
to read process definitions, discover other agents, and dispatch tasks.

Usage::

    manager = RuntimeManager(config=config)
    manager.start()

    session = ProjectSession(manager)
    result = session.run("Build a REST API for user management")
    print(result)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from ..utils.logging import get_logger

logger = get_logger(__name__)


def _make_safe_backend(project_root: str | Path) -> Any:
    """Create a FilesystemBackend that strips absolute path prefixes.

    Deepagent agents sometimes try to write to absolute paths like
    /home/user/workspace/... which virtual_mode=True maps to
    home/user/workspace/... under root. This wrapper intercepts
    write calls and strips common absolute path prefixes to keep
    all files directly under src/, tests/, docs/.
    """
    from deepagents.backends import FilesystemBackend

    root = str(project_root)
    base = FilesystemBackend(root_dir=root, virtual_mode=True)

    # Patch the write method to normalize paths
    original_awrite = base.awrite

    async def safe_awrite(path: str, content: str) -> str:
        path = _normalize_path(path)
        return await original_awrite(path, content)

    base.awrite = safe_awrite

    original_write = base.write

    def safe_write(path: str, content: str) -> str:
        path = _normalize_path(path)
        return original_write(path, content)

    base.write = safe_write

    return base


_PYTEST_RUNNER_PATTERNS = (
    "run_pytest", "pytest_runner", "pytest_run", "execute_pytest",
    "run_tests", "test_runner", "pytest_capture", "pytest_script",
    "pytest_exec", "test_run", "final_pytest", "py_test",
)


def _is_pytest_runner_junk(filename: str) -> bool:
    """Detect filenames that are LLM-generated pytest runner junk."""
    lower = filename.lower()
    if not lower.endswith((".py", ".sh", ".txt")):
        return False
    return any(p in lower for p in _PYTEST_RUNNER_PATTERNS) or lower in (
        "test_output.txt", "pytest_output.txt", "output_pytest.txt",
    )


def _normalize_path(path: str) -> str:
    """Strip absolute path prefixes and collapse to relative project paths.

    Routing rules (in order):
    0. runs/* → preserved as-is
    1. pytest runner junk (run_pytest.py etc.) → runs/scratch/
    2. .py/.sh files inside docs/ → runs/scratch/
    3. Files containing /docs/ or /design/ → docs/
    4. Files containing /aise/agents/ or /aise/runtime/ → runs/scratch/ (AISE internal)
    5. Files containing /tests/ → tests/ (rightmost wins)
    6. Files containing /src/ → src/ (rightmost wins)
    7. Files containing /runs/ → runs/
    8. Loose test_*.py files → tests/
    9. Everything else → runs/scratch/
    """
    # Strip leading /
    p = path.lstrip("/")
    parts = p.split("/")
    filename = parts[-1] or "unknown"

    # Rule 0: runs/ takes priority
    if p.startswith("runs/"):
        return p

    # Rule 1: known pytest runner junk → runs/scratch/
    if _is_pytest_runner_junk(filename):
        return f"runs/scratch/{filename}"

    # Rule 2: .py or .sh inside any docs/ → runs/scratch/
    # (docs/ is for markdown design docs only)
    if filename.endswith((".py", ".sh")) and "docs/" in p:
        return f"runs/scratch/{filename}"

    # Rule 3: design/ or docs/ in path → docs/
    for marker in ("/docs/", "/design/"):
        idx = p.rfind(marker)
        if idx >= 0:
            sub = p[idx + len(marker):]
            return f"docs/{sub}"
    if p.startswith(("docs/", "design/")):
        sub = p.split("/", 1)[1] if "/" in p else ""
        return f"docs/{sub}" if sub else "docs/"

    # Rule 4: AISE internal paths (src/aise/...) → runs/scratch/
    # Agents shouldn't be writing into the AISE codebase itself.
    if "/aise/agents/" in p or "/aise/runtime/" in p or p.startswith("aise/"):
        return f"runs/scratch/{filename}"

    # Rule 5: tests/ in path → tests/ (rightmost)
    test_idx = p.rfind("tests/")
    if test_idx >= 0:
        return p[test_idx:]

    # Rule 6: src/ in path → src/ (rightmost)
    src_idx = p.rfind("src/")
    if src_idx >= 0:
        sub = p[src_idx:]
        # Strip src/aise/ prefix if present (keep src/<rest>)
        if sub.startswith("src/aise/"):
            return f"runs/scratch/{filename}"
        return sub

    # Rule 7: runs/ in path → runs/
    runs_idx = p.rfind("runs/")
    if runs_idx >= 0:
        return p[runs_idx:]

    # Rule 8: filename starts with test_ → tests/
    if filename.startswith("test_") and filename.endswith(".py"):
        return f"tests/{filename}"

    # Everything else goes to runs/scratch/
    return f"runs/scratch/{filename}"


def _processes_dir() -> Path:
    """Return the path to ``src/aise/processes/``."""
    return Path(__file__).resolve().parent.parent / "processes"


class ProjectSession:
    """Drives a project from raw requirements to delivery.

    Creates orchestration tools, rebuilds the project_manager runtime
    with those tools injected, and provides a ``run()`` entry point.

    An optional ``on_event`` callback is invoked on every A2A message
    (task_request, task_response, stage_update) so external systems
    (e.g. the WebUI) can display live progress.
    """

    def __init__(
        self,
        manager: Any,
        *,
        project_root: str | Path | None = None,
        on_event: Any | None = None,
    ) -> None:
        """Initialize a project session.

        Args:
            manager: A started :class:`RuntimeManager` instance.
            project_root: Directory where project artifacts are written.
            on_event: Optional callback ``(event: dict) -> None`` invoked
                on every A2A message and stage transition.
        """
        from .manager import RuntimeManager

        self._manager: RuntimeManager = manager
        self._session_id = uuid.uuid4().hex[:12]
        self._task_log: list[dict[str, Any]] = []
        self._on_event = on_event
        self._current_stage: str = ""
        self._project_root: Path | None = Path(project_root) if project_root else None
        if self._project_root:
            for subdir in ("docs", "src", "tests", "runs/trace", "runs/docs", "runs/plans"):
                (self._project_root / subdir).mkdir(parents=True, exist_ok=True)
        self._pm_runtime = self._build_pm_runtime()

    # -- Public API ----------------------------------------------------------

    # The 5 stages the project_manager must complete
    _REQUIRED_STAGES = [
        "process_selection",
        "team_assembly",
    ]
    # dispatch_task stages are dynamic (from process phases), so we check
    # that at least one task_response exists after the planning stages.
    _MAX_CONTINUATIONS = 10

    def run(self, requirement: str) -> str:
        """Submit a raw requirement and let project_manager orchestrate.

        Includes a continuation loop: if the LLM stops before completing
        the full workflow (empty response, no task dispatches yet, etc.),
        it is prompted to continue.

        Args:
            requirement: The raw project requirement text.

        Returns:
            The project_manager's final response (delivery summary).
        """
        if self._pm_runtime is None:
            raise RuntimeError("project_manager runtime not available")

        logger.info("ProjectSession started: session=%s requirement_len=%d",
                     self._session_id, len(requirement))

        prompt = (
            f"New project requirement:\n\n{requirement}\n\n"
            "Execute the full workflow: "
            "1) select a process, "
            "2) assemble a team, "
            "3) plan the workflow, "
            "4) dispatch tasks to agents and coordinate, "
            "5) produce the final delivery report."
        )

        response = self._pm_runtime.handle_message(
            prompt, thread_id=self._session_id,
        )

        # Continuation loop: check if the workflow actually finished
        for attempt in range(self._MAX_CONTINUATIONS):
            if self._is_workflow_complete(response):
                break

            missing = self._describe_missing_work()
            logger.info(
                "ProjectSession continuation %d: session=%s reason=%s",
                attempt + 1, self._session_id, missing,
            )

            continuation_prompt = (
                f"The workflow is not yet complete. {missing}\n\n"
                "Continue executing the remaining steps. "
                "Use dispatch_task to send work to agents and "
                "write_project_file to save outputs.\n\n"
                "IMPORTANT: After all tasks are done, you MUST respond with a "
                "text delivery report summarizing what was completed. "
                "Do not end your turn with only a tool call — always follow up "
                "with a text response."
            )

            response = self._pm_runtime.handle_message(
                continuation_prompt, thread_id=self._session_id,
            )

        logger.info("ProjectSession completed: session=%s", self._session_id)
        return response

    _MAX_TOTAL_DISPATCHES = 12  # Safety cap on total task dispatches

    def _is_workflow_complete(self, response: str) -> bool:
        """Check if the workflow has meaningfully completed."""
        dispatched = [e for e in self._task_log if e.get("type") == "task_request"]
        completed = [e for e in self._task_log if e.get("type") == "task_response" and e.get("status") == "completed"]

        # Safety cap: if we've dispatched too many tasks, force completion
        if len(dispatched) >= self._MAX_TOTAL_DISPATCHES:
            logger.warning("Max dispatches reached (%d), forcing completion", len(dispatched))
            return True

        # Empty response always means incomplete
        if not response or not response.strip():
            return False

        # No tasks dispatched at all — incomplete
        if not dispatched:
            return False

        # No completed tasks — incomplete
        if not completed:
            return False

        # Response looks like a final report
        lower = response.lower()
        has_completion_signal = any(kw in lower for kw in [
            "delivery report", "completed", "final report", "summary",
            "交付", "完成", "总结", "报告", "cycle_complete",
        ])
        if has_completion_signal and len(response.strip()) > 100:
            return True

        # If response is long but no completion signal, it might be mid-stream
        return False

    def _describe_missing_work(self) -> str:
        """Describe what's missing based on task_log analysis."""
        stages_seen = {e["stage"] for e in self._task_log if e.get("type") == "stage_update"}
        dispatched = [e for e in self._task_log if e.get("type") == "task_request"]
        completed = [e for e in self._task_log if e.get("type") == "task_response" and e.get("status") == "completed"]

        parts = []
        if "process_selection" not in stages_seen:
            parts.append("Process has not been selected yet.")
        if "team_assembly" not in stages_seen:
            parts.append("Team has not been assembled yet.")
        if not dispatched:
            parts.append("No tasks have been dispatched to any agent.")
        else:
            parts.append(f"{len(dispatched)} tasks dispatched, {len(completed)} completed so far.")
            # Check which agents were used
            agents_used = {e.get("to") for e in dispatched}
            parts.append(f"Agents involved: {', '.join(sorted(agents_used))}.")
        return " ".join(parts)

    @property
    def task_log(self) -> list[dict[str, Any]]:
        """Chronological log of all A2A messages dispatched/received."""
        return list(self._task_log)

    @property
    def current_stage(self) -> str:
        return self._current_stage

    def _emit(self, event: dict[str, Any]) -> None:
        """Record event and notify callback."""
        self._task_log.append(event)
        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass

    _NOISE_MARKERS = (
        "Error: File",
        "Updated todo list",
        "not found",
        "todos.json",
    )

    def _save_task_output(self, agent: str, step_id: str, phase: str, content: str) -> None:
        """Auto-save a task output to the project runs/ directory.

        All auto-saved agent outputs go to runs/docs/ (intermediate artifacts).
        Only the final delivery report and agent-written files (via write_file)
        end up in the top-level docs/, src/, tests/.
        """
        if not self._project_root or not content.strip():
            return
        # Skip tool noise
        first_line = content.strip().split("\n")[0]
        if any(marker in first_line for marker in self._NOISE_MARKERS):
            logger.debug("Skipping tool noise output: %s", first_line[:80])
            return
        if len(content.strip()) < 20:
            return

        # All auto-saved outputs go to runs/docs/ (intermediate)
        subdir = "runs/docs"

        # Build filename
        parts = [p for p in [phase, agent, step_id] if p]
        base = "_".join(parts) if parts else f"{agent}_output"
        target = self._project_root / subdir / f"{base}.md"
        counter = 2
        while target.exists():
            target = self._project_root / subdir / f"{base}_{counter}.md"
            counter += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info("Task output saved: %s (%d bytes)", target.relative_to(self._project_root), len(content))

    # -- Tool factories ------------------------------------------------------

    def _make_tools(self) -> list[Any]:
        """Create LangChain tools for the project_manager agent."""
        session = self  # capture for closures

        def _enter_stage(stage: str) -> None:
            """Emit a stage_update if entering a new stage."""
            if session._current_stage != stage:
                session._current_stage = stage
                session._emit({
                    "type": "stage_update", "stage": stage,
                    "status": "started", "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        @tool
        def list_processes() -> str:
            """List all available process definitions with their id, name, work_type, and keywords."""
            _enter_stage("process_selection")
            procs_dir = _processes_dir()
            if not procs_dir.is_dir():
                return json.dumps({"processes": []})

            processes = []
            for f in sorted(procs_dir.glob("*.process.md")):
                text = f.read_text(encoding="utf-8")
                info = _parse_process_header(text)
                info["file"] = f.name
                processes.append(info)

            session._emit({
                "type": "tool_call", "tool": "list_processes",
                "summary": f"Found {len(processes)} processes: {', '.join(p.get('process_id','') for p in processes)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return json.dumps({"processes": processes}, ensure_ascii=False)

        @tool
        def get_process(process_file: str) -> str:
            """Read the full content of a specific process definition file.

            Args:
                process_file: Filename like 'waterfall.process.md'.
            """
            _enter_stage("process_selection")
            path = _processes_dir() / process_file
            if not path.is_file():
                return json.dumps({"error": f"Process file not found: {process_file}"})
            content = path.read_text(encoding="utf-8")
            session._emit({
                "type": "tool_call", "tool": "get_process",
                "summary": f"Read {process_file} ({len(content)} chars)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return content

        @tool
        def list_agents() -> str:
            """List all available agent cards with their name, description, skills, and capabilities."""
            _enter_stage("team_assembly")
            agents = []
            for name, rt in session._manager.runtimes.items():
                if name == "project_manager":
                    continue  # exclude self
                agents.append(rt.get_agent_card_dict())
            session._emit({
                "type": "tool_call", "tool": "list_agents",
                "summary": f"Found {len(agents)} agents: {', '.join(a.get('name','') for a in agents)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return json.dumps({"agents": agents}, ensure_ascii=False)

        @tool
        def dispatch_task(agent_name: str, task_description: str, step_id: str = "", phase: str = "") -> str:
            """Send a task to another agent and return its response.

            This follows the A2A task_request/task_response protocol.

            Args:
                agent_name: Name of the target agent (e.g. 'developer', 'architect').
                task_description: Detailed description of what the agent should do.
                step_id: The workflow step identifier.
                phase: The workflow phase name.
            """
            # Hard cap: refuse new dispatches once total exceeds MAX_TOTAL_DISPATCHES
            current_dispatches = sum(1 for e in session._task_log if e.get("type") == "task_request")
            if current_dispatches >= session._MAX_TOTAL_DISPATCHES:
                logger.warning("dispatch_task refused: cap reached (%d)", current_dispatches)
                return json.dumps({
                    "status": "failed",
                    "error": (
                        f"Maximum dispatches ({session._MAX_TOTAL_DISPATCHES}) reached. "
                        "Workflow must finish now. Stop calling tools and produce the "
                        "final delivery report as text."
                    ),
                })

            # Use phase as stage name so each workflow phase shows separately
            _enter_stage(phase or "execution")
            rt = session._manager.get_runtime(agent_name)
            if rt is None:
                return json.dumps({
                    "status": "failed",
                    "error": f"Agent '{agent_name}' not found",
                })

            task_id = uuid.uuid4().hex[:10]
            request_msg = {
                "taskId": task_id,
                "from": "project_manager",
                "to": agent_name,
                "type": "task_request",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "step": step_id,
                    "phase": phase,
                    "task": task_description,
                },
            }
            session._emit(request_msg)
            logger.info("Task dispatched: task=%s to=%s step=%s", task_id, agent_name, step_id)

            try:
                # Build a project-scoped runtime so write_file goes to disk
                dispatch_rt = session._get_project_runtime(agent_name, rt)

                # Phase-specific file rules
                if phase and any(kw in phase.lower() for kw in ("implement", "develop", "coding", "execution")):
                    file_rules = (
                        "Write source code to src/ (e.g. src/main.py, src/game/engine.py). "
                        "Write tests to tests/ (e.g. tests/test_main.py). "
                        "You MUST create a src/main.py entry point file. "
                        "Do NOT write code to docs/."
                    )
                elif phase and any(kw in phase.lower() for kw in ("test", "verif", "qa")):
                    file_rules = (
                        "Write test code to tests/ (e.g. tests/test_main.py, tests/test_core.py). "
                        "Each test file must be a complete runnable pytest module."
                    )
                elif phase and any(kw in phase.lower() for kw in ("design", "architect")):
                    file_rules = (
                        "Write design documents to docs/. "
                        "Include only interface definitions, schemas, and pseudocode — NOT full implementation code. "
                        "Keep code snippets under 10 lines."
                    )
                else:
                    file_rules = (
                        "Write documents to docs/. Write source code to src/. Write tests to tests/."
                    )

                full_prompt = (
                    f"{task_description}\n\n"
                    f"FILE OUTPUT RULES: Use write_file to save all output. {file_rules}\n"
                    "CRITICAL: All paths MUST be relative (e.g. src/main.py, tests/test_core.py). "
                    "NEVER use absolute paths starting with /. "
                    "After writing files, respond with a brief summary of what you produced."
                )

                result = dispatch_rt.handle_message(full_prompt)

                # Retry once if response is empty or trivial
                if not result.strip() or len(result.strip()) < 30:
                    logger.warning("Trivial response from %s (%d chars), retrying", agent_name, len(result))
                    retry_prompt = (
                        f"Your previous response was empty or too brief. "
                        f"Please complete the following task and provide the FULL output:\n\n"
                        f"{task_description}\n\n"
                        "Use write_file to save all code/document files, then summarize what you created."
                    )
                    result = dispatch_rt.handle_message(retry_prompt)

                # Auto-save full output to project directory
                session._save_task_output(agent_name, step_id, phase, result)

                # Truncate output for the tool return (PM doesn't need the full text;
                # it's auto-saved to disk). This prevents the PM from trying to
                # copy-paste huge content into write_project_file calls.
                output_len = len(result)
                preview = result[:500] + "..." if output_len > 500 else result
                response_msg = {
                    "taskId": task_id,
                    "from": agent_name,
                    "to": "project_manager",
                    "type": "task_response",
                    "status": "completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "output_preview": preview,
                        "output_length": output_len,
                        "saved_to": "auto-saved to project directory",
                    },
                }
                session._emit(response_msg)

                logger.info("Task completed: task=%s from=%s output=%d chars", task_id, agent_name, output_len)
                return json.dumps(response_msg, ensure_ascii=False)

            except Exception as exc:
                error_msg = {
                    "taskId": task_id,
                    "from": agent_name,
                    "to": "project_manager",
                    "type": "task_response",
                    "status": "failed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {"error": str(exc)},
                }
                session._emit(error_msg)
                logger.warning("Task failed: task=%s from=%s error=%s", task_id, agent_name, exc)
                return json.dumps(error_msg, ensure_ascii=False)

        @tool
        def write_project_file(file_path: str, content: str) -> str:
            """Write a file to the project directory.

            Use this to save plans, reports, and summaries you produce yourself.
            Agent outputs (from dispatch_task) are auto-saved — do NOT duplicate them.

            Path routing:
            - Plans/execution plans → runs/plans/ (auto-routed)
            - Your own reports → docs/ (e.g. docs/delivery_report.md)
            - Everything else → as specified

            Args:
                file_path: Relative path within the project (e.g. 'docs/delivery_report.md').
                content: File content to write.
            """
            if not session._project_root:
                return json.dumps({"status": "skipped", "reason": "no project directory configured"})

            # Route plan files to runs/plans/
            normalized = file_path.lower()
            if any(kw in normalized for kw in ("plan", "execution_plan", "team_roster")):
                file_path = "runs/plans/" + Path(file_path).name

            target = (session._project_root / file_path).resolve()
            if not str(target).startswith(str(session._project_root.resolve())):
                return json.dumps({"status": "failed", "error": "path escapes project directory"})
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            logger.info("Project file written: %s (%d bytes)", file_path, len(content))
            return json.dumps({"status": "saved", "path": file_path, "bytes": len(content)})

        @tool
        def dispatch_tasks_parallel(tasks_json: str) -> str:
            """Dispatch multiple tasks to different agents in parallel.

            Use this to run independent tasks concurrently, e.g. developer
            writing code while qa_engineer writes tests at the same time.

            Args:
                tasks_json: JSON array of task objects, each with:
                    - agent_name: target agent
                    - task_description: what to do
                    - step_id: workflow step id
                    - phase: workflow phase name
            """
            import concurrent.futures

            try:
                tasks = json.loads(tasks_json)
            except Exception:
                return json.dumps({"status": "failed", "error": "Invalid JSON"})

            if not isinstance(tasks, list) or not tasks:
                return json.dumps({"status": "failed", "error": "tasks must be a non-empty array"})

            results = []

            def run_one(t: dict) -> dict:
                agent = t.get("agent_name", "")
                desc = t.get("task_description", "")
                step = t.get("step_id", "")
                ph = t.get("phase", "")
                raw = dispatch_task.invoke({
                    "agent_name": agent,
                    "task_description": desc,
                    "step_id": step,
                    "phase": ph,
                })
                return json.loads(raw)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = {pool.submit(run_one, t): t for t in tasks}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        t = futures[future]
                        results.append({"status": "failed", "from": t.get("agent_name"), "error": str(exc)})

            ok = sum(1 for r in results if r.get("status") == "completed")
            fail = sum(1 for r in results if r.get("status") == "failed")
            return json.dumps({
                "parallel_results": results,
                "total": len(results),
                "completed": ok,
                "failed": fail,
            }, ensure_ascii=False)

        @tool
        def run_tdd_cycle(
            feature_description: str,
            phase: str = "implementation",
            max_iterations: int = 3,
        ) -> str:
            """Run TDD (Test-Driven Development) cycle by the developer agent.

            The developer follows the TDD methodology:
            1. Write unit tests FIRST in tests/ (RED)
            2. Write code in src/ to make tests pass (GREEN)
            3. System runs pytest
            4. If failures, developer fixes with real pytest output
            5. Repeat until tests pass or max_iterations reached

            Only the developer agent is used. QA integration testing happens
            SEPARATELY in the next phase via dispatch_task to qa_engineer.

            Args:
                feature_description: What feature/module to build.
                phase: Workflow phase name.
                max_iterations: Maximum fix-test iterations (default 3).
            """
            import subprocess

            # Single-use lock: run_tdd_cycle can only be called ONCE per session
            if getattr(session, "_tdd_cycle_called", False):
                return json.dumps({
                    "status": "failed",
                    "error": (
                        "run_tdd_cycle has already been called for this project. "
                        "Implementation phase is DONE. Move to the next phase "
                        "(QA integration testing) using dispatch_task to qa_engineer."
                    ),
                    "do_not_retry": True,
                })
            session._tdd_cycle_called = True

            _enter_stage(phase)
            iteration_results = []
            last_test_output = ""

            def actually_run_pytest() -> tuple[bool, str]:
                """Run pytest in the project directory and return (passed, output)."""
                if not session._project_root:
                    return False, "No project root configured"
                tests_dir = session._project_root / "tests"
                if not tests_dir.is_dir() or not any(tests_dir.iterdir()):
                    return False, "No tests directory or empty"
                try:
                    result = subprocess.run(
                        ["python", "-m", "pytest", str(tests_dir), "-q", "--tb=short", "--no-header"],
                        cwd=str(session._project_root),
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    output = (result.stdout + "\n" + result.stderr).strip()
                    output = output[-3000:]
                    passed = result.returncode == 0
                    return passed, output
                except subprocess.TimeoutExpired:
                    return False, "pytest timed out after 120s"
                except Exception as exc:
                    return False, f"pytest execution error: {exc}"

            for iteration in range(1, max_iterations + 1):
                session._emit({
                    "type": "stage_update",
                    "stage": f"{phase}_tdd_{iteration}",
                    "status": "started",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                if iteration == 1:
                    # TDD step 1+2: developer writes tests AND code
                    tdd_desc = (
                        f"Use Test-Driven Development (TDD) to build the following:\n\n"
                        f"{feature_description}\n\n"
                        f"TDD STEPS (you MUST follow this order):\n"
                        f"1. FIRST write unit tests to tests/ (e.g. tests/test_main.py). "
                        f"Tests should cover the public API and edge cases.\n"
                        f"2. THEN write the implementation code to src/ (e.g. src/main.py). "
                        f"You MUST create src/main.py as the entry point.\n"
                        f"3. Use write_file for ALL outputs. Use relative paths only.\n\n"
                        f"Do NOT skip tests. Do NOT write tests after code."
                    )
                    dispatch_task.invoke({
                        "agent_name": "developer",
                        "task_description": tdd_desc,
                        "step_id": "tdd_initial",
                        "phase": phase,
                    })
                else:
                    # Fix iteration: real pytest output guides the fix
                    fix_desc = (
                        f"TDD Iteration {iteration}: Fix the failing tests.\n\n"
                        f"REAL pytest output:\n```\n{last_test_output}\n```\n\n"
                        f"Steps:\n"
                        f"1. Read ONLY the specific failing test files and the code they test\n"
                        f"2. Identify the bug from the failure message\n"
                        f"3. Use write_file to save the corrected code\n"
                        f"Be efficient — do NOT read every file in the project."
                    )
                    dispatch_task.invoke({
                        "agent_name": "developer",
                        "task_description": fix_desc,
                        "step_id": f"tdd_fix_{iteration}",
                        "phase": phase,
                    })

                # System runs pytest (no LLM)
                all_pass, last_test_output = actually_run_pytest()
                session._emit({
                    "type": "tool_call", "tool": "pytest",
                    "summary": f"TDD iter {iteration}: {'PASSED' if all_pass else 'FAILED'}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                iteration_results.append({
                    "iteration": iteration,
                    "all_tests_pass": all_pass,
                    "pytest_output": last_test_output[:500],
                })

                if all_pass:
                    logger.info("TDD cycle passed at iteration %d", iteration)
                    break

                logger.info("TDD cycle iteration %d: tests still failing", iteration)

            final_pass = iteration_results[-1]["all_tests_pass"] if iteration_results else False
            status_msg = (
                "TDD cycle complete: all unit tests pass. Proceed to QA integration testing phase."
                if final_pass
                else f"TDD cycle complete: max iterations ({max_iterations}) reached. "
                     f"Implementation done. Proceed to next phase. Do NOT call run_tdd_cycle again."
            )
            return json.dumps({
                "cycle_complete": True,
                "all_tests_pass": final_pass,
                "iterations": iteration_results,
                "total_iterations": len(iteration_results),
                "status": status_msg,
                "do_not_retry": True,
            }, ensure_ascii=False)

        return [list_processes, get_process, list_agents, dispatch_task,
                dispatch_tasks_parallel, run_tdd_cycle, write_project_file]

    # -- Internal ------------------------------------------------------------

    _project_runtimes: dict[str, Any] = {}

    def _get_project_runtime(self, agent_name: str, global_rt: Any) -> Any:
        """Get or create a project-scoped AgentRuntime with FilesystemBackend.

        This allows agents to use write_file/edit_file to write directly
        to the project directory on disk.
        """
        if not self._project_root:
            return global_rt  # No project dir, use global runtime

        cache_key = f"{self._session_id}__{agent_name}"
        if cache_key in self._project_runtimes:
            return self._project_runtimes[cache_key]

        from .agent_runtime import AgentRuntime
        from .manager import _agents_dir, _build_llm

        try:
            md_path = _agents_dir() / f"{agent_name}.md"
            if not md_path.is_file():
                logger.warning("No agent.md for %s, using global runtime", agent_name)
                return global_rt

            model_info = global_rt.definition.metadata.get("_model_info", {})
            from ..config import ModelConfig
            model_cfg = ModelConfig(
                provider=model_info.get("provider", ""),
                model=model_info.get("model", ""),
                temperature=model_info.get("temperature", 0.7),
                max_tokens=model_info.get("maxTokens", 4096),
            )
            if hasattr(self._manager, "_config"):
                gc = self._manager._config.get_model_config(agent_name)
                model_cfg.api_key = gc.api_key
                model_cfg.base_url = gc.base_url
                model_cfg.extra = gc.extra

            llm = _build_llm(model_cfg)
            backend = _make_safe_backend(self._project_root)

            skills_dir = md_path.parent / "_runtime_skills"
            skills_dir.mkdir(exist_ok=True)

            trace_dir = str(self._project_root / "runs/trace")

            rt = AgentRuntime(
                agent_md=md_path,
                skills_dir=skills_dir,
                model=llm,
                backend=backend,
                trace_dir=trace_dir,
            )
            rt.evoke()
            self._project_runtimes[cache_key] = rt
            logger.info("Project-scoped runtime created: agent=%s root=%s", agent_name, self._project_root)
            return rt

        except Exception as exc:
            logger.warning("Failed to create project-scoped runtime for %s: %s, using global", agent_name, exc)
            return global_rt

    def _build_pm_runtime(self) -> Any:
        """Rebuild project_manager runtime with orchestration tools injected."""
        from .agent_runtime import AgentRuntime
        from .manager import _agents_dir, _build_llm

        pm_md = _agents_dir() / "project_manager.md"
        if not pm_md.is_file():
            logger.error("project_manager.md not found at %s", pm_md)
            return None

        existing_rt = self._manager.get_runtime("project_manager")
        if existing_rt is None:
            logger.error("project_manager not found in RuntimeManager")
            return None

        # Get model config from the existing runtime's metadata
        model_info = existing_rt.definition.metadata.get("_model_info", {})

        from ..config import ModelConfig
        model_cfg = ModelConfig(
            provider=model_info.get("provider", ""),
            model=model_info.get("model", ""),
            temperature=model_info.get("temperature", 0.7),
            max_tokens=model_info.get("maxTokens", 4096),
        )
        # Inherit api_key and base_url from the global config if available
        if hasattr(self._manager, "_config"):
            global_cfg = self._manager._config.get_model_config("project_manager")
            model_cfg.api_key = global_cfg.api_key
            model_cfg.base_url = global_cfg.base_url
            model_cfg.extra = global_cfg.extra

        llm = _build_llm(model_cfg)
        tools = self._make_tools()

        skills_dir = pm_md.parent / "_runtime_skills"
        skills_dir.mkdir(exist_ok=True)

        from langgraph.checkpoint.memory import MemorySaver

        trace_dir = str(self._project_root / "runs/trace") if self._project_root else None

        # Use FilesystemBackend so PM's write_file stays inside project dir
        pm_backend = None
        if self._project_root:
            try:
                pm_backend = _make_safe_backend(self._project_root)
            except Exception:
                pass

        rt = AgentRuntime(
            agent_md=pm_md,
            skills_dir=skills_dir,
            model=llm,
            extra_tools=tools,
            backend=pm_backend,
            trace_dir=trace_dir,
            checkpointer=MemorySaver(),
        )
        rt.evoke()
        logger.info(
            "ProjectSession PM runtime built: tools=%d trace_dir=%s session=%s",
            len(tools), trace_dir, self._session_id,
        )
        return rt


def _parse_process_header(text: str) -> dict[str, str]:
    """Extract process metadata from the header of a process.md file."""
    info: dict[str, str] = {}
    for line in text.split("\n")[:10]:
        line = line.strip()
        if line.startswith("- process_id:"):
            info["process_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("- name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("- work_type:"):
            info["work_type"] = line.split(":", 1)[1].strip()
        elif line.startswith("- keywords:"):
            info["keywords"] = line.split(":", 1)[1].strip()
        elif line.startswith("- summary:"):
            info["summary"] = line.split(":", 1)[1].strip()
    return info
