"""Init command for OLG CLI."""

import os
import shutil
from pathlib import Path
from typing import Optional

import typer
from jinja2 import Environment, FileSystemLoader
from rich.console import Console

console = Console()

# Available templates
TEMPLATES = {
    "basic-agent": "Basic ReAct agent with tool calling",
    "hitl-agent": "Agent with human-in-the-loop interrupts",
    "a2a-agent": "A2A Protocol compatible agent",
}

# Template directory
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def init(
    path: Optional[Path] = typer.Argument(
        None,
        help="Path where to create the project",
    ),
    template: str = typer.Option(
        "basic-agent",
        "--template",
        "-t",
        help="Template to use for scaffolding",
    ),
    list_templates: bool = typer.Option(
        False,
        "--list-templates",
        "-l",
        help="List available templates",
    ),
) -> None:
    """Initialize a new Open LangGraph project."""
    # List templates mode
    if list_templates:
        console.print("\n[bold]Available Templates:[/bold]\n")
        for name, description in TEMPLATES.items():
            console.print(f"  [cyan]{name}[/cyan] - {description}")
        console.print()
        raise typer.Exit(code=0)

    # Require path if not listing templates
    if path is None:
        console.print("[red]Error:[/red] Please specify a project path")
        console.print("Usage: olg init <path> [--template <template>]")
        raise typer.Exit(code=1)

    # Validate template
    if template not in TEMPLATES:
        console.print(f"[red]Error:[/red] Unknown template '{template}'")
        console.print(f"Available templates: {', '.join(TEMPLATES.keys())}")
        raise typer.Exit(code=1)

    # Check if path exists and is not empty
    if path.exists():
        if any(path.iterdir()):
            console.print(
                f"[red]Error:[/red] Directory '{path}' exists and is not empty"
            )
            raise typer.Exit(code=1)
    else:
        path.mkdir(parents=True)

    # Extract project name from path
    project_name = path.name
    graph_name = project_name.replace("-", "_").replace(" ", "_").lower()

    # Set up Jinja2 environment
    template_path = TEMPLATE_DIR / template
    if not template_path.exists():
        console.print(f"[red]Error:[/red] Template '{template}' not found")
        raise typer.Exit(code=1)

    env = Environment(loader=FileSystemLoader(str(template_path)))

    # Template context
    context = {
        "project_name": project_name,
        "graph_name": graph_name,
    }

    # Process template files
    console.print(f"\n[bold]Creating project:[/bold] {project_name}\n")

    for root, dirs, files in os.walk(template_path):
        rel_root = Path(root).relative_to(template_path)
        target_root = path / rel_root

        # Create directories
        for d in dirs:
            target_dir = target_root / d
            target_dir.mkdir(parents=True, exist_ok=True)

        # Process files
        for f in files:
            src_file = Path(root) / f
            rel_file = rel_root / f

            # Handle Jinja2 templates
            if f.endswith(".j2"):
                target_file = target_root / f[:-3]  # Remove .j2 extension
                template_obj = env.get_template(str(rel_file))
                content = template_obj.render(**context)
                target_file.write_text(content)
                console.print(f"  [green]Created:[/green] {target_file.relative_to(path)}")
            else:
                # Copy non-template files as-is
                target_file = target_root / f
                shutil.copy2(src_file, target_file)
                console.print(f"  [green]Created:[/green] {target_file.relative_to(path)}")

    # Create graphs directory if not exists
    graphs_dir = path / "graphs"
    graphs_dir.mkdir(exist_ok=True)

    console.print(f"\n[bold green]Success![/bold green] Project created at {path}")
    console.print("\nNext steps:")
    console.print(f"  cd {path}")
    console.print("  cp .env.example .env")
    console.print("  # Edit .env with your API keys")
    console.print("  olg dev")
