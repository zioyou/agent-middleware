"""OLG CLI - Open LangGraph command-line interface."""

import typer
from rich.console import Console

from olg.commands.validate import validate

app = typer.Typer(
    name="olg",
    help="Open LangGraph CLI - scaffold, develop, and validate LangGraph projects",
    no_args_is_help=True,
)
console = Console()

# Register commands
app.command()(validate)


@app.callback()
def main():
    """Open LangGraph CLI Tool."""
    pass


if __name__ == "__main__":
    app()
