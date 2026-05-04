"""Tests for stack_strict (commit c12)."""

from __future__ import annotations

import pytest

from aise.runtime.stack_strict import (
    UnsupportedLanguageError,
    get_interface_filename,
    get_test_extension,
    get_toolchain,
    language_has_no_barrel,
    registered_languages,
)

# -- get_toolchain -------------------------------------------------------


class TestGetToolchain:
    def test_known_languages_return_row(self):
        for lang in ("python", "typescript", "go", "rust", "java", "dart", "csharp", "kotlin", "swift"):
            row = get_toolchain(lang)
            assert "test_cmd" in row
            assert "test_path_pattern" in row
            assert "src_path_pattern" in row
            assert "static_check" in row

    def test_unknown_language_raises(self):
        with pytest.raises(UnsupportedLanguageError) as exc_info:
            get_toolchain("clojure")
        assert exc_info.value.language == "clojure"
        assert exc_info.value.table == "_LANGUAGE_TOOLCHAIN"
        assert "python" in exc_info.value.registered

    def test_normalizes_case_and_whitespace(self):
        assert get_toolchain(" Python ") == get_toolchain("python")
        assert get_toolchain("CSHARP") == get_toolchain("csharp")

    def test_empty_language_raises(self):
        with pytest.raises(UnsupportedLanguageError):
            get_toolchain("")


# -- get_interface_filename ----------------------------------------------


class TestGetInterfaceFilename:
    def test_python_returns_init_py(self):
        path = get_interface_filename("python", "core", "src/core")
        assert path.endswith("__init__.py")

    def test_typescript_returns_index_ts(self):
        path = get_interface_filename("typescript", "core", "src/core")
        assert path.endswith("index.ts")

    def test_dart_substitutes_subsystem_name(self):
        path = get_interface_filename("dart", "gameplay", "lib/gameplay")
        assert path.endswith("gameplay.dart")

    def test_csharp_returns_empty_string(self):
        # csharp is in _INTERFACE_FILENAME with the "" sentinel —
        # caller should treat empty as "no barrel deliverable for this stack"
        assert get_interface_filename("csharp", "x", "Assets/Scripts/X") == ""
        assert get_interface_filename("kotlin", "x", "src/main/kotlin/x") == ""
        assert get_interface_filename("swift", "x", "Sources/X") == ""

    def test_typo_language_raises(self):
        with pytest.raises(UnsupportedLanguageError):
            get_interface_filename("definitely_a_typo", "x", "x")


# -- get_test_extension --------------------------------------------------


class TestGetTestExtension:
    def test_python_dot_py(self):
        assert get_test_extension("python") == ".py"

    def test_csharp_dot_cs(self):
        # csharp must be in _LANGUAGE_TEST_EXT; if not, this test will
        # show the user where to add it. Per c12 the user added csharp
        # to _LANGUAGE_TOOLCHAIN/_INTERFACE_FILENAME — verify it's also
        # in scenario_gate's table.
        try:
            ext = get_test_extension("csharp")
        except UnsupportedLanguageError as e:
            pytest.fail(
                f"csharp missing from _LANGUAGE_TEST_EXT: {e}. "
                "Add it to src/aise/safety_net/scenario_gate.py to "
                "complete the c12 csharp coverage across all 3 tables."
            )
        assert ext == ".cs"

    def test_unknown_raises(self):
        with pytest.raises(UnsupportedLanguageError):
            get_test_extension("clojure")


# -- registered_languages ------------------------------------------------


class TestRegisteredLanguages:
    def test_includes_csharp(self):
        assert "csharp" in registered_languages()

    def test_includes_kotlin_and_swift(self):
        ls = registered_languages()
        assert "kotlin" in ls
        assert "swift" in ls

    def test_returns_sorted(self):
        ls = registered_languages()
        assert ls == sorted(ls)


# -- language_has_no_barrel ----------------------------------------------


class TestLanguageHasNoBarrel:
    def test_csharp_kotlin_swift_have_no_barrel(self):
        for lang in ("csharp", "cs", "kotlin", "swift", "CSHARP"):
            assert language_has_no_barrel(lang)

    def test_python_has_barrel(self):
        assert not language_has_no_barrel("python")
        assert not language_has_no_barrel("typescript")
        assert not language_has_no_barrel("dart")


# -- UnsupportedLanguageError --------------------------------------------


class TestUnsupportedLanguageError:
    def test_carries_language_table_registered(self):
        try:
            get_toolchain("clojure")
        except UnsupportedLanguageError as exc:
            assert exc.language == "clojure"
            assert exc.table == "_LANGUAGE_TOOLCHAIN"
            assert isinstance(exc.registered, list)
            # Error message tells the user where to add support
            assert "stack_contract.py" in str(exc)
