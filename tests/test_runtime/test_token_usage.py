"""Tests for LLM token-usage accounting.

Covers three layers:

1. ``_extract_token_counts`` — normalizes provider-specific shapes
   (OpenAI ``prompt_tokens``/``completion_tokens`` vs Anthropic /
   LangChain ``input_tokens``/``output_tokens`` vs ``usage_metadata``
   on the message) into a single ``{input,output,total}`` dict.

2. ``TraceLLMCallback.on_llm_end`` — accumulates per-call counts into
   ``trace_record["token_usage"]`` and forwards each call to the
   ``on_token_usage`` callback.

3. ``AgentRuntime.handle_message`` — plumbs ``on_token_usage`` through
   to the ``TraceLLMCallback`` so callers see live token counts as the
   LLM round-trips fire.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from aise.runtime.agent_runtime import AgentRuntime
from aise.runtime.trace_callback import TraceLLMCallback, _extract_token_counts

SAMPLE_AGENT_MD = """\
---
name: TokenTestAgent
description: Token usage agent
version: 1.0.0
---

# System Prompt

You are a test agent.
"""


@pytest.fixture
def agent_md_file(tmp_path: Path) -> Path:
    f = tmp_path / "agent.md"
    f.write_text(SAMPLE_AGENT_MD)
    return f


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def mock_create_deep_agent():
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": [AIMessage(content="ok")]}
    with patch("aise.runtime.agent_runtime.create_deep_agent", return_value=mock_agent) as mock_factory:
        yield mock_factory, mock_agent


def _make_llm_result(usage: dict | None = None, usage_metadata: dict | None = None) -> LLMResult:
    msg = AIMessage(content="hi")
    if usage_metadata is not None:
        msg.usage_metadata = usage_metadata
    gen = ChatGeneration(message=msg, text="hi")
    llm_output = {"token_usage": usage} if usage is not None else None
    return LLMResult(generations=[[gen]], llm_output=llm_output)


class TestExtractTokenCounts:
    def test_openai_shape(self):
        result = _make_llm_result(usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17})
        counts = _extract_token_counts(result)
        assert counts == {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}

    def test_anthropic_shape(self):
        result = _make_llm_result(usage={"input_tokens": 30, "output_tokens": 8, "total_tokens": 38})
        counts = _extract_token_counts(result)
        assert counts == {"input_tokens": 30, "output_tokens": 8, "total_tokens": 38}

    def test_falls_back_to_usage_metadata_on_message(self):
        # No llm_output, but the message carries usage_metadata.
        result = _make_llm_result(
            usage=None,
            usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
        )
        counts = _extract_token_counts(result)
        assert counts == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}

    def test_total_synthesized_when_missing(self):
        result = _make_llm_result(usage={"prompt_tokens": 10, "completion_tokens": 3})
        counts = _extract_token_counts(result)
        # No total_tokens reported → input+output
        assert counts == {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}

    def test_zero_when_unavailable(self):
        result = _make_llm_result(usage=None)
        counts = _extract_token_counts(result)
        assert counts == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class TestTraceLLMCallbackTokenUsage:
    def _drive(self, callback: TraceLLMCallback, result: LLMResult) -> None:
        import uuid

        run_id = uuid.uuid4()
        callback.on_chat_model_start(
            serialized={},
            messages=[[]],
            run_id=run_id,
        )
        callback.on_llm_end(result, run_id=run_id)

    def test_accumulates_in_trace_record(self):
        record: dict = {}
        cb = TraceLLMCallback(trace_record=record, trace_path=None, lock=threading.Lock())
        self._drive(cb, _make_llm_result(usage={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}))
        self._drive(cb, _make_llm_result(usage={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}))

        assert record["token_usage"] == {
            "input_tokens": 8,
            "output_tokens": 5,
            "total_tokens": 13,
            "llm_calls": 2,
        }

    def test_forwards_to_on_token_usage(self):
        record: dict = {}
        captured: list[dict] = []
        cb = TraceLLMCallback(
            trace_record=record,
            trace_path=None,
            lock=threading.Lock(),
            on_token_usage=captured.append,
        )
        self._drive(cb, _make_llm_result(usage={"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}))
        self._drive(cb, _make_llm_result(usage={"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17}))

        assert captured == [
            {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
            {"input_tokens": 11, "output_tokens": 6, "total_tokens": 17},
        ]

    def test_no_callback_fired_when_usage_empty(self):
        captured: list[dict] = []
        cb = TraceLLMCallback(
            trace_record={},
            trace_path=None,
            lock=threading.Lock(),
            on_token_usage=captured.append,
        )
        self._drive(cb, _make_llm_result(usage=None))
        # No usage anywhere → callback must NOT fire (otherwise the
        # WorkflowRun's llm_call_count would be inflated by no-op rounds).
        assert captured == []


class TestAgentRuntimeHandleMessageTokenUsage:
    def test_on_token_usage_invoked_for_each_round_trip(self, agent_md_file, skills_dir, mock_create_deep_agent):
        _, mock_agent = mock_create_deep_agent

        def _simulate_two_calls(state, config=None):
            callbacks = (config or {}).get("callbacks") or []
            for cb in callbacks:
                self._drive_two_llm_calls(cb)
            return {"messages": [AIMessage(content="done")]}

        mock_agent.invoke.side_effect = _simulate_two_calls

        runtime = AgentRuntime(
            agent_md=agent_md_file,
            skills_dir=skills_dir,
            model="openai:gpt-4o",
        )
        runtime.evoke()
        captured: list[dict] = []
        runtime.handle_message("hi", on_token_usage=captured.append)

        assert captured == [
            {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
            {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
        ]

    @staticmethod
    def _drive_two_llm_calls(cb: TraceLLMCallback) -> None:
        import uuid

        for usage in (
            {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        ):
            run_id = uuid.uuid4()
            cb.on_chat_model_start(serialized={}, messages=[[]], run_id=run_id)
            cb.on_llm_end(_make_llm_result(usage=usage), run_id=run_id)
