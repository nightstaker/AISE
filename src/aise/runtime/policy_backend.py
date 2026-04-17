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
    from deepagents.backends.protocol import EditResult, WriteResult

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

    # Session-scoped loop detector. Weak local LLMs can get stuck emitting
    # the same ``write_file``/``edit_file`` tool call regardless of what
    # the tool returned — neither success nor error breaks the generation
    # pattern. We track the last ``(tool, path, content_hash)`` signature
    # and its consecutive-repeat count; after ``_NOOP_STREAK_LIMIT``
    # identical no-ops in a row, the tool starts returning a hard
    # ``LOOP_DETECTED`` error. That won't force the LLM to stop (nothing
    # can, short of ``recursion_limit``), but it caps the damage per path
    # and makes the pathology obvious in logs.
    _NOOP_STREAK_LIMIT = 3
    _last_noop_sig: dict[str, tuple[str, str]] = {}  # path → (tool, content_hash)
    _noop_streak: int = 0  # consecutive no-ops matching _last_noop_sig

    def _track_noop(tool: str, file_path: str, content: str) -> bool:
        """Record a no-op call. Return True if the streak exceeded the limit."""
        nonlocal _noop_streak
        import hashlib

        sig = (tool, hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest())
        last = _last_noop_sig.get(file_path)
        if last == sig:
            _noop_streak += 1
        else:
            _last_noop_sig[file_path] = sig
            _noop_streak = 1
        if _noop_streak >= _NOOP_STREAK_LIMIT:
            logger.warning(
                "Loop detected: %s no-op on %s repeated %d× — returning error",
                tool,
                file_path,
                _noop_streak,
            )
            return True
        return False

    def _reset_noop_streak() -> None:
        nonlocal _noop_streak
        _noop_streak = 0

    def norm_write(file_path: str, content: str) -> WriteResult:
        file_path = _normalize(file_path)
        resolved = base._resolve_path(file_path)
        if not resolved.exists():
            _reset_noop_streak()
            return _orig_write(file_path, content)
        # File exists — compare content before overwriting
        try:
            existing = resolved.read_text(encoding="utf-8")
        except Exception:
            existing = None
        if existing is not None and existing == content:
            # Target state already satisfied. Return success on the first
            # ``_NOOP_STREAK_LIMIT - 1`` repeats so the LLM doesn't get
            # stuck in an error-retry cycle for benign cases. Beyond that,
            # surface a LOOP_DETECTED error so it's visible in the trace.
            if _track_noop("write_file", file_path, content):
                return WriteResult(
                    error=(
                        f"LOOP_DETECTED: write_file called {_NOOP_STREAK_LIMIT}× "
                        f"in a row with identical content on '{file_path}'. "
                        "File is already up to date. Stop calling this tool and "
                        "respond with a text summary instead."
                    )
                )
            logger.debug("write_file no-op (identical content): %s", file_path)
            return WriteResult(path=file_path, files_update=None)
        # Content differs → overwrite (a real change resets the streak)
        _reset_noop_streak()
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
        file_path = _normalize(file_path)
        # old_string == new_string is a no-op. Return success so the LLM
        # doesn't enter an error-retry loop. After _NOOP_STREAK_LIMIT
        # identical repeats the tool returns a LOOP_DETECTED error.
        if old_string == new_string:
            if _track_noop("edit_file", file_path, new_string):
                return EditResult(
                    error=(
                        f"LOOP_DETECTED: edit_file called {_NOOP_STREAK_LIMIT}× "
                        f"in a row with identical old/new strings on '{file_path}'. "
                        "Nothing to change. Stop calling this tool and respond "
                        "with a text summary instead."
                    )
                )
            logger.debug("edit_file no-op (old_string == new_string): %s", file_path)
            return EditResult(path=file_path, files_update=None, occurrences=0)
        _reset_noop_streak()
        # Try the real edit first
        result = _orig_edit(file_path, old_string, new_string, replace_all)
        if result.error and "not found" in result.error.lower():
            # old_string didn't match — guide the LLM to use write_file instead
            return EditResult(
                error=(
                    f"old_string not found in '{file_path}'. "
                    "Use read_file to see the current content, then call "
                    "write_file with the complete new content to replace the file."
                )
            )
        return result

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
