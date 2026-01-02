"""Tests for olg validate command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from olg.cli import app

runner = CliRunner()


class TestValidateCommand:
    """Tests for the validate command."""

    def test_validate_valid_config(self, tmp_path: Path):
        """Test validating a valid open_langgraph.json file."""
        config_file = tmp_path / "open_langgraph.json"
        config_file.write_text(
            '{"graphs": {"agent": "./graphs/agent.py:graph"}}'
        )

        result = runner.invoke(app, ["validate", "--config", str(config_file)])

        assert result.exit_code == 0
        assert "valid" in result.stdout.lower()

    def test_validate_missing_config(self, tmp_path: Path):
        """Test validating when config file doesn't exist."""
        config_file = tmp_path / "nonexistent.json"

        result = runner.invoke(app, ["validate", "--config", str(config_file)])

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "error" in result.stdout.lower()

    def test_validate_invalid_json(self, tmp_path: Path):
        """Test validating invalid JSON."""
        config_file = tmp_path / "open_langgraph.json"
        config_file.write_text("not valid json {")

        result = runner.invoke(app, ["validate", "--config", str(config_file)])

        assert result.exit_code != 0

    def test_validate_missing_graphs_key(self, tmp_path: Path):
        """Test validating config without 'graphs' key."""
        config_file = tmp_path / "open_langgraph.json"
        config_file.write_text('{"other": "value"}')

        result = runner.invoke(app, ["validate", "--config", str(config_file)])

        assert result.exit_code != 0
        assert "graphs" in result.stdout.lower()

    def test_validate_default_config_path(self, tmp_path: Path, monkeypatch):
        """Test validate uses default config path when not specified."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "open_langgraph.json"
        config_file.write_text('{"graphs": {"agent": "./agent.py:graph"}}')

        result = runner.invoke(app, ["validate"])

        assert result.exit_code == 0
