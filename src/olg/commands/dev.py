"""Dev command for OLG CLI."""

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

console = Console()

CONFIG_FILE = "open_langgraph.json"


def dev(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        "-h",
        help="Host to bind to",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port to bind to",
    ),
    reload: bool = typer.Option(
        True,
        "--reload/--no-reload",
        help="Enable auto-reload on file changes",
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config file",
    ),
) -> None:
    """Start the development server with hot reload."""
    config_path = config or Path(CONFIG_FILE)

    # Check config exists
    if not config_path.exists():
        console.print(
            f"[red]Error:[/red] Config file not found: {config_path}\n"
            "Are you in an Open LangGraph project directory?"
        )
        raise typer.Exit(code=1)

    # Set config path as environment variable
    os.environ["OPEN_LANGGRAPH_CONFIG"] = str(config_path.absolute())

    console.print(f"\n[bold]Starting Open LangGraph development server[/bold]\n")
    console.print(f"  Config: {config_path}")
    console.print(f"  Server: http://{host}:{port}")
    console.print(f"  Docs:   http://{host}:{port}/docs")
    console.print(f"  Reload: {'enabled' if reload else 'disabled'}")
    console.print()

    # Build uvicorn command
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "src.agent_server.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    if reload:
        cmd.append("--reload")

    try:
        result = subprocess.run(cmd)
        raise typer.Exit(code=result.returncode)
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped[/yellow]")
        raise typer.Exit(code=0)
