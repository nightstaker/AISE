"""Server-side translation helper.

Jinja templates (``layout.html``, ``global_config.html``, …) need the same
translation table the client-side i18next uses, so admins see one
consistent language regardless of whether a string is server-rendered
or React-rendered.

The helper reads the JSON files in ``static/locales/<lng>/translation.json``
once per process (lazy-loaded, thread-safe, cache-invalidated on file
mtime so developers don't have to restart the server when editing the
JSON).

Public surface
--------------

``make_translator(get_lang)`` returns a callable
``t(key, default=None, **params) -> str`` ready to register as a Jinja
global. ``get_lang`` is a zero-arg callable (typically
``WebProjectService.get_ui_language``) that returns ``"zh"`` or ``"en"``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from ..utils.logging import get_logger

logger = get_logger(__name__)


def _locales_dir() -> Path:
    return Path(__file__).resolve().parent / "static" / "locales"


class _LocaleCache:
    """Memoized JSON load per language, invalidated by file mtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._mtime: dict[str, float] = {}

    def get(self, lang: str) -> dict[str, Any]:
        path = _locales_dir() / lang / "translation.json"
        if not path.is_file():
            return {}
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}
        with self._lock:
            if self._mtime.get(lang) == mtime and lang in self._data:
                return self._data[lang]
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as exc:
                logger.warning("Failed to load locale %s: %s", lang, exc)
                return self._data.get(lang, {})
            if isinstance(data, dict):
                self._data[lang] = data
                self._mtime[lang] = mtime
                return data
            return {}


_CACHE = _LocaleCache()


def _resolve(tree: dict[str, Any], key: str) -> Any:
    """Walk a dotted key through a nested dict."""
    node: Any = tree
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _interpolate(value: str, params: dict[str, Any]) -> str:
    """Replace ``{{name}}`` / ``{name}`` tokens — same syntax as i18next.

    Supports both the double-brace form (``{{n}}`` — i18next default)
    and single-brace form for convenience. Missing keys leave the token
    intact so misspellings are visible instead of silently consumed.
    """
    if not params:
        return value
    out = value
    for name, raw in params.items():
        token_double = "{{" + name + "}}"
        token_single = "{" + name + "}"
        out = out.replace(token_double, str(raw)).replace(token_single, str(raw))
    return out


def make_translator(get_lang: Callable[[], str]) -> Callable[..., str]:
    """Build a Jinja-friendly ``t(key, default=None, **params)`` helper."""

    def t(key: str, default: str | None = None, **params: Any) -> str:
        lang = (get_lang() or "zh").strip().lower()
        tree = _CACHE.get(lang)
        value = _resolve(tree, key)
        if value is None and lang != "en":
            value = _resolve(_CACHE.get("en"), key)
        if value is None:
            return default if default is not None else key
        if isinstance(value, str):
            return _interpolate(value, params)
        return str(value)

    return t
