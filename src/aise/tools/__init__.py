"""Generic, role-agnostic tool primitives for orchestrator agents.

This package replaces the legacy ``aise.runtime.tool_primitives``
monolith. The same ``ToolContext``, ``WorkflowState`` and
``build_orchestrator_tools`` symbols are re-exported here so importers
get exactly the same surface.

Tool catalog
------------

Discovery (``discovery.py``):
- ``list_processes()`` — return process metadata
- ``get_process(process_file)`` — return a process definition
- ``list_agents()`` — return non-orchestrator agent cards

Dispatch (``dispatch.py``):
- ``dispatch_task(agent_name, task_description, ...)``
- ``dispatch_tasks_parallel(tasks_json)``
- ``dispatch_subsystems(phase, agent_name)``

Execution (``shell.py``):
- ``execute_shell(command, cwd, timeout)`` — sandboxed, allowlist gated

Workflow state (``completion.py``):
- ``mark_complete(report)`` — explicit terminal signal

Filesystem writes still use deepagents' built-in ``write_file``, which is
guarded by the agent's :class:`PolicyBackend` (see
``runtime/policy_backend.py``).
"""

from .builder import build_orchestrator_tools
from .context import ToolContext, WorkflowState

__all__ = [
    "ToolContext",
    "WorkflowState",
    "build_orchestrator_tools",
]
