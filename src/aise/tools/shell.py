"""Shell execution tool — allowlist-guarded ``execute_shell``."""

from __future__ import annotations

import json
import re
import subprocess

from langchain_core.tools import BaseTool, tool

from ..utils.logging import get_logger
from ._common import _now
from .context import ToolContext

logger = get_logger(__name__)


def make_shell_tool(ctx: ToolContext) -> BaseTool:
    """Create the ``execute_shell`` primitive (allowlist-guarded)."""
    shell_cfg = ctx.config.shell

    def _strip_cd_prefix(command: str) -> str:
        """Remove ``cd <path> &&`` or ``cd <path> ;`` prefix from a command.

        LLMs frequently prepend ``cd /absolute/path && actual_command``
        but execute_shell already sets cwd to the project root. The cd
        overrides that, pointing to the wrong directory. We strip it so
        the command runs in the correct project root.
        """
        return re.sub(r"^\s*cd\s+\S+\s*[;&]+\s*", "", command)

    @tool
    def execute_shell(command: str, cwd: str = "", timeout: int = 0) -> str:
        """Execute a shell command in the project root directory.

        The working directory is ALREADY set to the project root.
        Do NOT use ``cd`` to change directory — it is unnecessary and
        will be stripped. Just run the command directly, e.g.:
        ``python -m pytest tests/ -q --tb=short``

        Args:
            command: Shell command string (pipes and && are supported).
            cwd: Optional subdirectory relative to project root.
            timeout: Optional timeout in seconds.
        """
        command = _strip_cd_prefix(command)
        if not command.strip():
            return json.dumps({"status": "failed", "error": "empty command after stripping cd prefix"})

        if not shell_cfg.is_allowed(command):
            return json.dumps(
                {
                    "status": "refused",
                    "error": (f"Command not in allowlist. Allowed: {sorted(shell_cfg.allowlist)}"),
                }
            )

        effective_timeout = timeout if timeout > 0 else shell_cfg.timeout_seconds
        if ctx.project_root is None:
            return json.dumps({"status": "failed", "error": "no project root"})

        work_dir = ctx.project_root
        if cwd:
            candidate = (ctx.project_root / cwd).resolve()
            try:
                candidate.relative_to(ctx.project_root.resolve())
            except ValueError:
                return json.dumps({"status": "refused", "error": "cwd escapes project root"})
            work_dir = candidate

        try:
            # Use shell=True so that pipes (|), redirections (2>&1),
            # and chained commands (&&) work as LLMs expect.
            # Safety: the allowlist check already validated all
            # executables in the command string.
            proc = subprocess.run(  # noqa: S603 — allowlist enforced above
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "status": "failed",
                    "error": f"command timed out after {effective_timeout}s",
                }
            )
        except FileNotFoundError as exc:
            return json.dumps({"status": "failed", "error": f"command not found: {exc}"})

        stdout = (proc.stdout or "")[-3000:]
        stderr = (proc.stderr or "")[-3000:]
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "execute_shell",
                "summary": f"{command} → exit={proc.returncode}",
                "timestamp": _now(),
            }
        )
        return json.dumps(
            {
                "status": "completed",
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            ensure_ascii=False,
        )

    return execute_shell
