"""Integration tests for OLG CLI."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from olg.cli import app

runner = CliRunner()


class TestCLIIntegration:
    """End-to-end CLI workflow tests."""

    def test_full_workflow(self, tmp_path: Path, monkeypatch):
        """Test complete workflow: init -> graph add -> validate."""
        project_path = tmp_path / "test-project"

        # Step 1: Initialize project
        result = runner.invoke(app, ["init", str(project_path)])
        assert result.exit_code == 0
        assert (project_path / "open_langgraph.json").exists()

        # Step 2: Change to project directory
        monkeypatch.chdir(project_path)

        # Step 3: Add a new graph
        result = runner.invoke(app, ["graph", "add", "weather"])
        assert result.exit_code == 0
        assert (project_path / "graphs" / "weather.py").exists()

        # Step 4: Validate configuration
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

        # Step 5: Verify final config has both graphs
        config = json.loads((project_path / "open_langgraph.json").read_text())
        assert len(config["graphs"]) == 2

    def test_help_commands(self):
        """Test all help outputs work."""
        for cmd in ["--help", "init --help", "validate --help", "graph --help", "dev --help"]:
            result = runner.invoke(app, cmd.split())
            assert result.exit_code == 0
            assert "usage" in result.stdout.lower() or "options" in result.stdout.lower()

    def test_workflow_with_hitl_template(self, tmp_path: Path, monkeypatch):
        """Test workflow with HITL template."""
        project_path = tmp_path / "hitl-project"

        # Initialize with HITL template
        result = runner.invoke(
            app, ["init", str(project_path), "--template", "hitl-agent"]
        )
        assert result.exit_code == 0

        # Change to project directory
        monkeypatch.chdir(project_path)

        # Add another graph
        result = runner.invoke(app, ["graph", "add", "assistant"])
        assert result.exit_code == 0

        # Validate
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0

        # Verify HITL features in original agent
        content = (project_path / "graphs" / "agent.py").read_text()
        assert "interrupt" in content
        assert "approval_gate" in content

    def test_workflow_with_a2a_template(self, tmp_path: Path, monkeypatch):
        """Test workflow with A2A template."""
        project_path = tmp_path / "a2a-project"

        # Initialize with A2A template
        result = runner.invoke(
            app, ["init", str(project_path), "--template", "a2a-agent"]
        )
        assert result.exit_code == 0

        # Change to project directory
        monkeypatch.chdir(project_path)

        # Validate
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0

        # Verify A2A features
        content = (project_path / "graphs" / "agent.py").read_text()
        assert "attach_a2a_metadata" in content

    def test_multiple_graphs_workflow(self, tmp_path: Path, monkeypatch):
        """Test adding multiple graphs to a project."""
        project_path = tmp_path / "multi-graph-project"

        # Initialize project
        result = runner.invoke(app, ["init", str(project_path)])
        assert result.exit_code == 0

        # Change to project directory
        monkeypatch.chdir(project_path)

        # Add multiple graphs
        graphs_to_add = ["weather", "calculator", "search_engine"]
        for graph_name in graphs_to_add:
            result = runner.invoke(app, ["graph", "add", graph_name])
            assert result.exit_code == 0
            assert (project_path / "graphs" / f"{graph_name}.py").exists()

        # Validate
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0

        # Verify config has all graphs (1 from init + 3 added)
        config = json.loads((project_path / "open_langgraph.json").read_text())
        assert len(config["graphs"]) == 4

    def test_version_available(self):
        """Test that version info is accessible."""
        from olg import __version__
        assert __version__ == "0.1.0"

    def test_error_recovery_invalid_template(self, tmp_path: Path):
        """Test error handling with invalid template."""
        project_path = tmp_path / "error-project"

        result = runner.invoke(
            app, ["init", str(project_path), "--template", "nonexistent"]
        )

        assert result.exit_code != 0
        assert "unknown template" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_error_recovery_duplicate_graph(self, tmp_path: Path, monkeypatch):
        """Test error handling when adding duplicate graph."""
        project_path = tmp_path / "duplicate-project"

        # Initialize
        runner.invoke(app, ["init", str(project_path)])
        monkeypatch.chdir(project_path)

        # Add graph
        runner.invoke(app, ["graph", "add", "weather"])

        # Try to add same graph again
        result = runner.invoke(app, ["graph", "add", "weather"])
        assert result.exit_code != 0
        assert "exists" in result.stdout.lower()
