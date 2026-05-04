"""Tests for c5: dispatch.py 3-retry + real acceptance check.

The full ``aise.tools`` package has a pre-existing circular import in
the working tree (project_session.py imports from aise.tools at module
level, while aise.tools.context.py transitively pulls in project_session).
That is unrelated to c5 and not in scope. To still exercise c5's logic
without depending on the import working, this test loads
``aise.tools.retry`` and ``aise.tools.dispatch`` via importlib.spec
directly, bypassing the package ``__init__``.

End-to-end behavior of ``dispatch_task`` (the status="incomplete" path
when expected_artifacts remain missing after 3 retries) is covered by
the c14 integration tests.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RETRY = _load_module(
    "_c5_retry", Path("src/aise/tools/retry.py").resolve()
)


class TestRetryConstants:
    def test_max_retries_is_three(self):
        assert _RETRY._MAX_DISPATCH_RETRIES == 3, "c5 bumped retries from 1 to 3"


class TestBuildRetryPrompt:
    def test_includes_previous_response(self):
        out = _RETRY._build_retry_prompt("write code", "I tried but failed")
        assert "Original task:" in out
        assert "write code" in out
        assert "I tried but failed" in out

    def test_truncates_long_previous(self):
        long_prev = "x" * 5000
        out = _RETRY._build_retry_prompt("task", long_prev)
        assert len(out) < 2000

    def test_empty_previous_marked(self):
        out = _RETRY._build_retry_prompt("task", "")
        assert "(empty)" in out

    def test_template_is_role_neutral(self):
        """The retry template must not mention any specific agent role,
        skill, or filename — it must apply uniformly to every dispatch."""
        out = _RETRY._build_retry_prompt("X", "Y")
        for forbidden in (
            "developer",
            "architect",
            "product_manager",
            "qa_engineer",
            "skeleton",
            "scenario",
            ".cs",
            ".py",
        ):
            assert forbidden not in out


class TestDispatchPyChanged:
    """Verify the c5 patches landed in dispatch.py source.

    Since we can't import the full module due to the circular import,
    we sanity-check the source file contains the new control flow.
    """

    def test_status_incomplete_branch_present(self):
        src = Path("src/aise/tools/dispatch.py").read_text(encoding="utf-8")
        assert '"completed" if not final_shortfalls else "incomplete"' in src
        assert "final_shortfalls = _artifact_shortfalls" in src

    def test_parallel_aggregator_counts_incomplete(self):
        src = Path("src/aise/tools/dispatch.py").read_text(encoding="utf-8")
        assert 'incomplete = sum(1 for r in results if r.get("status") == "incomplete")' in src
        assert '"incomplete": incomplete,' in src
