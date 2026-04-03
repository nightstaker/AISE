"""Plan Visualizer — renders ExecutionPlans as Mermaid or text for user review.

Provides multiple output formats for AI-generated execution plans:
1. Mermaid flowchart for docs/reports
2. Text table for terminal/chat display
3. Summary for quick confirmation prompts
"""

from __future__ import annotations

from .ai_planner import ExecutionPlan, PlanStep
from .process_registry import ProcessRegistry


class PlanVisualizer:
    """Render an ExecutionPlan in various human-readable formats."""

    def __init__(self, registry: ProcessRegistry | None = None) -> None:
        self.registry = registry

    def to_mermaid(self, plan: ExecutionPlan) -> str:
        """Render plan as a Mermaid flowchart.

        Example output:
            ```mermaid
            graph TD
                requirement_analysis["Requirement Analysis<br/>🧑 product_manager"]
                system_design["System Design<br/>🧑 architect"]
                requirement_analysis --> system_design
            ```
        """
        lines = ["graph TD"]
        step_ids = {s.process_id for s in plan.steps}

        for step in plan.steps:
            label = self._step_label(step)
            lines.append(f'    {step.process_id}["{label}"]')

        for step in plan.steps:
            for dep in step.depends_on_steps:
                if dep in step_ids:
                    lines.append(f"    {dep} --> {step.process_id}")

        return "\n".join(lines)

    def to_text_table(self, plan: ExecutionPlan) -> str:
        """Render plan as a text table for terminal display.

        Example:
            # AI Execution Plan: Build a REST API
            ┌────┬──────────────────────┬──────────────────┬──────────────┐
            │ #  │ Process              │ Agent            │ Depends On   │
            ├────┼──────────────────────┼──────────────────┼──────────────┤
            │ 1  │ requirement_analysis │ product_manager  │ -            │
            │ 2  │ system_design        │ architect        │ #1           │
            └────┴──────────────────────┴──────────────────┴──────────────┘
        """
        if not plan.steps:
            return f"Plan: {plan.goal}\n(empty plan — no steps)"

        ordered = plan.execution_order()
        step_index = {s.process_id: i + 1 for i, s in enumerate(ordered)}

        lines = [f"# AI Execution Plan: {plan.goal}"]
        lines.append(f"# Reasoning: {plan.reasoning}")
        lines.append("")

        # Column widths
        max_proc = max(len(s.process_id) for s in ordered)
        max_agent = max(len(s.agent) for s in ordered)
        w_proc = max(max_proc, 7)
        w_agent = max(max_agent, 5)

        header = f"{'#':>3}  {'Process':<{w_proc}}  {'Agent':<{w_agent}}  Dependencies"
        sep = f"{'─' * 3}  {'─' * w_proc}  {'─' * w_agent}  {'─' * 14}"
        lines.append(header)
        lines.append(sep)

        for step in ordered:
            idx = step_index[step.process_id]
            deps = ", ".join(f"#{step_index[d]}" for d in step.depends_on_steps if d in step_index) or "-"
            lines.append(f"{idx:>3}  {step.process_id:<{w_proc}}  {step.agent:<{w_agent}}  {deps}")

        lines.append("")
        lines.append(f"Total steps: {len(ordered)}")

        return "\n".join(lines)

    def to_summary(self, plan: ExecutionPlan) -> str:
        """Compact one-line summary for quick confirmation.

        Example: "4 steps: requirement_analysis → system_design → code_generation → test_automation"
        """
        if not plan.steps:
            return f"Plan: {plan.goal} (empty)"

        ordered = plan.execution_order()
        chain = " → ".join(s.process_id for s in ordered)
        return f"{len(ordered)} steps: {chain}"

    def to_confirmation_prompt(self, plan: ExecutionPlan) -> str:
        """Generate a user confirmation prompt showing the plan.

        Returns a formatted string asking the user to approve the plan.
        """
        lines = [
            "━━━ AI-Generated Execution Plan ━━━",
            f"Goal: {plan.goal}",
            f"Reasoning: {plan.reasoning}",
            "",
        ]

        ordered = plan.execution_order()
        for i, step in enumerate(ordered, 1):
            deps_str = ""
            if step.depends_on_steps:
                deps_str = f" (after: {', '.join(step.depends_on_steps)})"
            proc_info = ""
            if self.registry:
                proc = self.registry.get(step.process_id)
                if proc:
                    proc_info = f" — {proc.description}"

            lines.append(f"  {i}. [{step.agent}] {step.process_id}{proc_info}{deps_str}")
            if step.rationale:
                lines.append(f"     └─ {step.rationale}")

        lines.append("")
        lines.append(f"Total: {len(ordered)} steps")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _step_label(self, step: PlanStep) -> str:
        """Build a Mermaid node label for a step."""
        name = step.process_id.replace("_", " ").title()
        return f"{name}<br/>🧑 {step.agent}"
