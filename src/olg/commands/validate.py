"""Validate command for OLG CLI."""

import json
from pathlib import Path

import typer
from rich.console import Console

console = Console()

DEFAULT_CONFIG = "open_langgraph.json"


def validate(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Validate an open_langgraph.json configuration file."""
    config_path = config or Path(DEFAULT_CONFIG)

    # Check file exists
    if not config_path.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config_path}")
        raise typer.Exit(code=1)

    # Try to parse JSON
    try:
        with config_path.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid JSON: {e}")
        raise typer.Exit(code=1) from None

    # Validate required keys
    if "graphs" not in data:
        console.print("[red]Error:[/red] Missing required key 'graphs' in config")
        raise typer.Exit(code=1)

    if not isinstance(data["graphs"], dict):
        console.print("[red]Error:[/red] 'graphs' must be a dictionary")
        raise typer.Exit(code=1)

    # Validate graph definitions
    for graph_id, graph_path in data["graphs"].items():
        if not isinstance(graph_path, str):
            console.print(f"[red]Error:[/red] Graph '{graph_id}' path must be a string")
            raise typer.Exit(code=1)

        if ":" not in graph_path:
            console.print(
                f"[red]Error:[/red] Graph '{graph_id}' path must include export name "
                f"(format: 'path/to/file.py:export_name')"
            )
            raise typer.Exit(code=1)

    # Success
    graph_count = len(data["graphs"])
    console.print(f"[green]Valid![/green] Configuration has {graph_count} graph(s) defined.")
    for graph_id in data["graphs"]:
        console.print(f"  - {graph_id}")
