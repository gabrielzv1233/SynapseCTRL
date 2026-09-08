"""CLI runner for the optional SynapseCTRL HTTP API."""

from __future__ import annotations

import argparse
import ipaddress
import math
import os
import secrets
import sys
from typing import Sequence

from .service import SynapseService


_HTTP_DEPENDENCIES = {"starlette", "uvicorn", "anyio", "click", "h11"}
_HTTP_TOKEN_ENV = "SYNAPSECTRL_HTTP_TOKEN"


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


def _token(value: str) -> str:
    if (
        not value
        or not value.isascii()
        or any(character.isspace() for character in value)
    ):
        raise argparse.ArgumentTypeError(
            "must be nonempty ASCII and contain no whitespace"
        )
    return value


def _is_loopback(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def build_serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synapsectrl serve",
        description=(
            "Run the optional SynapseCTRL REST/SSE API using Starlette and Uvicorn. "
            "The server binds to loopback by default."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP listen address (default: 127.0.0.1)",
    )
    parser.add_argument("--port", type=_port, default=8765, help="HTTP listen port (default: 8765)")
    parser.add_argument(
        "--inspector-port",
        type=_port,
        default=9229,
        help="Razer Synapse inspector port (default: 9229)",
    )
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
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument(
        "--token",
        type=_token,
        metavar="TOKEN",
        help=(
            "require this Bearer token for /v1 routes; if omitted, "
            f"{_HTTP_TOKEN_ENV} is used when set"
        ),
    )
    auth.add_argument(
        "--generate-token",
        action="store_true",
        help="generate a strong one-time Bearer token for this server process",
    )
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="Uvicorn log level (default: info)",
    )
    parser.add_argument(
        "--no-access-log",
        action="store_true",
        help="disable Uvicorn's per-request access log",
    )
    return parser


def _missing_http_message() -> str:
    return (
        "HTTP support is not installed. Install the optional dependencies with "
        "'uv tool install \"SynapseCTRL[http]\"' or 'pip install \"SynapseCTRL[http]\"'."
    )


def _resolve_token(args) -> str | None:
    if args.generate_token:
        token = secrets.token_urlsafe(32)
        print(f"Generated HTTP Bearer token: {token}", file=sys.stderr)
        return token

    token = args.token
    if token is None:
        token = os.environ.get(_HTTP_TOKEN_ENV)
    if token is None:
        return None

    try:
        return _token(token)
    except argparse.ArgumentTypeError as error:
        raise ValueError(f"{_HTTP_TOKEN_ENV}: {error}") from error


def main(argv: Sequence[str] | None = None) -> int:
    args = build_serve_parser().parse_args(argv)

    try:
        token = _resolve_token(args)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    try:
        import uvicorn
        from .http_api import create_app
    except ModuleNotFoundError as error:
        root_name = (error.name or "").split(".", 1)[0]
        if root_name in _HTTP_DEPENDENCIES:
            print(f"Error: {_missing_http_message()}", file=sys.stderr)
            return 2
        raise

    if not _is_loopback(args.host):
        if token is None:
            warning = (
                "WARNING: SynapseCTRL is listening on a non-loopback address without authentication. "
                "Anyone who can reach this port may be able to inspect state or switch Synapse profiles."
            )
        else:
            warning = (
                "WARNING: SynapseCTRL is listening on a non-loopback address with Bearer authentication, "
                "but the built-in server uses plain HTTP. Do not send the token across an untrusted network; "
                "use a trusted network or a TLS-terminating reverse proxy."
            )
        print(warning, file=sys.stderr)

    service = SynapseService(
        port=args.inspector_port,
        timeout=args.connect_timeout,
        poll_interval=args.poll_interval,
        unavailable_interval=args.unavailable_interval,
    )
    app = create_app(service, token=token)
    try:
        service.start()
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            access_log=not args.no_access_log,
        )
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        service.close()
