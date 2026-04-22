"""Unit tests for the language-config root generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aise.runtime.lang_config import detect_dominant_language, generate_root_config


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestDetection:
    def test_missing_src_dir(self, tmp_path: Path) -> None:
        assert detect_dominant_language(tmp_path / "nope") is None

    def test_empty_src_dir(self, workdir: Path) -> None:
        assert detect_dominant_language(workdir / "src") is None

    def test_python_wins_when_dominant(self, workdir: Path) -> None:
        _touch(workdir / "src" / "main.py")
        _touch(workdir / "src" / "helper.py")
        _touch(workdir / "src" / "misc.txt")
        assert detect_dominant_language(workdir / "src") == "python"

    def test_typescript_wins_over_less_common(self, workdir: Path) -> None:
        _touch(workdir / "src" / "index.ts")
        _touch(workdir / "src" / "helper.tsx")
        _touch(workdir / "src" / "stray.go")
        assert detect_dominant_language(workdir / "src") == "typescript"

    def test_nested_files_are_counted(self, workdir: Path) -> None:
        _touch(workdir / "src" / "pkg" / "a.rs")
        _touch(workdir / "src" / "pkg" / "b.rs")
        assert detect_dominant_language(workdir / "src") == "rust"

    def test_tie_break_prefers_earlier_language(self, workdir: Path) -> None:
        # 2 python, 2 go — python is earlier in the language list so wins
        _touch(workdir / "src" / "a.py")
        _touch(workdir / "src" / "b.py")
        _touch(workdir / "src" / "c.go")
        _touch(workdir / "src" / "d.go")
        assert detect_dominant_language(workdir / "src") == "python"


class TestGenerate:
    def test_python_project_writes_pyproject(self, workdir: Path) -> None:
        _touch(workdir / "src" / "main.py")
        result = generate_root_config(workdir, project_name="snake-game", run_command="python src/main.py")
        assert result["created"] is True
        assert result["path"] == "pyproject.toml"
        body = (workdir / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "snake-game"' in body
        # Entry point derived from RUN:
        assert 'snake-game = "main:main"' in body

    def test_node_project_writes_package_json(self, workdir: Path) -> None:
        _touch(workdir / "src" / "index.js")
        result = generate_root_config(workdir, project_name="My App", run_command="node src/index.js")
        assert result["created"] is True
        assert result["path"] == "package.json"
        payload = json.loads((workdir / "package.json").read_text(encoding="utf-8"))
        assert payload["name"] == "my-app"
        assert payload["scripts"]["start"] == "node src/index.js"
        assert payload["private"] is True

    def test_typescript_adds_typescript_devdep(self, workdir: Path) -> None:
        _touch(workdir / "src" / "index.ts")
        result = generate_root_config(workdir, project_name="ts-demo")
        assert result["language"] == "typescript"
        payload = json.loads((workdir / "package.json").read_text(encoding="utf-8"))
        assert "typescript" in payload["devDependencies"]
        assert payload["main"] == "src/index.ts"

    def test_go_module_uses_normalized_name(self, workdir: Path) -> None:
        _touch(workdir / "src" / "main.go")
        result = generate_root_config(workdir, project_name="User Service")
        assert result["created"] is True
        body = (workdir / "go.mod").read_text(encoding="utf-8")
        assert body.startswith("// AISE-generated")
        assert "module user-service" in body

    def test_rust_writes_cargo_toml(self, workdir: Path) -> None:
        _touch(workdir / "src" / "main.rs")
        result = generate_root_config(workdir, project_name="rusty")
        assert result["created"] is True
        body = (workdir / "Cargo.toml").read_text(encoding="utf-8")
        assert "[package]" in body
        assert 'name = "rusty"' in body
        assert 'edition = "2021"' in body

    def test_java_writes_pom_xml(self, workdir: Path) -> None:
        _touch(workdir / "src" / "App.java")
        result = generate_root_config(workdir, project_name="demo-api")
        assert result["created"] is True
        body = (workdir / "pom.xml").read_text(encoding="utf-8")
        assert "<artifactId>demo-api</artifactId>" in body
        assert "<modelVersion>4.0.0</modelVersion>" in body

    def test_skip_when_no_source(self, workdir: Path) -> None:
        result = generate_root_config(workdir)
        assert result["skipped"] is True
        assert result["reason"] == "no-source-detected"
        # No config file should have landed next to the empty src/ dir.
        for marker in ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", "pom.xml"):
            assert not (workdir / marker).exists()

    def test_skip_when_target_exists(self, workdir: Path) -> None:
        _touch(workdir / "src" / "main.py")
        (workdir / "pyproject.toml").write_text("# pre-existing\n", encoding="utf-8")
        result = generate_root_config(workdir, project_name="x")
        assert result["skipped"] is True
        assert result["reason"] == "already-exists"
        assert (workdir / "pyproject.toml").read_text(encoding="utf-8") == "# pre-existing\n"

    def test_skip_when_alternative_config_exists(self, workdir: Path) -> None:
        _touch(workdir / "src" / "main.py")
        (workdir / "setup.py").write_text("# legacy\n", encoding="utf-8")
        result = generate_root_config(workdir, project_name="x")
        assert result["skipped"] is True
        assert result["reason"] == "alternative-config-exists"
        # Never creates pyproject.toml if setup.py is present.
        assert not (workdir / "pyproject.toml").exists()

    def test_skip_when_project_root_missing(self, tmp_path: Path) -> None:
        result = generate_root_config(tmp_path / "does-not-exist")
        assert result["skipped"] is True
        assert result["reason"] == "no-project-root"

    def test_name_falls_back_to_directory(self, tmp_path: Path) -> None:
        root = tmp_path / "MyProject_42"
        (root / "src").mkdir(parents=True)
        _touch(root / "src" / "main.py")
        result = generate_root_config(root, project_name="")
        body = (root / "pyproject.toml").read_text(encoding="utf-8")
        # Dots, spaces, underscores, uppercase all collapsed to hyphen-lower.
        assert 'name = "myproject-42"' in body
        assert result["created"] is True
