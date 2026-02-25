"""Standard workflow process definitions and repository for Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _parse_meta_line(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw.startswith("- "):
        return None
    body = raw[2:]
    if ":" not in body:
        return None
    key, value = body.split(":", 1)
    return key.strip().lower().replace(" ", "_"), value.strip()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _merge_requirement_lists(
    base_agent_md: list[str] | None,
    process_global: list[str] | None,
    step_specific: list[str] | None,
) -> list[str]:
    """Merge agent requirements with override precedence.

    Precedence: step > process global > agent md.
    For lines of form ``key: value``, later layers override by key.
    Plain lines are appended with de-duplication.
    """

    def parse(items: list[str] | None) -> tuple[list[str], dict[str, str]]:
        plain: list[str] = []
        keyed: dict[str, str] = {}
        for item in items or []:
            raw = str(item).strip()
            if not raw:
                continue
            if ":" in raw:
                k, v = raw.split(":", 1)
                k_norm = _norm(k)
                if k_norm:
                    keyed[k_norm] = f"{k.strip()}: {v.strip()}"
                    continue
            plain.append(raw)
        return plain, keyed

    base_plain, base_keyed = parse(base_agent_md)
    proc_plain, proc_keyed = parse(process_global)
    step_plain, step_keyed = parse(step_specific)
    merged_keyed = dict(base_keyed)
    merged_keyed.update(proc_keyed)
    merged_keyed.update(step_keyed)
    return _dedup_keep_order(base_plain + proc_plain + step_plain + list(merged_keyed.values()))


@dataclass(slots=True)
class ProcessStepDefinition:
    step_id: str
    name: str
    participating_agents: list[str] = field(default_factory=list)
    description: str = ""
    agent_responsibilities: dict[str, list[str]] = field(default_factory=dict)
    agent_requirements: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "participating_agents": list(self.participating_agents),
            "description": self.description,
            "agent_responsibilities": {k: list(v) for k, v in self.agent_responsibilities.items()},
            "agent_requirements": {k: list(v) for k, v in self.agent_requirements.items()},
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ProcessDefinition:
    process_id: str
    name: str
    work_type: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    global_agent_requirements: dict[str, list[str]] = field(default_factory=dict)
    steps: list[ProcessStepDefinition] = field(default_factory=list)
    file_path: str = ""
    raw_markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "name": self.name,
            "work_type": self.work_type,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "step_count": len(self.steps),
            "file_path": self.file_path,
        }

    def resolve_agent_requirements(
        self,
        *,
        agent_type: str,
        step_id: str | None = None,
        agent_md_requirements: list[str] | None = None,
    ) -> list[str]:
        step_specific = None
        if step_id is not None:
            step = next((s for s in self.steps if s.step_id == step_id), None)
            if step is not None:
                step_specific = step.agent_requirements.get(agent_type, [])
        process_global = self.global_agent_requirements.get(agent_type, [])
        return _merge_requirement_lists(agent_md_requirements, process_global, step_specific)

    def matches(self, text: str) -> float:
        prompt = _norm(text)
        if not prompt:
            return 0.0
        score = 0.0
        for token in [_norm(self.work_type), _norm(self.name)]:
            if token and token in prompt:
                score += 2.0
        summary_tokens = [tok for tok in _norm(self.summary).split(" ") if tok]
        score += sum(0.2 for tok in summary_tokens if tok and tok in prompt)
        for kw in self.keywords:
            kw_norm = _norm(kw)
            if kw_norm and kw_norm in prompt:
                score += 1.2
        return score

    def render_for_prompt(self) -> str:
        lines = [
            f"Process ID: {self.process_id}",
            f"Process Name: {self.name}",
            f"Work Type: {self.work_type}",
            f"Summary: {self.summary}",
        ]
        if self.keywords:
            lines.append(f"Keywords: {', '.join(self.keywords)}")
        if self.global_agent_requirements:
            lines.append("Global Agent Requirements:")
            for agent, reqs in self.global_agent_requirements.items():
                lines.append(f"- {agent}: " + "; ".join(reqs))
        if self.steps:
            lines.append("Steps:")
            for idx, step in enumerate(self.steps, start=1):
                lines.append(
                    f"{idx}. {step.step_id} | {step.name} | agents={', '.join(step.participating_agents) or '-'}"
                )
                if step.description:
                    lines.append(f"   desc: {step.description}")
                for agent, duties in step.agent_responsibilities.items():
                    lines.append(f"   responsibility[{agent}]: " + "; ".join(duties))
                for agent, reqs in step.agent_requirements.items():
                    lines.append(f"   requirements[{agent}]: " + "; ".join(reqs))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "name": self.name,
            "work_type": self.work_type,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "global_agent_requirements": {k: list(v) for k, v in self.global_agent_requirements.items()},
            "steps": [s.to_dict() for s in self.steps],
            "file_path": self.file_path,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ProcessSelection:
    process: ProcessDefinition
    score: float

    def to_dict(self) -> dict[str, Any]:
        payload = self.process.summary_dict()
        payload["score"] = self.score
        return payload


class ProcessRepository:
    """Loads ``*.process.md`` files and exposes process definitions.

    Default directory is ``src/aise/processes``.
    """

    def __init__(self, process_dir: str | Path | None = None) -> None:
        self.process_dir = Path(process_dir) if process_dir else (Path(__file__).resolve().parents[1] / "processes")
        self._processes: dict[str, ProcessDefinition] = {}
        self.scan()

    def scan(self) -> list[ProcessDefinition]:
        self._processes = {}
        for path in sorted(self.process_dir.glob("*.process.md")):
            process = self._parse_process_markdown(path)
            self._processes[process.process_id] = process
        return self.list_processes()

    def list_processes(self) -> list[ProcessDefinition]:
        return list(self._processes.values())

    def get_process(self, process_id: str) -> ProcessDefinition | None:
        return self._processes.get(process_id)

    def summaries(self) -> list[dict[str, Any]]:
        return [p.summary_dict() for p in self.list_processes()]

    def select_process(self, prompt: str, *, min_score: float = 1.2) -> ProcessSelection | None:
        scored: list[ProcessSelection] = []
        for process in self.list_processes():
            score = process.matches(prompt)
            if score > 0:
                scored.append(ProcessSelection(process=process, score=score))
        if not scored:
            return None
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[0] if scored[0].score >= min_score else None

    def _parse_process_markdown(self, path: Path) -> ProcessDefinition:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        title = path.stem
        meta: dict[str, str] = {}
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if line.startswith("# "):
                title = line[2:].strip() or title
                i += 1
                continue
            parsed = _parse_meta_line(line)
            if parsed:
                meta[parsed[0]] = parsed[1]
                i += 1
                continue
            if line.strip().startswith("## "):
                break
            i += 1

        process = ProcessDefinition(
            process_id=meta.get("process_id", path.stem.replace(".process", "")),
            name=meta.get("name", title),
            work_type=meta.get("work_type", "general"),
            summary=meta.get("summary", ""),
            keywords=_split_csv(meta.get("keywords", "")),
            file_path=str(path),
            raw_markdown=text,
        )

        section = ""
        current_step: ProcessStepDefinition | None = None
        subsection = ""
        current_agent = ""

        def ensure_step() -> ProcessStepDefinition:
            nonlocal current_step
            if current_step is None:
                current_step = ProcessStepDefinition(
                    step_id=f"step_{len(process.steps) + 1}", name=f"Step {len(process.steps) + 1}"
                )
                process.steps.append(current_step)
            return current_step

        while i < len(lines):
            raw = lines[i].rstrip()
            line = raw.strip()
            if not line:
                i += 1
                continue

            if line.startswith("## "):
                section = line[3:].strip().lower()
                subsection = ""
                current_agent = ""
                i += 1
                continue

            if section.startswith("global agent requirements"):
                if line.startswith("### "):
                    current_agent = line[4:].strip()
                    process.global_agent_requirements.setdefault(current_agent, [])
                elif line.startswith("- ") and current_agent:
                    process.global_agent_requirements[current_agent].append(line[2:].strip())
                i += 1
                continue

            if section.startswith("steps"):
                if line.startswith("### "):
                    header = line[4:].strip()
                    if ":" in header:
                        step_id, step_name = header.split(":", 1)
                    elif "|" in header:
                        step_id, step_name = header.split("|", 1)
                    else:
                        step_id, step_name = f"step_{len(process.steps) + 1}", header
                    current_step = ProcessStepDefinition(step_id=step_id.strip(), name=step_name.strip())
                    process.steps.append(current_step)
                    subsection = ""
                    current_agent = ""
                    i += 1
                    continue

                step = ensure_step()
                if line.startswith("- ") and not current_agent:
                    meta_line = _parse_meta_line(line)
                    if meta_line:
                        key, value = meta_line
                        if key == "agents":
                            step.participating_agents = _split_csv(value)
                        elif key == "description":
                            step.description = value
                        else:
                            step.metadata[key] = value
                        i += 1
                        continue

                if line.startswith("#### "):
                    subsection = line[5:].strip().lower()
                    current_agent = ""
                    i += 1
                    continue

                if line.startswith("##### "):
                    current_agent = line[6:].strip()
                    if "responsibilit" in subsection:
                        step.agent_responsibilities.setdefault(current_agent, [])
                    elif "requirement" in subsection:
                        step.agent_requirements.setdefault(current_agent, [])
                    i += 1
                    continue

                if line.startswith("- ") and current_agent:
                    if "responsibilit" in subsection:
                        step.agent_responsibilities.setdefault(current_agent, []).append(line[2:].strip())
                    elif "requirement" in subsection:
                        step.agent_requirements.setdefault(current_agent, []).append(line[2:].strip())
                    i += 1
                    continue

            i += 1

        if not process.summary:
            process.summary = f"Standard process for {process.work_type} with {len(process.steps)} steps."
        if not process.keywords:
            process.keywords = _dedup_keep_order([process.work_type, *process.name.lower().split()])
        return process
