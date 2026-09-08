"""Top-level console entry point with long-lived command routing."""

from __future__ import annotations

import sys

from . import cli
from .bridge_cli import main as bridge_main
from .serve_cli import main as serve_main


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def entrypoint() -> None:
    _configure_streams()
    argv = sys.argv[1:]
    if argv and argv[0] == "bridge":
        raise SystemExit(bridge_main(argv[1:]))
    if argv and argv[0] == "serve":
        raise SystemExit(serve_main(argv[1:]))

    if argv in (["-h"], ["--help"]):
        help_text = cli.build_parser().format_help().rstrip()
        print(help_text)
        print("\nLong-lived commands:")
        print("  bridge              Run the persistent stdio bridge for integrations")
        print("  serve               Run the optional REST API over HTTP")
        print("\nRun 'synapsectrl bridge --help' or 'synapsectrl serve --help' for options.")
        return

    raise SystemExit(cli.main(argv))
