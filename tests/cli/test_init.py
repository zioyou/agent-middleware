"""Tests for olg init command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from olg.cli import app

runner = CliRunner()


class TestInitCommand:
    """Tests for the init command."""

    def test_init_creates_project_structure(self, tmp_path: Path):
        """Test init creates basic project structure."""
        project_path = tmp_path / "my-agent"

        result = runner.invoke(app, ["init", str(project_path)])

        assert result.exit_code == 0
        assert project_path.exists()
        assert (project_path / "open_langgraph.json").exists()
        assert (project_path / "graphs").is_dir()

    def test_init_creates_config_file(self, tmp_path: Path):
        """Test init creates valid config file."""
        import json

        project_path = tmp_path / "my-agent"

        runner.invoke(app, ["init", str(project_path)])

        config = json.loads((project_path / "open_langgraph.json").read_text())
        assert "graphs" in config
        assert len(config["graphs"]) > 0

    def test_init_with_template(self, tmp_path: Path):
        """Test init with specific template."""
        project_path = tmp_path / "my-agent"

        result = runner.invoke(
            app, ["init", str(project_path), "--template", "basic-agent"]
        )

        assert result.exit_code == 0
        assert (project_path / "graphs" / "agent.py").exists()

    def test_init_existing_directory_fails(self, tmp_path: Path):
        """Test init fails if directory exists and not empty."""
        project_path = tmp_path / "existing"
        project_path.mkdir()
        (project_path / "somefile.txt").write_text("content")

        result = runner.invoke(app, ["init", str(project_path)])

        assert result.exit_code != 0
        assert "exists" in result.stdout.lower() or "not empty" in result.stdout.lower()

    def test_init_lists_available_templates(self, tmp_path: Path):
        """Test init --list-templates shows available templates."""
        result = runner.invoke(app, ["init", "--list-templates"])

        assert result.exit_code == 0
        assert "basic-agent" in result.stdout
