"""Tests for policy_backend — path normalization + write-overwrite wrapper.

Every patched method (write, read, edit, ls_info, glob_info, grep_raw)
is tested to ensure:
1. Correct function signature (matches original FilesystemBackend)
2. Path normalization works (absolute host paths → virtual paths)
3. Normal operation is unbroken
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from aise.runtime.policy_backend import make_policy_backend


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def backend(project_root):
    return make_policy_backend(project_root)


# -- Signature checks: every wrapper must match the original ---------------


class TestSignatures:
    """Verify wrapper signatures match FilesystemBackend originals."""

    def test_signatures_match(self, backend):
        from deepagents.backends import FilesystemBackend

        methods = ["write", "read", "edit", "ls_info", "glob_info", "grep_raw"]
        for name in methods:
            orig_sig = inspect.signature(getattr(FilesystemBackend, name))
            wrap_sig = inspect.signature(getattr(backend, name))
            orig_params = [(n, p.default) for n, p in orig_sig.parameters.items() if n != "self"]
            wrap_params = [(n, p.default) for n, p in wrap_sig.parameters.items()]
            # Same number of params
            assert len(orig_params) == len(wrap_params), (
                f"{name}: param count mismatch: orig={len(orig_params)} wrap={len(wrap_params)}"
            )
            # Same param names and defaults
            for (on, od), (wn, wd) in zip(orig_params, wrap_params):
                assert on == wn, f"{name}: param name mismatch: {on} vs {wn}"
                # Both required or both have same default
                if od is inspect.Parameter.empty:
                    assert wd is inspect.Parameter.empty, f"{name}.{on}: should be required but has default={wd!r}"
                else:
                    assert wd == od, f"{name}.{on}: default mismatch: orig={od!r} wrap={wd!r}"


# -- Write: overwrite support + path normalization -------------------------


class TestWrite:
    def test_write_creates_file(self, backend, project_root):
        result = backend.write("/src/main.py", "print('hello')")
        assert result.error is None
        assert (project_root / "src" / "main.py").read_text() == "print('hello')"

    def test_write_overwrites_existing(self, backend, project_root):
        """Writing to an existing file overwrites it."""
        r1 = backend.write("/src/main.py", "v1")
        assert r1.error is None
        r2 = backend.write("/src/main.py", "v2")
        assert r2.error is None
        assert (project_root / "src" / "main.py").read_text() == "v2"

    def test_write_allows_different_paths(self, backend, project_root):
        """Different files can each be written once."""
        r1 = backend.write("/src/a.py", "a")
        r2 = backend.write("/src/b.py", "b")
        assert r1.error is None
        assert r2.error is None

    def test_write_rejects_identical_content(self, backend, project_root):
        """Writing the same content to an existing file returns an error."""
        backend.write("/src/main.py", "same")
        r = backend.write("/src/main.py", "same")
        assert r.error is not None
        assert "identical content" in r.error

    def test_write_allows_different_content(self, backend, project_root):
        """Writing different content to an existing file succeeds."""
        backend.write("/src/main.py", "v1")
        r = backend.write("/src/main.py", "v2")
        assert r.error is None
        assert (project_root / "src" / "main.py").read_text() == "v2"

    def test_write_normalizes_absolute_host_path(self, backend, project_root):
        # Simulate LLM using absolute AISE repo path
        import aise

        aise_root = str(Path(aise.__file__).resolve().parent.parent.parent)
        result = backend.write(f"{aise_root}/src/test.py", "x=1")
        assert result.error is None
        assert (project_root / "src" / "test.py").read_text() == "x=1"


# -- Read ------------------------------------------------------------------


class TestRead:
    def test_read_returns_content(self, backend, project_root):
        backend.write("/src/main.py", "line1\nline2")
        content = backend.read("/src/main.py")
        assert "line1" in content
        assert "line2" in content

    def test_read_with_offset_limit(self, backend):
        backend.write("/src/big.py", "\n".join(f"line{i}" for i in range(100)))
        content = backend.read("/src/big.py", offset=10, limit=5)
        assert "line10" in content
        assert "line0\n" not in content


# -- Edit ------------------------------------------------------------------


class TestEdit:
    def test_edit_replaces_string(self, backend, project_root):
        backend.write("/src/calc.py", "def add(a, b):\n    return a + b\n")
        result = backend.edit("/src/calc.py", "add", "sum_two")
        assert result.error is None
        assert "sum_two" in (project_root / "src" / "calc.py").read_text()

    def test_edit_file_not_found(self, backend):
        result = backend.edit("/src/nonexistent.py", "x", "y")
        assert result.error is not None

    def test_edit_identical_old_new_rejected(self, backend):
        """old_string == new_string is a no-op, returns error."""
        backend.write("/src/calc.py", "x = 1")
        result = backend.edit("/src/calc.py", "x = 1", "x = 1")
        assert result.error is not None
        assert "identical" in result.error

    def test_edit_old_string_not_found_guides_to_write(self, backend):
        """When old_string doesn't match, guide LLM to use write_file."""
        backend.write("/src/calc.py", "actual content here")
        result = backend.edit("/src/calc.py", "this does not exist", "new content")
        assert result.error is not None
        assert "write_file" in result.error


