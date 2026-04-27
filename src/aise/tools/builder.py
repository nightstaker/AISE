"""Aggregator factory — assembles every orchestrator tool group."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from .completion import make_completion_tool
from .context import ToolContext
from .discovery import make_discovery_tools
from .dispatch import make_dispatch_tools
from .shell import make_shell_tool


def build_orchestrator_tools(ctx: ToolContext) -> list[BaseTool]:
    """Build the full primitive tool set for an orchestrator session."""
    tools: list[BaseTool] = []
    tools.extend(make_discovery_tools(ctx))
    tools.extend(make_dispatch_tools(ctx))
    tools.append(make_shell_tool(ctx))
    tools.append(make_completion_tool(ctx))
    return tools
