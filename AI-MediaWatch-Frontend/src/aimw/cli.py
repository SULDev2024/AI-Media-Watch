"""Top-level ``aimw`` command-line interface."""

from __future__ import annotations

import typer

from aimw.collection.cli import collect_app
from aimw.db.cli import db_app
from aimw.entities.cli import entities_app
from aimw.extraction.cli import extract_app
from aimw.feedback.cli import feedback_app
from aimw.graph.cli import graph_app
from aimw.scoring.cli import score_app
from aimw.validation.cli import validation_app
from aimw.workers.cli import queue_app

app = typer.Typer(help="AI Media Watch CLI.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(collect_app, name="collect")
app.add_typer(extract_app, name="extract")
app.add_typer(entities_app, name="entities")
app.add_typer(score_app, name="score")
app.add_typer(graph_app, name="graph")
app.add_typer(queue_app, name="queue")
app.add_typer(feedback_app, name="feedback")
app.add_typer(validation_app, name="validation")


@app.command()
def bot() -> None:
    """Start the Telegram scam-checker bot (long-polling)."""
    from aimw.bot.run import main as bot_main

    bot_main()


def main() -> None:
    """Console-script entry point (``aimw``)."""
    app()


if __name__ == "__main__":
    main()
