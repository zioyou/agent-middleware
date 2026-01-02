"""OLG CLI - Open LangGraph command-line interface."""

import typer
from rich.console import Console

app = typer.Typer(
    name="olg",
    help="Open LangGraph CLI - scaffold, develop, and validate LangGraph projects",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main():
    """Open LangGraph CLI Tool."""
    pass


if __name__ == "__main__":
    app()