# -- ls_info ---------------------------------------------------------------


class TestLsInfo:
    def test_ls_lists_files(self, backend):
        backend.write("/src/a.py", "a")
        backend.write("/src/b.py", "b")
        entries = backend.ls_info("/src")
        paths = [e["path"] for e in entries]
        assert any("a.py" in p for p in paths)
        assert any("b.py" in p for p in paths)

    def test_ls_root(self, backend):
        backend.write("/src/a.py", "a")
        entries = backend.ls_info("/")
        paths = [e["path"] for e in entries]
        assert any("src" in p for p in paths)


# -- glob_info -------------------------------------------------------------


class TestGlobInfo:
    def test_glob_finds_py_files(self, backend):
        backend.write("/src/a.py", "a")
        backend.write("/src/b.py", "b")
        backend.write("/src/c.txt", "c")
        results = backend.glob_info("**/*.py")
        paths = [r["path"] for r in results]
        assert any("a.py" in p for p in paths)
        assert any("b.py" in p for p in paths)
        assert not any("c.txt" in p for p in paths)

    def test_glob_with_path_kwarg(self, backend):
        """Regression: norm_glob must accept path keyword argument."""
        backend.write("/src/a.py", "a")
        results = backend.glob_info("*.py", path="/src")
        paths = [r["path"] for r in results]
        assert any("a.py" in p for p in paths)


# -- grep_raw --------------------------------------------------------------


class TestGrepRaw:
    def test_grep_finds_content(self, backend):
        backend.write("/src/main.py", "hello world\nfoo bar\n")
        results = backend.grep_raw("hello")
        # Returns list of GrepMatch or error string
        assert not isinstance(results, str), f"grep returned error: {results}"
        assert len(results) > 0

    def test_grep_with_path_kwarg(self, backend):
        """Regression: norm_grep must accept path keyword argument."""
        backend.write("/src/main.py", "findme\n")
        results = backend.grep_raw("findme", path="/src")
        assert not isinstance(results, str)

    def test_grep_with_glob_kwarg(self, backend):
        """Regression: norm_grep must accept glob keyword argument."""
        backend.write("/src/a.py", "findme\n")
        backend.write("/src/b.txt", "findme\n")
        results = backend.grep_raw("findme", glob="*.py")
        assert not isinstance(results, str)


# -- Path normalization ----------------------------------------------------


class TestPathNormalization:
    def test_virtual_path_works(self, backend, project_root):
        backend.write("/docs/note.md", "hello")
        assert (project_root / "docs" / "note.md").read_text() == "hello"

    def test_relative_path_works(self, backend, project_root):
        backend.write("docs/note.md", "hello")
        assert (project_root / "docs" / "note.md").read_text() == "hello"

    def test_project_root_prefix_stripped(self, backend, project_root):
        # Write using project root absolute path
        result = backend.write(f"{project_root}/src/test.py", "x")
        assert result.error is None
        assert (project_root / "src" / "test.py").read_text() == "x"

    def test_virtual_mode_enabled(self, backend):
        assert backend.virtual_mode is True


# -- Execute (sandbox support) --------------------------------------------


class TestExecute:
    def test_execute_available(self, backend):
        assert hasattr(backend, "execute")
        assert hasattr(backend, "aexecute")

    def test_execute_python_version(self, backend):
        result = backend.execute(command="python --version")
        assert result.exit_code == 0
        assert "Python" in result.output

    def test_execute_runs_in_project_root(self, backend, project_root):
        backend.write("/src/hello.py", "print('works')")
        result = backend.execute(command="python src/hello.py")
        assert result.exit_code == 0
        assert "works" in result.output

    def test_execute_pytest(self, backend, project_root):
        backend.write("/tests/test_trivial.py", "def test_ok():\n    assert True\n")
        result = backend.execute(command="python -m pytest tests/test_trivial.py -q")
        assert result.exit_code == 0
        assert "passed" in result.output

    def test_execute_timeout(self, backend):
        result = backend.execute(command="sleep 10", timeout=1)
        assert result.exit_code == -1
        assert "timed out" in result.output.lower()

    def test_execute_signature_matches_protocol(self, backend):
        import inspect

        sig = inspect.signature(backend.execute)
        params = list(sig.parameters.keys())
        assert params == ["command", "timeout"]
