"""Optional Starlette REST API backed by the persistent SynapseCTRL service."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import math
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import __version__
from .errors import SynapseError
from .service import SynapseService


HTTP_API_VERSION = "1"
_LOG = logging.getLogger("synapsectrl.http")

_ERROR_STATUS = {
    "invalid_argument": 400,
    "invalid_json": 400,
    "device_not_found": 404,
    "profile_not_found": 404,
    "ambiguous_device": 409,
    "ambiguous_profile": 409,
    "device_unavailable": 503,
    "inspector_unreachable": 503,
    "transport_lost": 503,
    "verification_timeout": 504,
}


def _envelope(data: Any) -> dict[str, Any]:
    return {"apiVersion": HTTP_API_VERSION, "data": data}


def _error_envelope(error: SynapseError) -> dict[str, Any]:
    return {"apiVersion": HTTP_API_VERSION, "error": error.to_dict()}


def _status_for_error(error: SynapseError) -> int:
    return _ERROR_STATUS.get(error.code, 500)


def _bool(value: Any, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SynapseError("invalid_argument", f"{name} must be a boolean.")
    return value


def _positive_seconds(value: Any, name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise SynapseError("invalid_argument", f"{name} must be a positive number of seconds.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SynapseError("invalid_argument", f"{name} must be a positive number of seconds.") from exc
    if not math.isfinite(result) or result <= 0:
        raise SynapseError("invalid_argument", f"{name} must be a finite number greater than zero.")
    return result


async def _unexpected_error(request: Request, error: Exception) -> JSONResponse:
    _LOG.exception("Unhandled SynapseCTRL HTTP error", exc_info=error)
    payload = {
        "apiVersion": HTTP_API_VERSION,
        "error": {
            "code": "internal_error",
            "message": "An unexpected server error occurred.",
            "details": {},
        },
    }
    return JSONResponse(payload, status_code=500)


class HttpApi:
    """HTTP endpoint implementation separated from server/process lifecycle."""

    def __init__(self, service: SynapseService) -> None:
        self.service = service

    async def _run(self, function, *args, **kwargs) -> JSONResponse:
        try:
            result = await run_in_threadpool(function, *args, **kwargs)
            return JSONResponse(_envelope(result))
        except SynapseError as error:
            return JSONResponse(_error_envelope(error), status_code=_status_for_error(error))

    async def root(self, request: Request) -> JSONResponse:
        return JSONResponse(
            _envelope(
                {
                    "name": "SynapseCTRL",
                    "version": __version__,
                    "transport": "http",
                    "apiVersion": HTTP_API_VERSION,
                    "endpoints": {
                        "status": "/v1/status",
                        "state": "/v1/state",
                        "devices": "/v1/devices",
                        "refresh": "/v1/refresh",
                    },
                }
            )
        )

    async def status(self, request: Request) -> JSONResponse:
        return await self._run(lambda: self.service.status().to_dict())

    async def state(self, request: Request) -> JSONResponse:
        return JSONResponse(_envelope(self.service.state()))

    async def refresh(self, request: Request) -> JSONResponse:
        return await self._run(lambda: [device.to_dict() for device in self.service.refresh()])

    async def devices(self, request: Request) -> JSONResponse:
        return await self._run(
            lambda: [device.to_dict() for device in self.service.list_devices(refresh=True)]
        )

    async def profiles(self, request: Request) -> JSONResponse:
        device = request.path_params["device"]
        return await self._run(
            lambda: [profile.to_dict() for profile in self.service.list_profiles(device)]
        )

    async def active_profile(self, request: Request) -> JSONResponse:
        device = request.path_params["device"]

        def load() -> dict[str, Any] | None:
            profiles = self.service.list_profiles(device)
            active = next((profile for profile in profiles if profile.active), None)
            return active.to_dict() if active is not None else None

        return await self._run(load)

    async def activate_profile(self, request: Request) -> JSONResponse:
        device = request.path_params["device"]
        profile = request.path_params["profile"]
        try:
            body = await request.body()
            if not body:
                params: dict[str, Any] = {}
            else:
                try:
                    parsed = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise SynapseError("invalid_json", "Request body must contain valid JSON.") from exc
                if not isinstance(parsed, dict):
                    raise SynapseError("invalid_argument", "Request body must be a JSON object.")
                params = parsed

            timeout = _positive_seconds(params.get("timeout"), "timeout", 5.0)
            verify = _bool(params.get("verify"), "verify", True)
            result = await run_in_threadpool(
                self.service.switch_profile,
                device,
                profile,
                timeout=timeout,
                verify=verify,
            )
            return JSONResponse(_envelope(result.to_dict()))
        except SynapseError as error:
            return JSONResponse(_error_envelope(error), status_code=_status_for_error(error))


def create_app(service: SynapseService | None = None, **service_options: Any) -> Starlette:
    """Create the ASGI app. A supplied service is useful for embedding and tests."""
    owned_service = service is None
    service = service or SynapseService(**service_options)
    api = HttpApi(service)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        service.start()
        try:
            yield
        finally:
            if owned_service:
                service.close()

    routes = [
        Route("/", api.root, methods=["GET"]),
        Route("/v1/status", api.status, methods=["GET"]),
        Route("/v1/state", api.state, methods=["GET"]),
        Route("/v1/refresh", api.refresh, methods=["POST"]),
        Route("/v1/devices", api.devices, methods=["GET"]),
        Route("/v1/devices/{device}/profiles", api.profiles, methods=["GET"]),
        Route("/v1/devices/{device}/active-profile", api.active_profile, methods=["GET"]),
        Route(
            "/v1/devices/{device}/profiles/{profile}/activate",
            api.activate_profile,
            methods=["POST"],
        ),
    ]
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={Exception: _unexpected_error},
    )
    app.state.synapse_service = service
    app.state.synapse_api = api
    return app
