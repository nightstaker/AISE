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
        for lang in ("python", "typescript", "go", "rust", "cpp", "dart", "kotlin", "swift"):
            row = get_toolchain(lang)
            assert "test_cmd" in row
            assert "test_path_pattern" in row
            assert "src_path_pattern" in row
            assert "static_check" in row

    def test_dropped_languages_raise(self):
        # csharp / cs / java were dropped on 2026-05-04. Re-adding any
        # of them must be a deliberate decision, not a silent fallback.
        for lang in ("csharp", "cs", "java"):
            with pytest.raises(UnsupportedLanguageError):
                get_toolchain(lang)

    def test_unknown_language_raises(self):
        with pytest.raises(UnsupportedLanguageError) as exc_info:
            get_toolchain("clojure")
        assert exc_info.value.language == "clojure"
        assert exc_info.value.table == "_LANGUAGE_TOOLCHAIN"
        assert "python" in exc_info.value.registered

    def test_normalizes_case_and_whitespace(self):
        assert get_toolchain(" Python ") == get_toolchain("python")
        assert get_toolchain("CPP") == get_toolchain("cpp")

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

    def test_no_barrel_languages_return_empty_string(self):
        # cpp/kotlin/swift have no per-folder barrel convention; the
        # "" sentinel tells callers to skip the deliverable entirely.
        assert get_interface_filename("cpp", "core", "src/core") == ""
        assert get_interface_filename("kotlin", "x", "src/main/kotlin/x") == ""
        assert get_interface_filename("swift", "x", "Sources/X") == ""

    def test_typo_language_raises(self):
        with pytest.raises(UnsupportedLanguageError):
            get_interface_filename("definitely_a_typo", "x", "x")


# -- get_test_extension --------------------------------------------------


class TestGetTestExtension:
    def test_python_dot_py(self):
        assert get_test_extension("python") == ".py"

    def test_cpp_dot_cpp(self):
        # cpp must be in _LANGUAGE_TEST_EXT across all 3 tables for the
        # phase-3 fanout + scenario derivation to use the correct
        # extension. Both ``cpp`` and ``c++`` aliases must round-trip.
        assert get_test_extension("cpp") == ".cpp"
        assert get_test_extension("c++") == ".cpp"

    def test_dropped_languages_have_no_test_extension(self):
        for lang in ("csharp", "cs", "java"):
            with pytest.raises(UnsupportedLanguageError):
                get_test_extension(lang)

    def test_unknown_raises(self):
        with pytest.raises(UnsupportedLanguageError):
            get_test_extension("clojure")


# -- registered_languages ------------------------------------------------


class TestRegisteredLanguages:
    def test_includes_cpp(self):
        assert "cpp" in registered_languages()

    def test_includes_kotlin_and_swift(self):
        ls = registered_languages()
        assert "kotlin" in ls
        assert "swift" in ls

    def test_excludes_dropped_languages(self):
        ls = registered_languages()
        for lang in ("csharp", "cs", "java"):
            assert lang not in ls, (
                f"{lang!r} unexpectedly present in registered_languages(); support was dropped on 2026-05-04"
            )

    def test_returns_sorted(self):
        ls = registered_languages()
        assert ls == sorted(ls)


# -- language_has_no_barrel ----------------------------------------------


class TestLanguageHasNoBarrel:
    def test_cpp_kotlin_swift_have_no_barrel(self):
        for lang in ("cpp", "c++", "kotlin", "swift", "CPP"):
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
