"""Optional Starlette REST API backed by the persistent SynapseCTRL service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import math
import secrets
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import __version__
from .errors import SynapseError
from .service import SynapseService


HTTP_API_VERSION = "1"
SSE_HEARTBEAT_SECONDS = 15.0
SSE_QUEUE_SIZE = 128
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


def _sse_event(event: str, data: Any) -> bytes:
    """Encode one versioned Server-Sent Event frame."""
    payload = json.dumps(
        {"apiVersion": HTTP_API_VERSION, "event": event, "data": data},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        {
            "apiVersion": HTTP_API_VERSION,
            "error": {
                "code": "unauthorized",
                "message": "A valid Bearer token is required.",
                "details": {},
            },
        },
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


class BearerAuthMiddleware:
    """Protect versioned HTTP API routes with a configured Bearer token.

    The root information endpoint remains public so callers can discover the API
    version and whether authentication is enabled. All `/v1` routes require the
    token when this middleware is installed.
    """

    def __init__(self, app, *, token: str) -> None:
        if not token or any(character.isspace() for character in token):
            raise SynapseError(
                "invalid_argument",
                "HTTP bearer token must be nonempty and contain no whitespace.",
            )
        self.app = app
        self.token = token
        self.expected = f"Bearer {token}"

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not (path == "/v1" or path.startswith("/v1/")):
            await self.app(scope, receive, send)
            return

        authorization: str | None = None
        for raw_name, raw_value in scope.get("headers", ()):
            if raw_name.lower() == b"authorization":
                authorization = raw_value.decode("latin-1")
                break

        if authorization is None or not secrets.compare_digest(authorization, self.expected):
            await _unauthorized_response()(scope, receive, send)
            return

        await self.app(scope, receive, send)


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

    def __init__(
        self,
        service: SynapseService,
        *,
        auth_enabled: bool = False,
        event_heartbeat: float = SSE_HEARTBEAT_SECONDS,
        event_queue_size: int = SSE_QUEUE_SIZE,
    ) -> None:
        self.service = service
        self.auth_enabled = bool(auth_enabled)
        self.event_heartbeat = _positive_seconds(
            event_heartbeat,
            "event heartbeat",
            SSE_HEARTBEAT_SECONDS,
        )
        if isinstance(event_queue_size, bool) or not isinstance(event_queue_size, int) or event_queue_size <= 0:
            raise SynapseError("invalid_argument", "event queue size must be a positive integer.")
        self.event_queue_size = event_queue_size

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
                    "authentication": "bearer" if self.auth_enabled else "none",
                    "endpoints": {
                        "status": "/v1/status",
                        "state": "/v1/state",
                        "devices": "/v1/devices",
                        "refresh": "/v1/refresh",
                        "events": "/v1/events",
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

    async def events(self, request: Request) -> StreamingResponse:
        """Stream persistent service events as text/event-stream."""

        async def stream():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.event_queue_size)
            accepting = True

            def enqueue(payload: dict[str, Any]) -> None:
                nonlocal accepting
                if not accepting:
                    return
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

            def on_service_event(payload: dict[str, Any]) -> None:
                if not accepting:
                    return
                try:
                    loop.call_soon_threadsafe(enqueue, payload)
                except RuntimeError:
                    # The request loop is already gone.
                    pass

            unsubscribe = self.service.subscribe(on_service_event)
            try:
                yield _sse_event("service.snapshot", self.service.state())
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        payload = await asyncio.wait_for(
                            queue.get(),
                            timeout=self.event_heartbeat,
                        )
                    except TimeoutError:
                        yield b": keep-alive\n\n"
                        continue

                    event = payload.get("event")
                    data = payload.get("data")
                    if not isinstance(event, str) or not event:
                        continue
                    yield _sse_event(event, data)
            finally:
                accepting = False
                unsubscribe()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


def create_app(
    service: SynapseService | None = None,
    *,
    token: str | None = None,
    **service_options: Any,
) -> Starlette:
    """Create the ASGI app. A supplied service is useful for embedding and tests."""
    if token is not None and (not token or any(character.isspace() for character in token)):
        raise SynapseError(
            "invalid_argument",
            "HTTP bearer token must be nonempty and contain no whitespace.",
        )

    owned_service = service is None
    service = service or SynapseService(**service_options)
    api = HttpApi(service, auth_enabled=token is not None)

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
        Route("/v1/events", api.events, methods=["GET"]),
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
    if token is not None:
        app.add_middleware(BearerAuthMiddleware, token=token)
    app.state.synapse_service = service
    app.state.synapse_api = api
    app.state.auth_enabled = token is not None
    return app
