"""OLG CLI - Open LangGraph command-line interface."""

import typer
from rich.console import Console

from olg.commands.graph import graph_app
from olg.commands.init import init
from olg.commands.validate import validate

app = typer.Typer(
    name="olg",
    help="Open LangGraph CLI - scaffold, develop, and validate LangGraph projects",
    no_args_is_help=True,
)
console = Console()

# Register commands
app.command()(init)
app.command()(validate)
app.add_typer(graph_app)


@app.callback()
def main():
    """Open LangGraph CLI Tool."""
    pass


if __name__ == "__main__":
    app()
