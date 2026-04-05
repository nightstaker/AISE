"""Tests for AISE packaging and self-extracting installer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Mark all tests in this file as slow (real subprocess operations)
pytestmark = pytest.mark.slow

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def build_dir():
    """Temporary directory for build output."""
    d = tempfile.mkdtemp(prefix="aise_build_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def install_dir():
    """Temporary directory for installation."""
    d = tempfile.mkdtemp(prefix="aise_install_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def _run(cmd: str | list, **kwargs) -> subprocess.CompletedProcess:
    """Run command, capture output."""
    if isinstance(cmd, str):
        cmd = ["bash", "-c", cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kwargs)


class TestBuildScript:
    """Tests for packaging/build.sh."""

    def test_build_produces_installer(self, build_dir: Path):
        """build.sh creates aise-VERSION.sh in output directory."""
        result = _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0-test --output {build_dir}")
        assert result.returncode == 0, f"Build failed: {result.stderr}"
        installer = build_dir / "aise-0.1.0-test.sh"
        assert installer.exists(), "Installer not created"
        assert installer.stat().st_size > 1000, "Installer suspiciously small"
        # Check executable
        assert os.access(installer, os.X_OK), "Installer not executable"

    def test_build_default_version(self, build_dir: Path):
        """build.sh reads version from pyproject.toml when not specified."""
        result = _run(f"bash {PROJECT_ROOT}/packaging/build.sh --output {build_dir}")
        assert result.returncode == 0, f"Build failed: {result.stderr}"
        # Should use 0.1.0 from pyproject.toml
        installer = build_dir / "aise-0.1.0.sh"
        assert installer.exists(), f"Expected aise-0.1.0.sh, found: {list(build_dir.iterdir())}"

    def test_build_help(self):
        """build.sh --help shows usage."""
        result = _run(f"bash {PROJECT_ROOT}/packaging/build.sh --help")
        assert result.returncode == 0
        assert "Usage" in result.stdout

    def test_installer_contains_archive_marker(self, build_dir: Path):
        """Built installer contains the archive marker."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        content = installer.read_text(errors="replace")
        assert "__ARCHIVE_BELOW__" in content

    def test_installer_header_has_version(self, build_dir: Path):
        """Installer header embeds correct version."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 1.2.3 --output {build_dir}")
        installer = build_dir / "aise-1.2.3.sh"
        # Read header (before archive marker)
        content = installer.read_text(errors="replace")
        header = content.split("__ARCHIVE_BELOW__")[0]
        assert "1.2.3" in header


class TestInstallerNoArgs:
    """Test installer without subcommand shows help."""

    def test_no_args_shows_usage(self, build_dir: Path):
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        result = _run(f"bash {installer}")
        assert result.returncode == 0
        assert "install" in result.stdout.lower()
        assert "upgrade" in result.stdout.lower()
        assert "uninstall" in result.stdout.lower()

    def test_install_help(self, build_dir: Path):
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        result = _run(f"bash {installer} install --help")
        assert result.returncode == 0
        assert "--prefix" in result.stdout
        assert "--port" in result.stdout
        assert "--host" in result.stdout

    def test_upgrade_help(self, build_dir: Path):
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        result = _run(f"bash {installer} upgrade --help")
        assert result.returncode == 0
        assert "--no-backup" in result.stdout

    def test_uninstall_help(self, build_dir: Path):
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        result = _run(f"bash {installer} uninstall --help")
        assert result.returncode == 0
        assert "--keep-data" in result.stdout


class TestInstallerInstall:
    """Test actual installation flow."""

    @pytest.fixture
    def installer(self, build_dir: Path) -> Path:
        """Build installer for tests."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        return build_dir / "aise-0.1.0.sh"

    def test_install_creates_structure(self, installer: Path, install_dir: Path):
        """Install creates expected directory structure."""
        result = _run(f"bash {installer} install --prefix {install_dir} --no-start")
        assert result.returncode == 0, f"Install failed: {result.stderr}\n{result.stdout}"

        # Check structure
        assert (install_dir / ".aise_version").exists()
        assert (install_dir / ".aise_version").read_text().strip() == "0.1.0"
        assert (install_dir / "src" / "aise").is_dir()
        assert (install_dir / "config").is_dir()
        assert (install_dir / "venv").is_dir()
        assert (install_dir / "data").is_dir()
        assert (install_dir / "logs").is_dir()
        assert (install_dir / ".env").exists()
        assert (install_dir / "bin" / "aise").exists()

    def test_install_env_file(self, installer: Path, install_dir: Path):
        """Install writes correct .env file."""
        _run(f"bash {installer} install --prefix {install_dir} --port 9999 --host 0.0.0.0 --no-start")
        env = (install_dir / ".env").read_text()
        assert "AISE_PORT=9999" in env
        assert "AISE_HOST=0.0.0.0" in env

    def test_install_refuses_existing(self, installer: Path, install_dir: Path):
        """Install rejects existing installation without --force."""
        _run(f"bash {installer} install --prefix {install_dir} --no-start")
        result = _run(f"bash {installer} install --prefix {install_dir} --no-start")
        assert result.returncode != 0
        assert "already installed" in result.stdout.lower() or "already installed" in result.stderr.lower()

    def test_install_force_overwrites(self, installer: Path, install_dir: Path):
        """Install --force overwrites existing."""
        _run(f"bash {installer} install --prefix {install_dir} --no-start")
        result = _run(f"bash {installer} install --prefix {install_dir} --no-start --force")
        assert result.returncode == 0

    def test_install_custom_dirs(self, installer: Path, install_dir: Path):
        """Install respects custom data and log dirs."""
        data = install_dir / "custom_data"
        logs = install_dir / "custom_logs"
        result = _run(f"bash {installer} install --prefix {install_dir} --data-dir {data} --log-dir {logs} --no-start")
        assert result.returncode == 0
        assert data.is_dir()
        assert logs.is_dir()

    def test_install_creates_cli_wrapper(self, installer: Path, install_dir: Path):
        """CLI wrapper script is executable and has correct shebang."""
        _run(f"bash {installer} install --prefix {install_dir} --no-start")
        wrapper = install_dir / "bin" / "aise"
        assert wrapper.exists()
        assert os.access(wrapper, os.X_OK)
        content = wrapper.read_text()
        assert "#!/usr/bin/env bash" in content
        assert "AISE_HOME" in content


