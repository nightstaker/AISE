"""Create a deepagents FilesystemBackend with path normalization + write-overwrite.

Two patches over the native ``FilesystemBackend``:

1. **Path normalization** — LLMs frequently produce absolute host paths
   (e.g. ``/home/user/workspace/AISE/src/foo.py``) or virtual-root
   paths (``/src/foo.py``). The backend's ``virtual_mode`` already
   handles the leading-slash case, but absolute host paths create
   nested directory trees (``<root>/home/user/...``). We intercept
   every file operation to strip known prefixes so paths resolve
   correctly under the project root.

2. **Write-overwrite** — The native ``write()`` rejects existing files
   with "already exists", which causes LLMs to enter rename loops.
   We allow overwrite since the containment is already guaranteed by
   ``virtual_mode``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


def make_policy_backend(
    project_root: str | Path,
    *,
    layout: Any = None,
    agent_name: str = "agent",
) -> Any:
    """Create a deepagents FilesystemBackend with path normalization.

    Args:
        project_root: Directory where the agent may read/write files.
        layout: Unused (kept for call-site compatibility).
        agent_name: Unused (kept for call-site compatibility).

    Returns:
        A ``FilesystemBackend`` with ``virtual_mode=True``, patched
        ``write`` (allows overwrite), and path normalization on all
        file operations.
    """
    from deepagents.backends import FilesystemBackend
    from deepagents.backends.protocol import WriteResult

    root = Path(project_root).resolve()
    root_str = str(root)
    base = FilesystemBackend(root_dir=str(root), virtual_mode=True)

    # -- Path normalization ------------------------------------------------

    # Prefixes that the LLM might prepend. The project root itself
    # (``/home/user/.../projects/project_3-snake``) and the AISE repo
    # root (``/home/user/.../AISE``) are both common.
    _strip_prefixes: list[str] = []
    _strip_prefixes.append(root_str + "/")  # project root
    _strip_prefixes.append(root_str)
    # Also strip the AISE repo root (2 levels up from src/aise/runtime/)
    aise_root = Path(__file__).resolve().parent.parent.parent.parent
    aise_str = str(aise_root)
    if aise_str != root_str:
        _strip_prefixes.append(aise_str + "/")
        _strip_prefixes.append(aise_str)

    def _normalize(path: str) -> str:
        """Strip absolute host prefixes, leaving a virtual-root-relative path.

        ``/home/user/workspace/AISE/src/foo.py`` → ``/src/foo.py``
        ``/src/foo.py`` → ``/src/foo.py``  (already virtual)
        ``src/foo.py`` → ``src/foo.py``    (already relative)
        """
        for prefix in _strip_prefixes:
            if path.startswith(prefix):
                remainder = path[len(prefix) :]
                # Ensure it starts with / for virtual_mode consistency
                normalized = "/" + remainder.lstrip("/") if remainder else "/"
                if normalized != path:
                    logger.debug("Path normalized: %r → %r", path, normalized)
                return normalized
        return path

    # -- Wrap every file operation with normalization ----------------------

    _orig_write = base.write
    _orig_read = base.read
    _orig_edit = base.edit
    _orig_ls = base.ls_info
    _orig_glob = base.glob_info
    _orig_grep = base.grep_raw

    def norm_write(file_path: str, content: str) -> WriteResult:
        file_path = _normalize(file_path)
        resolved = base._resolve_path(file_path)
        if not resolved.exists():
            return _orig_write(file_path, content)
        # File exists → overwrite in place. No artificial restrictions.
        # The recursion_limit (80) is the safety net against loops.
        try:
            flags = os.O_WRONLY | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved, flags)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            return WriteResult(path=file_path, files_update=None)
        except (OSError, UnicodeEncodeError) as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")

    def norm_read(file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return _orig_read(_normalize(file_path), offset, limit)

    def norm_edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False):
        return _orig_edit(_normalize(file_path), old_string, new_string, replace_all)

    def norm_ls(path: str) -> Any:
        return _orig_ls(_normalize(path))

    def norm_glob(pattern: str, path: str = "/") -> Any:
        return _orig_glob(_normalize(pattern), _normalize(path))

    def norm_grep(pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        norm_path = _normalize(path) if path else path
        return _orig_grep(pattern, norm_path, glob)

    # -- Sandbox: execute support --------------------------------------------
    # FilesystemBackend doesn't implement SandboxBackendProtocol, so
    # deepagents won't expose the `execute` tool. We add execute/aexecute
    # directly so the LLM can run shell commands (e.g. pytest) without
    # resorting to creating runner scripts.

    import asyncio
    import subprocess as _sp

    from deepagents.backends.protocol import ExecuteResponse

    _shell_timeout = 120

    def execute(command: str, *, timeout: int | None = None) -> ExecuteResponse:
        effective_timeout = timeout if timeout and timeout > 0 else _shell_timeout
        try:
            proc = _sp.run(
                command,
                shell=True,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            truncated = len(output) > 10000
            return ExecuteResponse(
                output=output[-10000:],
                exit_code=proc.returncode,
                truncated=truncated,
            )
        except _sp.TimeoutExpired:
            return ExecuteResponse(output=f"Command timed out after {effective_timeout}s", exit_code=-1)
        except Exception as exc:
            return ExecuteResponse(output=f"Error: {exc}", exit_code=-1)

    async def aexecute(command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(execute, command, timeout=timeout)

    base.execute = execute
    base.aexecute = aexecute

    base.write = norm_write
    base.read = norm_read
    base.edit = norm_edit
    base.ls_info = norm_ls
    base.glob_info = norm_glob
    base.grep_raw = norm_grep

    return base
