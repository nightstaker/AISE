"""Tests for the provider-pluggable LLM factory."""

from unittest.mock import MagicMock, patch

import pytest

from aise.config import ModelConfig
from aise.runtime import llm_factory
from aise.runtime.llm_factory import (
    _is_local_base_url,
    build_llm,
    register_provider,
)
from aise.runtime.runtime_config import LLMDefaults


class _TempProviders:
    """Context manager that temporarily replaces registered providers."""

    def __init__(self, **providers):
        self._new = providers
        self._saved: dict[str, object] = {}

    def __enter__(self):
        for name, builder in self._new.items():
            if name in llm_factory._REGISTRY:
                self._saved[name] = llm_factory._REGISTRY[name]
            llm_factory._REGISTRY[name] = builder
        return self

    def __exit__(self, *exc):
        for name in self._new:
            if name in self._saved:
                llm_factory._REGISTRY[name] = self._saved[name]
            else:
                llm_factory._REGISTRY.pop(name, None)


class TestBuildLLM:
    def test_dispatches_to_openai_by_default(self):
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        mock_builder = MagicMock(return_value="llm-instance")
        with _TempProviders(openai=mock_builder):
            result = build_llm(cfg)
        assert result == "llm-instance"
        mock_builder.assert_called_once()

    def test_dispatches_to_local_when_provider_is_local(self):
        cfg = ModelConfig(provider="local", model="llama3")
        mock_builder = MagicMock(return_value="local-llm")
        with _TempProviders(local=mock_builder):
            result = build_llm(cfg)
        assert result == "local-llm"
        mock_builder.assert_called_once()

    def test_dispatches_to_local_when_base_url_is_localhost(self):
        cfg = ModelConfig(provider="", base_url="http://localhost:11434/v1")
        mock_local = MagicMock(return_value="local-llm")
        mock_openai = MagicMock(return_value="should-not-call")
        with _TempProviders(local=mock_local, openai=mock_openai):
            build_llm(cfg)
        mock_local.assert_called_once()
        mock_openai.assert_not_called()

    def test_unknown_provider_falls_back_to_openai(self):
        cfg = ModelConfig(provider="some-unknown", model="x")
        mock_openai = MagicMock(return_value="fallback")
        with _TempProviders(openai=mock_openai):
            result = build_llm(cfg)
        assert result == "fallback"
        mock_openai.assert_called_once()

    def test_register_custom_provider(self):
        sentinel = object()
        with _TempProviders(test_provider=lambda cfg, defaults: sentinel):
            cfg = ModelConfig(provider="test_provider", model="x")
            assert build_llm(cfg) is sentinel

    def test_register_provider_lowercases_name(self):
        sentinel = object()
        register_provider("MIXEDCASE", lambda cfg, defaults: sentinel)
        try:
            assert build_llm(ModelConfig(provider="mixedcase", model="x")) is sentinel
        finally:
            llm_factory._REGISTRY.pop("mixedcase", None)


class TestIsLocalBaseUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8000",
            "http://127.0.0.1:1234/v1",
            "http://[::1]/v1",
        ],
    )
    def test_local_urls(self, url):
        assert _is_local_base_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.openai.com/v1",
            "",
            "not-a-url",
        ],
    )
    def test_non_local_urls(self, url):
        assert not _is_local_base_url(url)


class TestDefaults:
    def test_min_max_tokens_applied_via_openai_builder(self):
        from aise.runtime.llm_factory import _build_openai

        cfg = ModelConfig(provider="openai", model="gpt-4o", api_key="x", max_tokens=1024)
        defaults = LLMDefaults(min_max_tokens=8000)
        with patch("langchain_openai.ChatOpenAI") as mock_cls:
            _build_openai(cfg, defaults)
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["max_tokens"] == 8000
