"""Regression guards for the frontend stage-label resolver.

The React frontend in ``src/aise/web/static/app.js`` routes stage names
through a ``resolveStageLabel`` helper. A screenshot on 2026-04-19
showed the task-detail chips rendering as ``需求分析 → architecture
→ implementation_layer1`` — mixed Chinese + raw English IDs — because:

1. ``stage.architecture`` was missing from the translation table.
2. The suffix matcher only handled ``_cycle_N``, not ``_layer1`` /
   ``_part_2`` / ``_iter3`` etc.
3. The fallback returned the raw snake_case ID instead of a
   human-readable label.

These tests pin the three fixes so a future edit can't reintroduce
any of them.

Because the resolver is JavaScript, we test it textually — grepping
``app.js`` for the required translation keys and running Python
regex against the published suffix pattern. That's enough to pin
the contract; a JS-level unit test would require a JS runtime the
repo does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import aise

APP_JS = Path(aise.__file__).resolve().parent / "web" / "static" / "app.js"


def _load_app_js() -> str:
    assert APP_JS.is_file(), f"missing fixture: {APP_JS}"
    return APP_JS.read_text(encoding="utf-8")


class TestStageTranslationCoverage:
    """Every phase name the orchestrator / PM emits at dispatch time
    must have a translation entry in BOTH the ``zh`` and ``en``
    sections of the ``TRANSLATIONS`` table.

    This list reflects phase names observed in production runs on
    project_3-snake (2026-04-18 → 2026-04-19) plus the
    orchestrator-framework defaults. New phase names added in the
    future should extend both the table and this test.
    """

    REQUIRED_STAGES = (
        # Orchestrator framework phases (project_session.py).
        "requirement",
        "requirements",
        "architecture",
        "design",
        "implementation",
        "main_entry",
        "testing",
        "verification",
        "qa_testing",
        "delivery",
        "execution",
    )

    @pytest.mark.parametrize("stage_id", REQUIRED_STAGES)
    def test_key_present_in_zh_table(self, stage_id: str) -> None:
        body = _load_app_js()
        key = f'"stage.{stage_id}"'
        # The zh table appears before the en table in the source, so
        # finding the key anywhere implies at least one language has
        # it — stricter assertion below pins both.
        assert key in body, f"translation key missing: stage.{stage_id}"

    @pytest.mark.parametrize("stage_id", REQUIRED_STAGES)
    def test_key_present_in_both_tables(self, stage_id: str) -> None:
        body = _load_app_js()
        key = f'"stage.{stage_id}"'
        # Both tables must have the key, so the occurrence count is 2
        # (once in zh, once in en). A count of 1 means one table is
        # missing the key and the frontend would fall back across
        # languages for this stage.
        assert body.count(key) == 2, (
            f"stage.{stage_id} must appear in BOTH zh and en tables (found {body.count(key)} occurrences)"
        )


class TestStageSuffixPattern:
    """The ``STAGE_SUFFIX_RE`` regex strips a trailing counter suffix
    so labels like ``implementation_layer1`` resolve to "开发实现 #1"
    / "Implementation #1" instead of being emitted verbatim.

    The frontend regex is authored in JS; we extract it from app.js
    and exercise it with Python's ``re`` (compatible syntax for the
    patterns in use) so this test fails loudly if the pattern is
    narrowed in a future edit."""

    @pytest.fixture(scope="class")
    def pattern(self) -> re.Pattern[str]:
        body = _load_app_js()
        m = re.search(r"var STAGE_SUFFIX_RE = (/\^.+?\$/);", body)
        assert m, "STAGE_SUFFIX_RE declaration not found in app.js"
        js_re = m.group(1)
        # Strip the JS delimiter ``/.../`` — what's inside is valid
        # Python regex syntax for this pattern.
        py_src = js_re[1:-1]
        return re.compile(py_src)

    @pytest.mark.parametrize(
        "stage,expected_base,expected_counter",
        [
            ("implementation_layer1", "implementation", "1"),
            ("implementation_layer_2", "implementation", "2"),
            ("implementation_cycle_3", "implementation", "3"),
            ("design_part_2", "design", "2"),
            ("architecture_iter4", "architecture", "4"),
            ("architecture_iteration_5", "architecture", "5"),
            ("testing_round_1", "testing", "1"),
            ("delivery_v2", "delivery", "2"),
            ("qa_testing_stage_3", "qa_testing", "3"),
            ("requirement_step_1", "requirement", "1"),
        ],
    )
    def test_suffix_stripped_correctly(
        self,
        pattern: re.Pattern[str],
        stage: str,
        expected_base: str,
        expected_counter: str,
    ) -> None:
        m = pattern.match(stage)
        assert m, f"pattern failed to match {stage!r}"
        assert m.group(1) == expected_base
        assert m.group(2) == expected_counter

    @pytest.mark.parametrize(
        "stage",
        [
            "architecture",  # no suffix → must NOT match
            "implementation",  # no suffix
            "main_entry",  # trailing token is not a counter suffix
            "qa_testing",  # trailing token is not a counter suffix
            "step_architecture_design",  # PM step id, no trailing counter
        ],
    )
    def test_non_suffixed_stages_do_not_match(
        self,
        pattern: re.Pattern[str],
        stage: str,
    ) -> None:
        m = pattern.match(stage)
        assert not m, f"pattern wrongly matched {stage!r} — would strip valid stage id"


class TestHumanizeFallbackPresent:
    """When a stage id has no translation and no counter suffix the
    resolver must fall back to a humanized Title Case label, not to
    the raw snake_case id. Pinned by grepping for the helper and the
    call site that uses it."""

    def test_humanize_helper_defined(self) -> None:
        body = _load_app_js()
        assert "function humanizeStageId" in body

    def test_resolver_falls_back_to_humanized_form(self) -> None:
        """The unknown-stage fallback must call ``humanizeStageId`` —
        pinning this prevents a future refactor from reinstating the
        old ``return stage`` behavior that caused ``implementation_layer1``
        to render verbatim among Chinese labels.

        We locate the fallback by finding the ``resolveStageLabel``
        declaration and asserting the body (up to the first balanced
        closing brace at column 0 — the function's closing brace)
        contains a ``return humanizeStageId(`` call.
        """
        body = _load_app_js()
        start = body.find("function resolveStageLabel(stage)")
        assert start >= 0, "resolveStageLabel not found"
        # Walk forward until the function's closing ``}`` by tracking
        # brace depth. This is robust against inner ``if {}`` blocks.
        depth = 0
        end = -1
        in_fn = False
        for i in range(start, len(body)):
            ch = body[i]
            if ch == "{":
                depth += 1
                in_fn = True
            elif ch == "}":
                depth -= 1
                if in_fn and depth == 0:
                    end = i
                    break
        assert end > start, "could not locate end of resolveStageLabel"
        fn_src = body[start : end + 1]
        assert "return humanizeStageId(stage)" in fn_src, (
            "resolveStageLabel is missing the humanized-fallback branch — unknown stage ids must not be returned raw"
        )