class TestInstallerInfo:
    """Test info command."""

    def test_info_shows_version(self, build_dir: Path):
        """Info command displays package version."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 2.0.0 --output {build_dir}")
        installer = build_dir / "aise-2.0.0.sh"
        result = _run(f"bash {installer} info")
        assert result.returncode == 0
        assert "2.0.0" in result.stdout

    def test_info_shows_build_meta(self, build_dir: Path):
        """Info command shows build metadata."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 2.0.0 --output {build_dir}")
        installer = build_dir / "aise-2.0.0.sh"
        result = _run(f"bash {installer} info")
        assert "Build time" in result.stdout or "build_time" in result.stdout


class TestInstallerUpgrade:
    """Test upgrade flow."""

    def test_upgrade_requires_existing(self, build_dir: Path, install_dir: Path):
        """Upgrade fails if no existing installation."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.2.0 --output {build_dir}")
        installer = build_dir / "aise-0.2.0.sh"
        result = _run(f"bash {installer} upgrade --prefix {install_dir} --no-restart")
        assert result.returncode != 0

    def test_upgrade_updates_version(self, build_dir: Path, install_dir: Path):
        """Upgrade changes installed version."""
        # Install v1
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        v1 = build_dir / "aise-0.1.0.sh"
        _run(f"bash {v1} install --prefix {install_dir} --no-start")
        assert (install_dir / ".aise_version").read_text().strip() == "0.1.0"

        # Upgrade to v2
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.2.0 --output {build_dir}")
        v2 = build_dir / "aise-0.2.0.sh"
        result = _run(f"bash {v2} upgrade --prefix {install_dir} --no-restart")
        assert result.returncode == 0
        assert (install_dir / ".aise_version").read_text().strip() == "0.2.0"

    def test_upgrade_preserves_config(self, build_dir: Path, install_dir: Path):
        """Upgrade preserves user's config file."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        v1 = build_dir / "aise-0.1.0.sh"
        _run(f"bash {v1} install --prefix {install_dir} --no-start")

        # Modify config
        config = install_dir / "config" / "global_project_config.json"
        config.write_text('{"custom": true}')

        # Upgrade
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.2.0 --output {build_dir}")
        v2 = build_dir / "aise-0.2.0.sh"
        _run(f"bash {v2} upgrade --prefix {install_dir} --no-restart")

        assert json.loads(config.read_text()) == {"custom": True}

    def test_upgrade_creates_backup(self, build_dir: Path, install_dir: Path):
        """Upgrade creates backup of previous version."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        v1 = build_dir / "aise-0.1.0.sh"
        _run(f"bash {v1} install --prefix {install_dir} --no-start")

        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.2.0 --output {build_dir}")
        v2 = build_dir / "aise-0.2.0.sh"
        _run(f"bash {v2} upgrade --prefix {install_dir} --no-restart")

        backups = install_dir / "backups"
        assert backups.is_dir()
        backup_dirs = list(backups.iterdir())
        assert len(backup_dirs) >= 1


class TestInstallerUninstall:
    """Test uninstall flow."""

    def test_uninstall_removes_all(self, build_dir: Path, install_dir: Path):
        """Uninstall --yes removes installation directory."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        _run(f"bash {installer} install --prefix {install_dir} --no-start")

        result = _run(f"bash {installer} uninstall --prefix {install_dir} --yes")
        assert result.returncode == 0
        assert not install_dir.exists()

    def test_uninstall_keep_data(self, build_dir: Path, install_dir: Path):
        """Uninstall --keep-data preserves data and config."""
        _run(f"bash {PROJECT_ROOT}/packaging/build.sh --version 0.1.0 --output {build_dir}")
        installer = build_dir / "aise-0.1.0.sh"
        _run(f"bash {installer} install --prefix {install_dir} --no-start")

        # Create a data file
        (install_dir / "data" / "test.db").write_text("important data")

        result = _run(f"bash {installer} uninstall --prefix {install_dir} --yes --keep-data")
        assert result.returncode == 0

        # Data preserved
        assert (install_dir / "data" / "test.db").exists()
        # Code removed
        assert not (install_dir / "src").exists()
        assert not (install_dir / "venv").exists()
