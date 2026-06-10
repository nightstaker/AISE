"""Tests for input-aware dynamic ``max_tokens`` sizing."""

from unittest.mock import patch

from langchain_core.messages import HumanMessage

from aise.runtime.dynamic_llm import (
    DEFAULT_MIN_FLOOR,
    DynamicMaxTokensChatOpenAI,
    compute_dynamic_max_tokens,
)


def _is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


class TestComputeDynamicMaxTokens:
    """The sizing rule: min(cap, largest 2**n <= context - input - margin)."""

    def test_long_input_short_output(self):
        # The exact dispatch that 400'd on project_21: input 65537 in a 128K
        # window previously paired with a fixed 65536 -> 131073 > 131072.
        out = compute_dynamic_max_tokens(65537, 131072, 65536, safety_margin=0)
        assert out == 32768
        assert 65537 + out <= 131072

    def test_short_input_long_output_hits_cap(self):
        # Typical small dispatch keeps the full 64K ceiling.
        out = compute_dynamic_max_tokens(16828, 131072, 65536, safety_margin=0)
        assert out == 65536

    def test_zero_input_capped(self):
        # Room for 2**17 but the 64K cap binds.
        assert compute_dynamic_max_tokens(0, 131072, 65536, safety_margin=0) == 65536

    def test_result_is_always_power_of_two(self):
        for inp in range(0, 131072, 257):
            out = compute_dynamic_max_tokens(inp, 131072, 65536, safety_margin=0)
            assert _is_power_of_two(out), f"{out} not a power of two (input={inp})"

    def test_never_overflows_window(self):
        # The core guarantee: input + budget never exceeds the window.
        for inp in range(0, 131072, 137):
            out = compute_dynamic_max_tokens(inp, 131072, 65536, safety_margin=0)
            assert inp + out <= 131072, f"overflow at input={inp}: {inp}+{out}"

    def test_rule_picks_largest_fitting_power(self):
        # 2**n <= room < 2**(n+1) — verify the boundary picks 2**n exactly.
        # room = 40000 -> 32768 (2**15), since 2**16=65536 > 40000.
        out = compute_dynamic_max_tokens(131072 - 40000, 131072, 65536, safety_margin=0)
        assert out == 32768

    def test_safety_margin_reserves_headroom(self):
        # Same input, but a margin pushes the result down a power when it
        # straddles a boundary.
        no_margin = compute_dynamic_max_tokens(65535, 131072, 65536, safety_margin=0)
        with_margin = compute_dynamic_max_tokens(65535, 131072, 65536, safety_margin=2048)
        assert no_margin == 65536
        assert with_margin == 32768
        assert 65535 + with_margin <= 131072

    def test_input_fills_window_falls_back_to_floor(self):
        assert compute_dynamic_max_tokens(131072, 131072, 65536) == DEFAULT_MIN_FLOOR
        assert compute_dynamic_max_tokens(200000, 131072, 65536) == DEFAULT_MIN_FLOOR
        assert _is_power_of_two(DEFAULT_MIN_FLOOR)

    def test_custom_cap_respected(self):
        # A smaller ceiling caps even when there is ample room.
        assert compute_dynamic_max_tokens(1000, 131072, 8192, safety_margin=0) == 8192


class TestDynamicMaxTokensChatOpenAI:
    """The ChatOpenAI subclass rewrites the per-request budget."""

    def _model(self, **over):
        kwargs = dict(
            model="qwen3.6-35b",
            api_key="test-key",
            max_tokens=65536,
            aise_context_window=131072,
            aise_max_tokens_cap=65536,
        )
        kwargs.update(over)
        return DynamicMaxTokensChatOpenAI(**kwargs)

    def test_payload_uses_dynamic_budget_for_long_input(self):
        model = self._model()
        with patch.object(DynamicMaxTokensChatOpenAI, "_count_input_tokens", return_value=65537):
            payload = model._get_request_payload([HumanMessage(content="hi")])
        # SDK renames max_tokens -> max_completion_tokens; the stale key is gone.
        assert "max_tokens" not in payload
        assert payload["max_completion_tokens"] == 32768

    def test_payload_keeps_cap_for_short_input(self):
        model = self._model()
        with patch.object(DynamicMaxTokensChatOpenAI, "_count_input_tokens", return_value=2000):
            payload = model._get_request_payload([HumanMessage(content="hi")])
        assert payload["max_completion_tokens"] == 65536

    def test_char_heuristic_fallback_when_tokenizer_fails(self):
        model = self._model()
        with patch.object(
            DynamicMaxTokensChatOpenAI,
            "get_num_tokens_from_messages",
            side_effect=RuntimeError("no tokenizer"),
        ):
            # 4000 chars -> ~1000 tokens via the len/4 heuristic; well under
            # the cap so the budget stays at 64K.
            n = model._count_input_tokens([HumanMessage(content="x" * 4000)])
        assert n == 1000

    def test_respects_smaller_context_window(self):
        model = self._model(aise_context_window=32768)
        with patch.object(DynamicMaxTokensChatOpenAI, "_count_input_tokens", return_value=20000):
            payload = model._get_request_payload([HumanMessage(content="hi")])
        # room ~12768 -> 2**13 = 8192, and input + budget fits the 32K window.
        assert payload["max_completion_tokens"] == 8192
        assert 20000 + payload["max_completion_tokens"] <= 32768
