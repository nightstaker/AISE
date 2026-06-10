"""Input-aware dynamic ``max_tokens`` for OpenAI-compatible chat models.

AI tasks are lopsided: a short prompt often wants a long completion
("write the whole file"), while a long prompt usually wants a short one
("review this and reply REVISE"). Binding a single fixed ``max_tokens``
on the client — the historical behaviour, a flat 64K floor — is wrong at
both ends:

* On long-input dispatches it **overflows the context window**. Observed
  on project_21-calculator (2026-06-10): a developer fanout accumulated
  ~65,537 input tokens across its ReAct loop, the client still requested
  65,536 output tokens, and the server rejected the call —
  ``131073 > 131072`` — with a 400. Six dispatches died this way.
* On short-input dispatches a fixed small ceiling silently truncates.

The fix is to size ``max_tokens`` from the *actual* input length on every
call, leaving the rest of the window for output, capped at 64K.

Sizing rule (``compute_dynamic_max_tokens``):

    room        = context_window - input_tokens - safety_margin
    max_tokens  = min( cap , largest power of two <= room )

so ``max_tokens`` is always a power of two and ``input + max_tokens``
never exceeds the window. ``cap`` defaults to 64K (2**16); the power-of-two
flooring is what guarantees headroom — at worst it hands back just under
half of ``room``, which absorbs any drift between the client tokenizer and
the server's count.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

# 64K — the ceiling. A reasoning model (qwen3.x) spends part of this on a
# hidden <think> block, so the ceiling stays generous for short-input,
# large-artifact dispatches (see runtime_config.DEFAULT_MIN_MAX_TOKENS).
DEFAULT_MAX_TOKENS_CAP = 65536
# Smallest budget we will ever request. A power of two so the result of
# ``compute_dynamic_max_tokens`` is always 2**n, even on the degenerate
# "input already fills the window" path.
DEFAULT_MIN_FLOOR = 256
# Reserved headroom subtracted before sizing, to cover the gap between the
# client-side token count and the server's stricter count (the original
# overflow was an exact off-by-one). Scales with input so it stays
# meaningful at large prompts; see ``_safety_margin_for``.
MIN_SAFETY_MARGIN = 1024


def _largest_power_of_two_at_most(value: int) -> int:
    """Largest ``2**n`` with ``2**n <= value`` (value >= 1)."""
    return 1 << (value.bit_length() - 1)


def compute_dynamic_max_tokens(
    input_tokens: int,
    context_window: int,
    cap: int = DEFAULT_MAX_TOKENS_CAP,
    *,
    safety_margin: int = 0,
    min_floor: int = DEFAULT_MIN_FLOOR,
) -> int:
    """Size ``max_tokens`` from the input length.

    Returns ``min(cap, 2**floor(log2(room)))`` where
    ``room = context_window - input_tokens - safety_margin``. The result is
    always a power of two, and whenever ``room >= 1`` it satisfies
    ``input_tokens + safety_margin + result <= context_window`` — i.e. it
    never overflows the window. When the input alone (plus margin) already
    fills the window there is no non-overflowing budget; we return
    ``min_floor`` so the request carries a truthful tiny budget and the
    server rejects it with a clear error instead of us guessing.
    """
    room = context_window - input_tokens - safety_margin
    if room < 1:
        return min_floor
    return min(cap, _largest_power_of_two_at_most(room))


def _safety_margin_for(input_tokens: int) -> int:
    """Headroom reserve: at least ``MIN_SAFETY_MARGIN``, ~3% of input.

    A flat reserve is too thin once the prompt is tens of thousands of
    tokens (where the client/server tokenizer gap is largest), so it grows
    with the input."""
    return max(MIN_SAFETY_MARGIN, input_tokens // 32)


class DynamicMaxTokensChatOpenAI(ChatOpenAI):
    """``ChatOpenAI`` that recomputes ``max_tokens`` per request.

    Every chat call in ``langchain_openai`` (sync/async, streaming or not)
    funnels through ``_get_request_payload``; overriding it once covers all
    four entry points. We measure the outgoing messages, size the budget
    with :func:`compute_dynamic_max_tokens`, and overwrite whatever fixed
    ceiling the payload carried (``max_completion_tokens`` after the SDK's
    own rename of ``max_tokens``).
    """

    # Declared as pydantic fields so they survive model construction.
    aise_context_window: int = 131072
    aise_max_tokens_cap: int = DEFAULT_MAX_TOKENS_CAP

    def _count_input_tokens(self, messages: Sequence[BaseMessage]) -> int:
        """Token count of the outgoing messages, with a char heuristic
        fallback if the tokenizer is unavailable for this model."""
        try:
            return self.get_num_tokens_from_messages(list(messages))
        except Exception:
            # ~4 chars/token over textual content; deliberately rough — the
            # power-of-two flooring absorbs the imprecision.
            chars = 0
            for m in messages:
                content = getattr(m, "content", "")
                if isinstance(content, str):
                    chars += len(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            chars += len(str(part.get("text", "")))
            return chars // 4

    def _resolve_dynamic_max_tokens(self, input_: Any) -> int | None:
        """Dynamic budget for this input, or ``None`` if messages can't be
        recovered (then the static payload value is left untouched)."""
        try:
            messages = self._convert_input(input_).to_messages()
        except Exception:
            return None
        input_tokens = self._count_input_tokens(messages)
        return compute_dynamic_max_tokens(
            input_tokens,
            self.aise_context_window,
            self.aise_max_tokens_cap,
            safety_margin=_safety_margin_for(input_tokens),
        )

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        dynamic = self._resolve_dynamic_max_tokens(input_)
        if dynamic is not None:
            # ChatOpenAI renamed max_tokens -> max_completion_tokens upstream;
            # drop any stale key and set the one the API actually reads.
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = dynamic
        return payload
