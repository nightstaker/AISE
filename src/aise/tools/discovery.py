"""Discovery tools — list_processes / get_process / list_agents."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool

from ..utils.logging import get_logger
from ._common import _default_processes_dir, _now
from .context import ToolContext

logger = get_logger(__name__)


def make_discovery_tools(ctx: ToolContext) -> list[BaseTool]:
    """Create the discovery tool primitives (processes + agents)."""
    from ..runtime.process_md_parser import parse_process_md

    processes_dir = ctx.processes_dir or _default_processes_dir()
    orchestrator_role = ctx.config.orchestrator_role
    orchestrator_fallback_name = ctx.config.orchestrator_fallback_name

    @tool
    def list_processes() -> str:
        """List all available process definitions with metadata only."""
        if not processes_dir.is_dir():
            return json.dumps({"processes": []})
        items: list[dict[str, str]] = []
        for f in sorted(processes_dir.glob("*.process.md")):
            try:
                proc = parse_process_md(f)
            except Exception as exc:
                logger.warning("Failed to parse process %s: %s", f.name, exc)
                continue
            entry = proc.header_dict()
            entry["file"] = f.name
            items.append(entry)
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "list_processes",
                "summary": f"Found {len(items)} processes",
                "timestamp": _now(),
            }
        )
        return json.dumps({"processes": items}, ensure_ascii=False)

    @tool
    def get_process(process_file: str) -> str:
        """Read the full content of a specific process definition file.

        Args:
            process_file: Filename like 'waterfall.process.md'.
        """
        path = processes_dir / process_file
        if not path.is_file():
            return json.dumps({"error": f"Process file not found: {process_file}"})
        content = path.read_text(encoding="utf-8")
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "get_process",
                "summary": f"Read {process_file}",
                "timestamp": _now(),
            }
        )
        return content

    @tool
    def list_agents() -> str:
        """List all non-orchestrator agents with their cards."""
        agents: list[dict[str, Any]] = []
        for name, rt in ctx.manager.runtimes.items():
            defn = rt.definition
            role = (getattr(defn, "role", "") or "").lower()
            if role == orchestrator_role:
                continue
            # Always exclude the configured orchestrator fallback name,
            # regardless of how its role is tagged. This keeps legacy
            # project_manager.md (no explicit role) excluded.
            if name == orchestrator_fallback_name:
                continue
            agents.append(rt.get_agent_card_dict())
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "list_agents",
                "summary": f"Found {len(agents)} agents",
                "timestamp": _now(),
            }
        )
        return json.dumps({"agents": agents}, ensure_ascii=False)

    return [list_processes, get_process, list_agents]
