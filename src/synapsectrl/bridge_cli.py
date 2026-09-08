"""CLI runner for the persistent SynapseCTRL bridge."""

from __future__ import annotations

import argparse
import math
import sys
from typing import Sequence

from .bridge import StdioBridge
from .errors import SynapseError
from .service import SynapseService


def _positive_seconds(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number of seconds") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return result


def _port(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 65535") from exc
    if not 1 <= result <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return result


def _pid(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive process ID") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def build_bridge_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synapsectrl bridge",
        description=(
            "Run a long-lived SynapseCTRL bridge. The default transport is newline-delimited "
            "JSON over stdin/stdout; stdout is reserved for protocol messages."
        ),
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="explicitly select the stdio transport (currently the default)",
    )
    parser.add_argument("--port", type=_port, default=9229, help="loopback inspector port (default: 9229)")
    parser.add_argument(
        "--connect-timeout",
        type=_positive_seconds,
        default=8.0,
        metavar="SECONDS",
        help="inspector operation timeout (default: 8)",
    )
    parser.add_argument(
        "--poll-interval",
        type=_positive_seconds,
        default=0.75,
        metavar="SECONDS",
        help="active-state polling interval while ready (default: 0.75)",
    )
    parser.add_argument(
        "--unavailable-interval",
        type=_positive_seconds,
        default=2.0,
        metavar="SECONDS",
        help="reconnect polling interval while unavailable (default: 2)",
    )
    parser.add_argument(
        "--parent-pid",
        type=_pid,
        metavar="PID",
        help="exit if the owning parent process disappears",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_bridge_parser().parse_args(argv)
    try:
        service = SynapseService(
            port=args.port,
            timeout=args.connect_timeout,
            poll_interval=args.poll_interval,
            unavailable_interval=args.unavailable_interval,
        )
        return StdioBridge(service, parent_pid=args.parent_pid).run()
    except SynapseError as error:
        print(f"Error [{error.code}]: {error.message}", file=sys.stderr)
        return 2 if error.code == "invalid_argument" else 1
    except KeyboardInterrupt:
        return 130
