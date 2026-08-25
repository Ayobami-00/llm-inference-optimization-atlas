"""Atlas command-line interface."""

from typer import Typer

from atlas import __version__

app = Typer(no_args_is_help=True, help="Validate, run, and explore Atlas evidence.")


@app.command()
def version() -> None:
    """Print the Atlas version."""
    print(__version__)
