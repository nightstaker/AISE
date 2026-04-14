"""RuntimeManager — scan agent.md definitions and initialize via AgentRuntime.

On startup the manager scans ``src/aise/agents/`` for ``*.md`` files,
parses each one with :func:`parse_agent_md`, and creates an
:class:`AgentRuntime` instance for every definition found.  Each runtime
is then activated via ``evoke()`` so it can accept messages.

Usage::

    manager = RuntimeManager(config=project_config)
    manager.start()                      # scan + init + evoke
    agents = manager.get_agents_status() # for Monitor API
    manager.stop()
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import ModelConfig, ProjectConfig
from ..utils.logging import get_logger
from .agent_runtime import AgentRuntime
from .llm_factory import build_llm as _factory_build_llm
from .models import AgentState
from .runtime_config import LLMDefaults

logger = get_logger(__name__)


def _agents_dir() -> Path:
    """Return the path to ``src/aise/agents/``."""
    return Path(__file__).resolve().parent.parent / "agents"


class RuntimeManager:
    """Manages the lifecycle of agents discovered from agent.md definitions.

    Scans ``aise/agents/`` for ``*.md`` files, creates an
    :class:`AgentRuntime` per file, and activates each one.
    """

    def __init__(self, config: ProjectConfig | None = None) -> None:
        self._config = config or ProjectConfig()
        self._runtimes: dict[str, AgentRuntime] = {}
        self._started_at: datetime | None = None
        self._started = False

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Scan for agent.md files and initialize each via AgentRuntime."""
        if self._started:
            logger.warning("RuntimeManager already started")
            return

        md_files = _discover_agent_md_files()
        logger.info(
            "Agent definitions discovered: count=%d files=%s",
            len(md_files),
            [f.name for f in md_files],
        )

        for md_path in md_files:
            try:
                self._init_runtime(md_path)
            except Exception as exc:
                logger.error("Failed to initialize agent from %s: %s", md_path.name, exc)

        self._started_at = datetime.now(timezone.utc)
        self._started = True
        logger.info("RuntimeManager started: agents=%d", len(self._runtimes))

    def stop(self) -> None:
        """Stop all runtimes and clean up."""
        for rt in self._runtimes.values():
            try:
                rt.stop()
            except Exception:
                pass
        self._runtimes.clear()
        self._started = False
        logger.info("RuntimeManager stopped")

    # -- Agent access --------------------------------------------------------

    @property
    def runtimes(self) -> dict[str, AgentRuntime]:
        """All active AgentRuntime instances keyed by agent name."""
        return dict(self._runtimes)

    def get_runtime(self, name: str) -> AgentRuntime | None:
        return self._runtimes.get(name)

    def get_agents_status(self) -> list[dict[str, Any]]:
        """Return status info for every managed agent (for Monitor API).

        Each entry includes metadata and a full A2A agent card read
        directly from the AgentRuntime.
        """
        result: list[dict[str, Any]] = []
        for name, rt in self._runtimes.items():
            card = rt.agent_card
            card_dict = card.to_dict()
            defn = rt.definition

            # Enrich card with model details from the definition metadata
            model_info = defn.metadata.get("_model_info", {})

            result.append(
                {
                    "agent_id": f"runtime__{name}",
                    "name": name,
                    "role": name,
                    "role_display": card.name.replace("_", " ").title() if card.name else name,
                    "project_id": "",
                    "project_name": "",
                    "source": "runtime",
                    "model": model_info,
                    "skills": [s.id for s in card.skills],
                    "status": _map_state(rt.state),
                    "current_task": rt.current_task,
                    "agent_card": {
                        **card_dict,
                        "model": model_info,
                    },
                }
            )
        return result

    # -- Internal ------------------------------------------------------------

    def _init_runtime(self, md_path: Path) -> None:
        """Create and activate an AgentRuntime from a single agent.md file."""
        from .agent_md_parser import parse_agent_md

        defn = parse_agent_md(md_path)
        agent_name = defn.name

        if agent_name in self._runtimes:
            logger.warning("Duplicate agent name, skipping: %s", agent_name)
            return

        # Resolve model from ProjectConfig (per-agent or default)
        model_cfg = self._config.get_model_config(agent_name)
        llm = _build_llm(model_cfg)

        # Use an empty skills directory (skills are metadata in agent.md)
        skills_dir = md_path.parent / "_runtime_skills"
        skills_dir.mkdir(exist_ok=True)

        rt = AgentRuntime(
            agent_md=md_path,
            skills_dir=skills_dir,
            model=llm,
        )

        # Stash model info so the Monitor can display it
        rt.definition.metadata["_model_info"] = {
            "provider": model_cfg.provider,
            "model": model_cfg.model,
            "temperature": model_cfg.temperature,
            "maxTokens": model_cfg.max_tokens,
        }

        rt.evoke()
        self._runtimes[agent_name] = rt

        logger.info(
            "AgentRuntime initialized: name=%s md=%s state=%s skills=%d",
            agent_name,
            md_path.name,
            rt.state.value,
            len(rt.agent_card.skills),
        )


def _discover_agent_md_files() -> list[Path]:
    """Scan ``aise/agents/`` for ``*.md`` agent definition files."""
    agents_path = _agents_dir()
    if not agents_path.is_dir():
        logger.warning("Agents directory not found: %s", agents_path)
        return []

    files = sorted(agents_path.glob("*.md"))
    return files


def _map_state(state: AgentState) -> str:
    """Map AgentRuntime state to Monitor status string."""
    if state == AgentState.WORKING:
        return "working"
    if state == AgentState.ACTIVE:
        return "standby"
    if state == AgentState.STOPPED:
        return "stopped"
    return "standby"


# Back-compat shim. The real factory lives in :mod:`llm_factory` and is
# provider-pluggable; existing call sites and tests that monkeypatch
# ``aise.runtime.manager._build_llm`` continue to work because they hit
# this thin wrapper.
def _build_llm(config: ModelConfig) -> Any:
    """Build a chat model using the runtime LLM factory."""
    return _factory_build_llm(config, LLMDefaults())
