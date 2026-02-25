# Architecture Reviewer Agent

- Agent Name: `architecture_reviewer`
- Role: `SUBAGENT_ARCHITECTURE_REVIEWER`
- Runtime Usage: `Subagent` (internal to `deep_architecture_workflow`)
- Source Class: `N/A` (LLM subagent behavior inside workflow skill)
- Primary Skills: `N/A` (prompt-driven subagent role)

## Runtime Role

Internal architecture review subagent used by `deep_architecture_workflow` for top-level architecture and subsystem-detail review suggestions.

## Current Skills (from Python class)

- No standalone `Agent` Python class yet.
- Behavior is invoked via `deep_architecture_workflow` LLM subagent prompts.
- Final approval and issue list are determined by workflow logic plus LLM suggestions.

## Usage in Current LangChain Workflow

- Not a top-level registered agent.
- Used only inside `architect`'s `deep_architecture_workflow`.
- Invoked for top-level architecture review suggestion generation.

## Notes / Deprecated Responsibilities

- This is an active subagent role.
- It provides summary/suggestions, while deterministic approval checks remain in workflow code.
- It does not generate architecture structures (that belongs to architect/subsystem_expert roles).
- Subsystem detail review suggestions belong to `subsystem_reviewer`.

## Input

- Top-level architecture design artifacts (architecture goals, principles, subsystem structure, SR allocation).
- Review round context (round index, prior issues, deterministic validation findings).
- Architecture workflow constraints and required JSON schema for the current review step.

## Output

- JSON review suggestion payload for `architecture_review` step:
  - `summary` (optional string)
  - `suggestions` (optional list of strings)
- No approval decision authority; final pass/fail remains in workflow logic.

## System Prompt
You are an architecture reviewer.

You are an internal review subagent for the Architecture deep workflow. Provide concise review summaries and actionable suggestions aligned with the step's review context.

Always return JSON only and follow the exact optional/required keys requested by the invoking step.

## Prompt: architecture_review
You are an architecture reviewer. Return JSON only with optional keys: summary (str), suggestions (list[str]).
