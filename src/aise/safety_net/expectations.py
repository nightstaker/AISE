"""Pre-baked Layer-B expectation sets for the standard pipeline phases."""

from __future__ import annotations

from .types import ExpectedArtifact


def scaffolding_expectations() -> tuple[ExpectedArtifact, ...]:
    """The layer-B expectations the PM agent's SCAFFOLDING TASK claims
    to satisfy. Exposed as a free function so callers in
    ``web/app.py`` can wire it without duplicating the list.
    """
    return (
        ExpectedArtifact(path=".", kind="git_repo", description="project root initialized as git repo"),
        ExpectedArtifact(path=".gitignore", kind="file", non_empty=True, description="baseline .gitignore seeded"),
        ExpectedArtifact(path="docs", kind="dir"),
        ExpectedArtifact(path="src", kind="dir"),
        ExpectedArtifact(path="tests", kind="dir"),
        ExpectedArtifact(path="scripts", kind="dir"),
        ExpectedArtifact(path="config", kind="dir"),
        ExpectedArtifact(path="artifacts", kind="dir"),
        ExpectedArtifact(path="trace", kind="dir"),
        # Leftover-file guards: nothing scaffolds these files yet, so
        # if any are present they're carryover from a prior run on the
        # same project_id (e.g. a Phaser package.json + node_modules
        # that survived because the previous run wasn't fully reset).
        # Letting them survive into a new run with a different stack
        # produced project_7-tower's three-stacks-coexist failure
        # mode. Repair = delete.
        ExpectedArtifact(
            path="package.json", kind="must_not_exist", description="leftover package.json from prior run"
        ),
        ExpectedArtifact(
            path="package-lock.json", kind="must_not_exist", description="leftover npm lockfile from prior run"
        ),
        ExpectedArtifact(
            path="pnpm-lock.yaml", kind="must_not_exist", description="leftover pnpm lockfile from prior run"
        ),
        ExpectedArtifact(path="yarn.lock", kind="must_not_exist", description="leftover yarn lockfile from prior run"),
        ExpectedArtifact(path="tsconfig.json", kind="must_not_exist", description="leftover tsconfig from prior run"),
        ExpectedArtifact(
            path="vitest.config.ts", kind="must_not_exist", description="leftover vitest config from prior run"
        ),
        ExpectedArtifact(
            path="vite.config.ts", kind="must_not_exist", description="leftover vite config from prior run"
        ),
        ExpectedArtifact(
            path="node_modules", kind="must_not_exist", description="leftover node_modules from prior run"
        ),
        ExpectedArtifact(path="Cargo.toml", kind="must_not_exist", description="leftover Cargo.toml from prior run"),
        ExpectedArtifact(path="Cargo.lock", kind="must_not_exist", description="leftover Cargo.lock from prior run"),
        ExpectedArtifact(path="target", kind="must_not_exist", description="leftover Rust target/ from prior run"),
        ExpectedArtifact(path="go.mod", kind="must_not_exist", description="leftover go.mod from prior run"),
        ExpectedArtifact(path="go.sum", kind="must_not_exist", description="leftover go.sum from prior run"),
        ExpectedArtifact(path="vendor", kind="must_not_exist", description="leftover Go vendor/ from prior run"),
        ExpectedArtifact(path="pom.xml", kind="must_not_exist", description="leftover Maven pom.xml from prior run"),
        ExpectedArtifact(
            path="build.gradle.kts", kind="must_not_exist", description="leftover Gradle build from prior run"
        ),
        ExpectedArtifact(
            path="pyproject.toml",
            kind="must_not_exist",
            description="leftover pyproject.toml from prior run (architect re-creates if Python is the chosen stack)",
        ),
        ExpectedArtifact(
            path=".coverage", kind="must_not_exist", description="leftover coverage artifact from prior run"
        ),
    )


def architecture_expectations() -> tuple[ExpectedArtifact, ...]:
    """The layer-B expectations the architect agent's Phase-2 dispatch
    must satisfy. Currently:
    - docs/architecture.md exists and is non-empty
    - docs/stack_contract.json exists and is valid JSON

    Callers in ``project_session.py`` invoke ``run_post_step_check``
    with this list after the architect dispatch returns. Missing /
    malformed contract triggers an architect re-dispatch with the
    failure detail.
    """
    return (
        ExpectedArtifact(path="docs/architecture.md", kind="file", non_empty=True, description="architecture document"),
        ExpectedArtifact(
            path="docs/stack_contract.json",
            kind="stack_contract",
            non_empty=True,
            description="stack contract JSON with two-level subsystems[].components[] schema",
        ),
    )


def qa_expectations() -> tuple[ExpectedArtifact, ...]:
    """The layer-B expectations the qa_engineer agent's Phase-5
    dispatch must satisfy. Currently:
    - docs/qa_report.json exists and is valid JSON

    Callers in ``project_session.py`` invoke ``run_post_step_check``
    with this list after the QA dispatch returns. Missing /
    malformed report triggers a QA re-dispatch with the failure
    detail. Phase 6 reads the report verbatim — without this guard
    a flaky pytest run in Phase 6 would silently overwrite QA's
    real findings.
    """
    return (
        ExpectedArtifact(
            path="docs/qa_report.json", kind="json_file", non_empty=True, description="QA report JSON for Phase 6"
        ),
    )
