"""Log file access + LLM-driven analysis for the web console.

Exposes:

- ``LogService.list_files()`` — enumerate rotated / current log files.
- ``LogService.read_tail(...)`` — filter + tail log lines with parsing
  into structured records (timestamp / level / logger / message).
- ``LogService.analyze(...)`` — ship a text excerpt to a registered
  AgentRuntime (defaults to ``rd_director``) for LLM summarisation and
  root-cause reasoning.

The module deliberately keeps parsing loose: AISE logs are written in
the standard format ``%(asctime)s | %(levelname)s | %(name)s |
%(message)s`` (see ``utils/logging.py``). A JSON formatter is also
supported — lines that parse as a JSON object with a ``level`` field
are treated as JSON records.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..utils.logging import get_logger

logger = get_logger(__name__)


# Standard pipe-delimited plain-text line produced by the shared formatter:
#   2026-04-21 12:34:56 | INFO | aise.web.app | some message
_PLAIN_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s*\|\s*"
    r"(?P<level>[A-Z]+)\s*\|\s*"
    r"(?P<logger>[\w.\-]+)\s*\|\s*"
    r"(?P<message>.*)$"
)

LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "WARN": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}


@dataclass
class LogRecord:
    """One parsed log line ready for the UI."""

    raw: str
    timestamp: str = ""
    level: str = ""
    logger_name: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
        }


def _parse_line(line: str) -> LogRecord:
    """Best-effort parse of a single log line.

    Falls back to ``raw``-only record if no structured format matches
    so the UI can still display the line.
    """
    stripped = line.rstrip("\n")
    if not stripped:
        return LogRecord(raw="")

    # JSON formatter path
    if stripped[:1] == "{":
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and "level" in obj:
                return LogRecord(
                    raw=stripped,
                    timestamp=str(obj.get("ts", "")),
                    level=str(obj.get("level", "")).upper(),
                    logger_name=str(obj.get("logger", "")),
                    message=str(obj.get("message", "")),
                )
        except Exception:
            pass

    match = _PLAIN_LINE_RE.match(stripped)
    if match:
        return LogRecord(
            raw=stripped,
            timestamp=match.group("ts"),
            level=match.group("level").upper(),
            logger_name=match.group("logger"),
            message=match.group("message"),
        )

    return LogRecord(raw=stripped, message=stripped)


def _iter_lines_tail(path: Path, max_lines: int) -> Iterable[str]:
    """Read up to ``max_lines`` from the tail of the file.

    Streams the whole file through a bounded ``deque`` — simple and
    robust for the sizes web consoles care about (single-digit MB).
    """
    if max_lines <= 0:
        return ()
    buf: deque[str] = deque(maxlen=max_lines)
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            buf.append(line)
    return list(buf)


class LogService:
    """Thin service wrapping log-dir reads and a dispatch hook."""

    def __init__(self, log_dir: str | Path, *, runtime_manager: Any | None = None) -> None:
        self._log_dir = Path(log_dir)
        self._runtime_manager = runtime_manager

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def set_runtime_manager(self, runtime_manager: Any) -> None:
        self._runtime_manager = runtime_manager

    # -- Listing -------------------------------------------------------------

    def list_files(self) -> list[dict[str, Any]]:
        """Return metadata for every log file in the directory.

        Includes both the current rotated file (``aise.log``) and the
        dated backups (``aise.log.2026-04-19``) so admins can read
        historical runs, not just today's log.
        """
        if not self._log_dir.is_dir():
            return []
        items: list[dict[str, Any]] = []
        for entry in self._log_dir.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if not (name.endswith(".log") or ".log." in name):
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            items.append(
                {
                    "name": name,
                    "size": st.st_size,
                    "mtime": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
                }
            )
        items.sort(key=lambda item: item["mtime"], reverse=True)
        return items

    # -- Reading -------------------------------------------------------------

    def read_tail(
        self,
        *,
        filename: str,
        limit: int = 500,
        level: str | None = None,
        logger_filter: str | None = None,
        query: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Read + filter the tail of a log file.

        Returns a dict with ``file``, ``records`` (list[LogRecord]),
        ``total_read``, ``returned``, and ``truncated`` so the UI can
        tell the user whether more lines exist outside the window.
        """
        if not filename:
            raise ValueError("filename is required")
        # Path traversal guard.
        candidate = (self._log_dir / filename).resolve()
        root = self._log_dir.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("filename escapes log directory") from exc
        if not candidate.is_file():
            raise FileNotFoundError(filename)

        limit = max(1, min(int(limit), 5000))
        raw_level = (level or "").strip().upper()
        level_threshold = LEVEL_ORDER.get(raw_level)
        logger_substring = (logger_filter or "").strip()
        query_lc = (query or "").strip().lower()
        since_norm = _normalize_iso(since)
        until_norm = _normalize_iso(until)

        # Oversample 3x so filters don't leave the UI with a near-empty
        # result when the user asks for "latest 100 ERRORs".
        read_max = min(limit * 3 + 200, 20000)
        total_scanned = 0
        matched: list[LogRecord] = []
        for raw in _iter_lines_tail(candidate, read_max):
            total_scanned += 1
            record = _parse_line(raw)
            if level_threshold is not None:
                rec_level = LEVEL_ORDER.get(record.level.upper())
                if rec_level is None or rec_level < level_threshold:
                    continue
            if logger_substring:
                if logger_substring.lower() not in record.logger_name.lower():
                    continue
            if query_lc:
                if query_lc not in raw.lower():
                    continue
            if since_norm or until_norm:
                rec_ts = _normalize_iso(record.timestamp)
                if since_norm and (rec_ts is None or rec_ts < since_norm):
                    continue
                if until_norm and (rec_ts is None or rec_ts > until_norm):
                    continue
            matched.append(record)
            if len(matched) > limit:
                matched.pop(0)
        return {
            "file": filename,
            "total_scanned": total_scanned,
            "returned": len(matched),
            "records": [r.to_dict() for r in matched],
            "truncated": total_scanned >= read_max,
        }

    # -- Analysis ------------------------------------------------------------

    def analyze(
        self,
        *,
        records_text: str,
        focus: str = "",
        agent_name: str = "rd_director",
    ) -> dict[str, Any]:
        """Ship ``records_text`` to an agent runtime for analysis.

        The default target is ``rd_director`` because it already
        inspects other agents' outputs and has a broad system view.
        Falls back to ``project_manager`` then the first available
        runtime so the feature works even on stripped-down setups.
        """
        if self._runtime_manager is None:
            raise RuntimeError("LogService has no runtime_manager — cannot analyze")
        text = (records_text or "").strip()
        if not text:
            raise ValueError("records_text is empty")
        # Clamp size so a clueless admin doesn't ship 20MB of logs.
        MAX_CHARS = 40000
        truncated = False
        if len(text) > MAX_CHARS:
            text = text[-MAX_CHARS:]
            truncated = True

        candidates = [agent_name, "rd_director", "project_manager"]
        runtime = None
        for name in candidates:
            candidate = self._runtime_manager.get_runtime(name)
            if candidate is not None:
                runtime = candidate
                agent_name = name
                break
        if runtime is None:
            runtimes = getattr(self._runtime_manager, "runtimes", {}) or {}
            if runtimes:
                agent_name, runtime = next(iter(runtimes.items()))
        if runtime is None:
            raise RuntimeError("No agent runtime available for log analysis")

        focus_hint = focus.strip()
        prompt = (
            "You are a senior SRE reviewing AISE application logs.\n\n"
            "Return a concise Markdown report with EXACTLY these sections:\n"
            "1. **Summary** — one or two sentences describing what is happening.\n"
            "2. **Severity** — one of NORMAL / WARNING / CRITICAL with a short justification.\n"
            "3. **Top Issues** — a numbered list of the 1-5 most impactful problems. For each:\n"
            "   - a one-line symptom,\n"
            "   - the logger/module that produced it,\n"
            "   - the likely root cause (be specific — name the function, config, or dependency),\n"
            "   - suggested next action.\n"
            "4. **Errors vs Warnings vs Info** — counts of each.\n"
            "5. **Notable Loggers** — short table of the top 3 loggers by volume.\n"
            "6. **Follow-up Questions** — 1-3 diagnostic questions worth answering.\n\n"
            "Rules:\n"
            "- Do NOT invent log lines; only analyze what is supplied.\n"
            "- Quote at most one short log excerpt per issue (<=200 chars).\n"
            "- If the log is empty or uninformative, say so clearly.\n"
        )
        if focus_hint:
            prompt += f"\nAdditional focus from the operator: {focus_hint}\n"
        if truncated:
            prompt += "\n(Note: only the most recent segment of the log is shown.)\n"
        prompt += "\n--- LOG EXCERPT START ---\n" + text + "\n--- LOG EXCERPT END ---\n"

        try:
            response = runtime.handle_message(prompt)
        except Exception as exc:
            logger.warning("Log analysis dispatch failed: agent=%s error=%s", agent_name, exc)
            raise
        return {
            "agent": agent_name,
            "analysis": response or "",
            "truncated": truncated,
            "input_chars": len(text),
        }


def _normalize_iso(value: str | None) -> str | None:
    """Lowercase ISO-8601 string for lexicographic comparison.

    Log timestamps are already ISO-like, so a plain string compare is
    enough to implement ``since/until`` without pulling in timezone
    math. If parsing fails we return the raw string — the caller will
    either compare or skip it as appropriate.
    """
    if not value:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    # Convert ``YYYY-MM-DD HH:MM:SS`` to ``YYYY-MM-DDTHH:MM:SS`` for
    # consistent comparison against ISO inputs from the frontend.
    if " " in stripped and "T" not in stripped:
        stripped = stripped.replace(" ", "T", 1)
    return stripped
