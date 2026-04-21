"""Regression guards for the frontend i18n translation resources.

Translations live in standard i18next JSON resource files under
``src/aise/web/static/locales/<lng>/translation.json`` (one folder per
language, one JSON per namespace). These tests validate the resource
files directly — no need to parse ``app.js``, no JS runtime needed.

They pin three things:

1. Every declared language has a resource file.
2. The ``zh`` and ``en`` files have identical key sets — a missing key
   on one side would make the UI fall through to i18next's fallback
   language and render mixed Chinese/English, which is the exact
   symptom that motivated this layer.
3. Specific keys that the orchestrator / PM emits at dispatch time
   (``stage.architecture``, ``stage.requirement``, etc.) are present.
   These reflect phase names observed in project_3-snake runs.

The companion ``resolveStageLabel`` helper in ``app.js`` layers a
suffix-stripper and humanize-fallback on top of i18next; that behavior
is exercised indirectly by the regex + humanize presence checks below.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import aise

STATIC_DIR = Path(aise.__file__).resolve().parent / "web" / "static"
LOCALES_DIR = STATIC_DIR / "locales"
APP_JS = STATIC_DIR / "app.js"

SUPPORTED_LANGS = ("zh", "en")

# Phase names the orchestrator / PM emits at dispatch time (observed on
# project_3-snake 2026-04-18 → 2026-04-19 plus the framework defaults
# declared in project_session.py). Extending this list should go hand
# in hand with extending both translation.json files.
REQUIRED_STAGES: tuple[str, ...] = (
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


def _flatten(obj: object, prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts into ``a.b.c`` dotted keys mapping to leaves."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            sub = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, sub))
    else:
        out[prefix] = obj  # type: ignore[assignment]
    return out


def _load_locale(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / lang / "translation.json"
    assert path.is_file(), f"missing i18next resource: {path}"
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


class TestLocaleResourceFiles:
    @pytest.mark.parametrize("lang", SUPPORTED_LANGS)
    def test_resource_file_exists_and_parses(self, lang: str) -> None:
        """Each declared language must have a parseable translation.json."""
        entries = _load_locale(lang)
        assert entries, f"{lang} translation.json parsed to empty dict"

    def test_zh_and_en_have_identical_key_sets(self) -> None:
        """Key parity between languages: a key missing on one side causes
        i18next to fall back across languages, producing the mixed
        Chinese/English rendering that motivated this whole layer.

        Both sides must be in lockstep."""
        zh = _load_locale("zh")
        en = _load_locale("en")
        only_in_zh = sorted(set(zh) - set(en))
        only_in_en = sorted(set(en) - set(zh))
        assert not only_in_zh, f"keys missing in en/translation.json: {only_in_zh}"
        assert not only_in_en, f"keys missing in zh/translation.json: {only_in_en}"

    @pytest.mark.parametrize("lang", SUPPORTED_LANGS)
    @pytest.mark.parametrize("stage", REQUIRED_STAGES)
    def test_required_stage_key_present(self, lang: str, stage: str) -> None:
        """Every phase name the orchestrator / PM emits must have a
        translation entry — otherwise the chip renders as a humanized
        fallback alongside fully-translated siblings, which reads as
        the same mixed-language problem."""
        entries = _load_locale(lang)
        key = f"stage.{stage}"
        assert key in entries, f"{lang}/translation.json missing {key}"
        assert entries[key].strip(), f"{lang}/translation.json has empty value for {key}"

    def test_interpolation_tokens_use_i18next_syntax(self) -> None:
        """i18next uses ``{{name}}`` for interpolation. Single-brace
        ``{name}`` tokens would render literally — a common regression
        when porting from ad-hoc templating."""
        for lang in SUPPORTED_LANGS:
            entries = _load_locale(lang)
            for key, value in entries.items():
                bad = re.findall(r"(?<!\{)\{(\w+)\}(?!\})", value)
                assert not bad, (
                    f"{lang}/{key} uses single-brace interpolation {{...}} instead of i18next's {{{{...}}}}: {value!r}"
                )


class TestI18nextBootstrap:
    """Pin the client-side integration with the i18next library itself.

    We still verify a couple of things against ``app.js`` by string
    search — these are lightweight and guard against accidentally
    rolling the integration back to an ad-hoc table."""

    def test_app_js_initializes_i18next_with_http_backend(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        # The integration uses i18next + i18next-http-backend; both
        # must be referenced so the bundler / bootstrap knows to wait
        # on them.
        assert "i18next" in body
        assert "i18nextHttpBackend" in body or "HttpBackend" in body
        # Resources are loaded from the static mount.
        assert "/static/locales/{{lng}}/{{ns}}.json" in body

    def test_app_js_waits_for_i18n_before_mount(self) -> None:
        """React mount must follow ``initI18n()`` so the first paint
        has translated text, not raw keys."""
        body = APP_JS.read_text(encoding="utf-8")
        assert "initI18n()" in body
        # The DOMContentLoaded handler must chain the setup calls after
        # the init promise resolves.
        assert re.search(r"initI18n\(\)\.(?:finally|then)\(", body), (
            "DOMContentLoaded handler must await initI18n() before mounting"
        )

    def test_app_js_has_no_inline_translations_table(self) -> None:
        """Regression: the old ``const TRANSLATIONS = { zh: {...} }``
        inline table must be gone. All translations live in the JSON
        resource files under locales/."""
        body = APP_JS.read_text(encoding="utf-8")
        assert "const TRANSLATIONS" not in body, (
            "inline TRANSLATIONS table reintroduced; translations must live in locales/<lng>/translation.json only"
        )


class TestStageLabelResolverHelpers:
    """The ``resolveStageLabel`` helper in app.js layers two extra
    strategies on top of i18next: a counter-suffix stripper (so
    ``implementation_layer1`` → ``Implementation #1``) and a humanize
    fallback (so an unknown id renders as Title Case English instead of
    raw snake_case)."""

    @pytest.fixture(scope="class")
    def suffix_pattern(self) -> re.Pattern[str]:
        body = APP_JS.read_text(encoding="utf-8")
        m = re.search(r"var STAGE_SUFFIX_RE = (/\^.+?\$/);", body)
        assert m, "STAGE_SUFFIX_RE declaration not found in app.js"
        js_re = m.group(1)
        return re.compile(js_re[1:-1])

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
        suffix_pattern: re.Pattern[str],
        stage: str,
        expected_base: str,
        expected_counter: str,
    ) -> None:
        m = suffix_pattern.match(stage)
        assert m, f"pattern failed to match {stage!r}"
        assert m.group(1) == expected_base
        assert m.group(2) == expected_counter

    @pytest.mark.parametrize(
        "stage",
        [
            "architecture",
            "implementation",
            "main_entry",
            "qa_testing",
            "step_architecture_design",
        ],
    )
    def test_non_suffixed_stages_do_not_match(
        self,
        suffix_pattern: re.Pattern[str],
        stage: str,
    ) -> None:
        m = suffix_pattern.match(stage)
        assert not m, f"pattern wrongly matched {stage!r} — would strip valid stage id"

    def test_resolver_uses_i18next_exists(self) -> None:
        """The resolver must probe i18next via its public ``exists``
        API, not via a string-equality trick against the return value
        of ``t()``."""
        body = APP_JS.read_text(encoding="utf-8")
        assert "i18next.exists" in body

    def test_chip_strip_uses_resolveChipLabel_not_resolveStageLabel(self) -> None:
        """The chip strip must call ``resolveChipLabel`` so multi-layer
        phases render as one chip without a ``#N`` counter. An expanded
        log entry still calls ``resolveStageLabel`` to show the raw
        per-layer detail.

        Regression guard for the pathology where
        ``implementation_layer1`` / ``implementation_layer2`` each
        rendered as their own chip, flooding the stage strip."""
        body = APP_JS.read_text(encoding="utf-8")
        # The chip .map() block references resolveChipLabel.
        chip_block_start = body.find("run-stages-flow")
        assert chip_block_start > 0
        chip_block_end = body.find("run-log-empty", chip_block_start)
        assert chip_block_end > chip_block_start
        chip_block = body[chip_block_start:chip_block_end]
        assert "resolveChipLabel" in chip_block, (
            "chip strip must use resolveChipLabel; otherwise per-layer entries show with '#N' suffixes"
        )
        # And resolveStageLabel must still exist for the log-entry
        # stage rows (expanded per-event detail).
        assert "resolveStageLabel" in body

    def test_normalize_stage_id_strips_suffix(self) -> None:
        """``normalizeStageId`` is the function the chip accumulator
        uses to dedupe. It must strip the same counter suffix that
        ``STAGE_SUFFIX_RE`` recognizes, returning the base phase id."""
        body = APP_JS.read_text(encoding="utf-8")
        assert "function normalizeStageId(" in body, "normalizeStageId helper missing; chip collapse depends on it"
        # The normalized id must be used in the stage accumulator — the
        # chip list should be built from normalized ids, not raw ones.
        acc_match = re.search(r"stages\.push\(curNormalizedStage\)", body)
        assert acc_match, (
            "stage accumulator must push curNormalizedStage, not the raw "
            "ev.stage — otherwise implementation_layer1 and "
            "implementation_layer2 become two separate chips"
        )

    def test_filter_uses_normalized_stage(self) -> None:
        """Clicking the ``implementation`` chip must filter events
        across every ``implementation_layer*`` variant, not just the
        one raw id. The visibleStages array is therefore derived from
        the NORMALIZED stage, not the raw one."""
        body = APP_JS.read_text(encoding="utf-8")
        assert re.search(
            r"visibleStages\s*=\s*taskLog\s*\.\s*map\(\s*\(_,\s*i\)\s*=>\s*evStagesNormalized\[i\]\)",
            body,
        ), "visibleStages must be built from evStagesNormalized[i]"

    def test_resolver_has_humanize_fallback(self) -> None:
        """The final branch of ``resolveStageLabel`` must humanize the
        unknown id — pins the fix for the 2026-04-19 screenshot where
        ``implementation_layer1`` rendered verbatim."""
        body = APP_JS.read_text(encoding="utf-8")
        start = body.find("function resolveStageLabel(stage)")
        assert start >= 0, "resolveStageLabel not found"
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
        assert end > start
        fn_src = body[start : end + 1]
        assert "return humanizeStageId(stage)" in fn_src
