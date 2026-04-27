"""Sandbox-capable filesystem backend for deepagents with path normalization.

Three extensions over the native ``FilesystemBackend``:

1. **Shell execution** — the backend subclasses
   :class:`SandboxBackendProtocol` so deepagents auto-registers the
   ``execute`` tool. Previously we attached ``execute``/``aexecute`` via
   ``setattr``, but deepagents' ``FilesystemMiddleware`` checks
   ``isinstance(backend, SandboxBackendProtocol)`` (a plain ABC, not a
   ``@runtime_checkable`` Protocol), so the duck-typed attachments were
   silently ignored and worker agents never had a working ``execute``
   tool — observed in dispatch ``e13a04cd449d`` which wasted 98 LLM
   rounds writing ``subprocess.run(…)`` wrapper scripts.

2. **Path normalization** — LLMs frequently produce absolute host paths
   (e.g. ``/home/user/workspace/AISE/src/foo.py``) or virtual-root
   paths (``/src/foo.py``). The backend's ``virtual_mode`` already
   handles the leading-slash case. We intercept every file operation to
   strip the project root prefix (so ``<project_root>/src/foo.py`` →
   ``/src/foo.py``) and reject paths that escape the project root
   (``/home/other/...``, ``/etc/...``, ``/tmp/...``, etc.).

3. **Write-overwrite** — The native ``write()`` rejects existing files
   with "already exists", which causes LLMs to enter rename loops.
   We allow overwrite since the containment is already guaranteed by
   ``virtual_mode``.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    SandboxBackendProtocol,
    WriteResult,
)

from ..utils.logging import get_logger

logger = get_logger(__name__)


_DEFAULT_SHELL_TIMEOUT = 120
_MAX_OUTPUT_BYTES = 10000


class SandboxFilesystemBackend(FilesystemBackend, SandboxBackendProtocol):
    """``FilesystemBackend`` that advertises :class:`SandboxBackendProtocol`.

    The parent ``FilesystemBackend`` handles all virtual-root file ops.
    We add :meth:`execute` and :meth:`aexecute` so ``isinstance`` checks
    inside deepagents' middleware recognize this backend as shell-capable
    — which is what triggers the ``execute`` tool to be bound to the
    agent's tool list.

    Run behavior: commands execute via ``subprocess.run(shell=True)``
    with ``cwd`` set to the project root. No allowlist is enforced here;
    the worker agent is already sandboxed by its project_root and the
    rest of its restricted tool surface. Orchestrator-level dispatches
    still use the separate ``execute_shell`` tool from ``aise.tools.shell``
    (which *does* have an allowlist).
    """

    def __init__(
        self,
        root_dir: str,
        *,
        virtual_mode: bool = True,
        shell_timeout: int = _DEFAULT_SHELL_TIMEOUT,
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=virtual_mode)
        self._shell_timeout = shell_timeout
        self._sandbox_id = f"fs:{root_dir}"

    @property
    def id(self) -> str:
        return self._sandbox_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        effective_timeout = timeout if timeout and timeout > 0 else self._shell_timeout
        try:
            proc = subprocess.run(  # noqa: S602 — sandboxed to project_root, worker tool
                command,
                shell=True,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            truncated = len(output) > _MAX_OUTPUT_BYTES
            return ExecuteResponse(
                output=output[-_MAX_OUTPUT_BYTES:],
                exit_code=proc.returncode,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Command timed out after {effective_timeout}s",
                exit_code=-1,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return ExecuteResponse(output=f"Error: {exc}", exit_code=-1)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)


def make_policy_backend(
    project_root: str | Path,
    *,
    layout: Any = None,
    agent_name: str = "agent",
) -> Any:
    """Create a ``SandboxFilesystemBackend`` with path normalization + guards.

    Args:
        project_root: Directory where the agent may read/write files.
        layout: Unused (kept for call-site compatibility).
        agent_name: Unused (kept for call-site compatibility).

    Returns:
        A :class:`SandboxFilesystemBackend` instance with:

        - ``virtual_mode=True`` (leading-slash paths rooted at project_root)
        - ``write`` allowing overwrite
        - Path normalization and escape-path rejection
        - Loop-detection after 3 consecutive identical no-op writes/edits
        - Rejection of the SummarizationMiddleware ``"...(argument truncated)"``
          marker
        - Native ``execute`` / ``aexecute`` inherited from the class so
          deepagents' ``FilesystemMiddleware`` auto-registers the
          ``execute`` tool via its ``isinstance(backend,
          SandboxBackendProtocol)`` check.
    """
    root = Path(project_root).resolve()
    root_str = str(root)
    base = SandboxFilesystemBackend(root_dir=str(root), virtual_mode=True)

    # -- Path normalization ------------------------------------------------

    # Prefixes the LLM might prepend to reach files inside THIS project.
    # We only strip the project root — absolute paths pointing outside
    # the project (``/home/user/workspace/AISE/...``, ``/etc/...``, etc.)
    # are rejected rather than silently remapped. An earlier version
    # stripped the AISE repo root too, which let a confused PM write
    # ``/home/user/.../AISE/src/aise/docs/requirement.md`` and have it
    # land at ``projects/<proj>/src/aise/docs/requirement.md`` — wrong
    # location, and the LLM had no way to notice the mistake because
    # the write silently succeeded.
    _project_strip_prefixes: tuple[str, ...] = (root_str + "/", root_str)

    # System paths we know a project write should never touch. Used to
    # flag escape attempts when a path starts with ``/`` but does not
    # point inside the project.
    _ESCAPE_PREFIXES: tuple[str, ...] = (
        "/home/",
        "/opt/",
        "/usr/",
        "/etc/",
        "/tmp/",
        "/var/",
        "/mnt/",
        "/root/",
        "/boot/",
        "/dev/",
        "/proc/",
        "/sys/",
    )

    def _normalize(path: str) -> str | None:
        """Return a virtual-root-relative path, or None if the path escapes.

        - ``/<project_root>/src/foo.py`` → ``/src/foo.py``
        - ``/src/foo.py`` (virtual) → ``/src/foo.py``
        - ``src/foo.py`` (relative) → ``src/foo.py``
        - ``/home/other/…`` → None  (reject: escapes project root)
        """
        for prefix in _project_strip_prefixes:
            if path.startswith(prefix):
                remainder = path[len(prefix) :]
                normalized = "/" + remainder.lstrip("/") if remainder else "/"
                if normalized != path:
                    logger.debug("Path normalized: %r → %r", path, normalized)
                return normalized
        # Relative path or already-virtual absolute path: pass through.
        if not path.startswith("/"):
            return path
        # Absolute host path that isn't in the project. If it targets a
        # known system directory, reject outright; otherwise trust the
        # deepagents virtual_mode resolver (it will root under the
        # project anyway, but at least non-system paths aren't escape
        # attempts).
        if path.startswith(_ESCAPE_PREFIXES):
            logger.warning("Path escapes project root, rejecting: %r", path)
            return None
        return path

    def _escape_error(file_path: str) -> str:
        return (
            f"Path '{file_path}' is outside this project's root. "
            "Use relative paths (e.g. 'docs/requirement.md') or paths "
            "rooted at the project (e.g. '/docs/requirement.md'). Do "
            "NOT use absolute host paths like /home/user/workspace/..."
        )

    # Summarization middleware replaces past ``write_file.content`` /
    # ``edit_file.new_string`` arguments with this marker when the context
    # grows too large. Weak local LLMs then read their own truncated
    # history and emit a new ``write_file`` whose ``content`` is literally
    # the marker string — which would destructively overwrite the real
    # file with a 43-byte garbage payload. We refuse such writes.
    _TRUNCATION_MARKER = "...(argument truncated)"

    def _truncation_marker_error(tool: str, file_path: str) -> str:
        return (
            f"Refusing {tool} on '{file_path}': the content argument "
            f"contains the summarization-middleware marker "
            f"{_TRUNCATION_MARKER!r}. That marker is a placeholder the "
            "conversation middleware puts in place of a large tool-call "
            "argument in your history — it is NOT real content. "
            "Regenerate the full file content from the original task "
            "requirements, or use read_file to see the current on-disk "
            "content before deciding what to write."
        )

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
        normalized = _normalize(file_path)
        if normalized is None:
            return WriteResult(error=_escape_error(file_path))
        file_path = normalized
        if _TRUNCATION_MARKER in content:
            logger.warning(
                "write_file refused: content contains truncation marker (%s)",
                file_path,
            )
            return WriteResult(error=_truncation_marker_error("write_file", file_path))
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
        normalized = _normalize(file_path)
        if normalized is None:
            return _escape_error(file_path)
        return _orig_read(normalized, offset, limit)

    def norm_edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False):
        normalized = _normalize(file_path)
        if normalized is None:
            return EditResult(error=_escape_error(file_path))
        file_path = normalized
        if _TRUNCATION_MARKER in new_string:
            logger.warning(
                "edit_file refused: new_string contains truncation marker (%s)",
                file_path,
            )
            return EditResult(error=_truncation_marker_error("edit_file", file_path))
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
        normalized = _normalize(path)
        if normalized is None:
            # Raise, rather than silently remap to project root. The old
            # fallback returned the project root's contents for any
            # escape path, which fooled the LLM into believing that
            # ``ls /home/.../AISE/src`` worked — it built a false model
            # of the filesystem and then tried ``write_file`` on the
            # same escape path. Deepagents' tool wrapper converts this
            # exception to a ToolMessage the LLM can see and learn from.
            raise PermissionError(_escape_error(path))
        return _orig_ls(normalized)

    def norm_glob(pattern: str, path: str = "/") -> Any:
        # Only treat ``pattern`` as a path when it looks like one. A
        # leading-``/`` pattern (``/src/**/*.py``) is a virtual-root
        # pattern and passes through normalize; bare patterns
        # (``**/*.py``) are globs relative to ``path``.
        p_norm = _normalize(pattern) if pattern and pattern.startswith("/") else pattern
        base_norm = _normalize(path)
        if p_norm is None or base_norm is None:
            bad = path if base_norm is None else pattern
            raise PermissionError(_escape_error(bad))
        return _orig_glob(p_norm, base_norm)

    def norm_grep(pattern: str, path: str | None = None, glob: str | None = None) -> Any:
        if path:
            normalized = _normalize(path)
            if normalized is None:
                raise PermissionError(_escape_error(path))
        else:
            normalized = path
        return _orig_grep(pattern, normalized, glob)

    # ``execute`` / ``aexecute`` come from the :class:`SandboxFilesystemBackend`
    # class itself — no patching needed. The ``isinstance(backend,
    # SandboxBackendProtocol)`` check in deepagents' FilesystemMiddleware
    # now succeeds, so the ``execute`` tool is registered automatically.

    base.write = norm_write
    base.read = norm_read
    base.edit = norm_edit
    base.ls_info = norm_ls
    base.glob_info = norm_glob
    base.grep_raw = norm_grep

    return base
