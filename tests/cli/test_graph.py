"""Tests for olg graph commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from olg.cli import app

runner = CliRunner()


class TestGraphAddCommand:
    """Tests for the graph add command."""

    def test_graph_add_creates_file(self, tmp_path: Path, monkeypatch):
        """Test graph add creates a new graph file."""
        monkeypatch.chdir(tmp_path)

        # Create minimal project structure
        (tmp_path / "graphs").mkdir()
        (tmp_path / "open_langgraph.json").write_text('{"graphs": {}}')

        result = runner.invoke(app, ["graph", "add", "weather"])

        assert result.exit_code == 0
        assert (tmp_path / "graphs" / "weather.py").exists()

    def test_graph_add_updates_config(self, tmp_path: Path, monkeypatch):
        """Test graph add updates open_langgraph.json."""
        monkeypatch.chdir(tmp_path)

        (tmp_path / "graphs").mkdir()
        (tmp_path / "open_langgraph.json").write_text('{"graphs": {}}')

        runner.invoke(app, ["graph", "add", "weather"])

        config = json.loads((tmp_path / "open_langgraph.json").read_text())
        assert "weather" in config["graphs"]
        assert config["graphs"]["weather"] == "./graphs/weather.py:graph"

    def test_graph_add_existing_fails(self, tmp_path: Path, monkeypatch):
        """Test graph add fails if graph already exists."""
        monkeypatch.chdir(tmp_path)

        (tmp_path / "graphs").mkdir()
        (tmp_path / "graphs" / "weather.py").write_text("# existing")
        (tmp_path / "open_langgraph.json").write_text(
            '{"graphs": {"weather": "./graphs/weather.py:graph"}}'
        )

        result = runner.invoke(app, ["graph", "add", "weather"])

        assert result.exit_code != 0
        assert "exists" in result.stdout.lower()

    def test_graph_add_no_config_fails(self, tmp_path: Path, monkeypatch):
        """Test graph add fails without open_langgraph.json."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["graph", "add", "weather"])

        assert result.exit_code != 0

    def test_graph_add_creates_graphs_dir_if_missing(self, tmp_path: Path, monkeypatch):
        """Test graph add creates graphs directory if it doesn't exist."""
        monkeypatch.chdir(tmp_path)

        # Only config, no graphs dir
        (tmp_path / "open_langgraph.json").write_text('{"graphs": {}}')

        result = runner.invoke(app, ["graph", "add", "weather"])

        assert result.exit_code == 0
        assert (tmp_path / "graphs").is_dir()
        assert (tmp_path / "graphs" / "weather.py").exists()

    def test_graph_add_snake_case_name(self, tmp_path: Path, monkeypatch):
        """Test graph add with snake_case name generates correct class name."""
        monkeypatch.chdir(tmp_path)

        (tmp_path / "graphs").mkdir()
        (tmp_path / "open_langgraph.json").write_text('{"graphs": {}}')

        runner.invoke(app, ["graph", "add", "weather_forecast"])

        content = (tmp_path / "graphs" / "weather_forecast.py").read_text()
        # Should have PascalCase class name
        assert "WeatherForecast" in content
