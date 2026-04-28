"""Retry-prompt construction shared by dispatch tools."""

from __future__ import annotations

# Maximum number of context-augmented retries a single ``dispatch_task``
# will issue after an empty response or missing artifacts. One retry is
# enough in practice: if a fresh context-augmented attempt still fails,
# looping further usually burns tokens without recovering.
_MAX_DISPATCH_RETRIES = 1

# Text prepended to the task description on a context-augmented retry.
# Deliberately agent-, tool-, skill-, and file-neutral so it applies
# uniformly to every dispatch. ``{prev}`` is filled with a truncated
# verbatim copy of the previous response (or the literal ``(empty)`` if
# the previous attempt returned nothing). ``{task}`` is the original
# task description.
_RETRY_CONTEXT_TEMPLATE = (
    "[Retry context]\n"
    "A previous attempt at this task ended without producing the\n"
    "expected output. Its last message was:\n"
    "<<<\n"
    "{prev}\n"
    ">>>\n"
    "Continue the task. If the previous attempt described an intended\n"
    "action without performing it, perform it now.\n\n"
    "Original task:\n"
    "{task}"
)

# Max bytes of the previous response to echo into the retry prompt.
# Large responses would inflate the retry prompt without helping the
# model; most useful signal is in the final few hundred characters.
_RETRY_PREV_MAX_BYTES = 500


def _build_retry_prompt(original_task: str, previous_response: str) -> str:
    """Compose the context-augmented retry prompt for a dispatch."""
    prev = previous_response.strip()
    if not prev:
        echoed = "(empty)"
    elif len(prev) <= _RETRY_PREV_MAX_BYTES:
        echoed = prev
    else:
        echoed = prev[-_RETRY_PREV_MAX_BYTES:]
    return _RETRY_CONTEXT_TEMPLATE.format(prev=echoed, task=original_task)
