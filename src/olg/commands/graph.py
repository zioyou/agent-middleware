"""Graph commands for OLG CLI."""

import json
from pathlib import Path

import typer
from jinja2 import Environment, FileSystemLoader
from rich.console import Console

console = Console()

graph_app = typer.Typer(
    name="graph",
    help="Manage graphs in your project",
    no_args_is_help=True,
)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
CONFIG_FILE = "open_langgraph.json"


@graph_app.command("add")
def add(
    name: str = typer.Argument(
        ...,
        help="Name of the graph to add",
    ),
) -> None:
    """Add a new graph to the project."""
    # Check we're in a project directory
    config_path = Path(CONFIG_FILE)
    if not config_path.exists():
        console.print(
            f"[red]Error:[/red] {CONFIG_FILE} not found. Are you in an Open LangGraph project directory?"
        )
        raise typer.Exit(code=1)

    # Load config
    try:
        with config_path.open() as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid JSON in {CONFIG_FILE}: {e}")
        raise typer.Exit(code=1) from None

    # Check if graph already exists in config
    if name in config.get("graphs", {}):
        console.print(f"[red]Error:[/red] Graph '{name}' already exists in config")
        raise typer.Exit(code=1)

    graph_file = Path("graphs") / f"{name}.py"
    if graph_file.exists():
        console.print(f"[red]Error:[/red] File '{graph_file}' already exists")
        raise typer.Exit(code=1)

    # Ensure graphs directory exists
    graph_file.parent.mkdir(exist_ok=True)

    # Generate graph file from template
    template_file = TEMPLATE_DIR / "graph.py.j2"
    if not template_file.exists():
        console.print(f"[red]Error:[/red] Graph template not found at {template_file}")
        raise typer.Exit(code=1)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("graph.py.j2")

    # Convert name to class name (snake_case -> PascalCase)
    class_name = "".join(word.capitalize() for word in name.split("_"))

    content = template.render(
        graph_name=name,
        class_name=class_name,
    )
    graph_file.write_text(content)
    console.print(f"[green]Created:[/green] {graph_file}")

    # Update config
    if "graphs" not in config:
        config["graphs"] = {}
    config["graphs"][name] = f"./{graph_file}:graph"

    with config_path.open("w") as f:
        json.dump(config, f, indent=2)
    console.print(f"[green]Updated:[/green] {CONFIG_FILE}")

    console.print(f"\n[bold green]Success![/bold green] Graph '{name}' added")
    console.print(f"\nEdit your graph at: {graph_file}")
