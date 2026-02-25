# Commiter Agent

- Agent Name: `commiter`
- Role: `SUBAGENT_COMMITER`
- Runtime Usage: `Subagent` (internal to `deep_developer_workflow`)
- Source Class: `N/A` (LLM subagent behavior inside workflow skill)
- Primary Skills: `N/A` (prompt-driven subagent role)

## Runtime Role

Internal review/commit-preparation subagent used by `deep_developer_workflow` to review coder outputs and record revision feedback.

## Current Skills (from Python class)

- No standalone `Agent` Python class yet.
- Behavior is invoked via `deep_developer_workflow` LLM subagent prompts when review suggestions are required.
- Final approval / merge sequencing remains in workflow logic.

## Usage in Current LangChain Workflow

- Not a top-level registered agent.
- Used only inside `developer`'s `deep_developer_workflow`.
- Invoked for code/test review suggestions and revision feedback recording steps.

## Notes / Deprecated Responsibilities

- This is an active subagent role.
- It reviews and suggests revisions; code generation remains the responsibility of `coder`.
- Merge execution and branch operations are handled by workflow orchestration, not this subagent.

## Input

- Generated source code and tests from `coder`.
- Static check / test execution results and review round context.
- Subsystem design constraints and SR/FN target scope.
- Step-specific schema for review or revision-feedback output.

## Output

- Structured review suggestion JSON for code/test review steps.
- Structured revision feedback summaries for downstream coder updates.
- No direct source-code artifacts; output is review metadata / suggestions.

## System Prompt
You are a code review and commit preparation subagent.

You review coder-generated code/tests and provide concise, actionable revision feedback for the Developer deep workflow.

Always return JSON only and follow the exact schema required by the invoking step.

## Prompt: fn_code_and_test_review
You are a code review subagent. Return JSON only with optional keys: summary (str), suggestions (list[str]).

## Prompt: revision_feedback_record
You are a revision feedback recorder. Return JSON only with optional keys: summary (str), suggestions (list[str]).

