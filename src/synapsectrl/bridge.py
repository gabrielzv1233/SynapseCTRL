"""Newline-delimited JSON bridge for long-lived local integrations."""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, TextIO

import psutil

from . import __version__
from .errors import SynapseError
from .service import SynapseService


BRIDGE_PROTOCOL_VERSION = "1"


class StdioBridge:
    """Serve SynapseCTRL requests over stdin/stdout using one JSON object per line."""

    def __init__(
        self,
        service: SynapseService,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        parent_pid: int | None = None,
    ) -> None:
        self.service = service
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.parent_pid = parent_pid
        self._write_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._unsubscribe = self.service.subscribe(self._on_service_event)
        self._parent_thread: threading.Thread | None = None

    def close(self) -> None:
        self._shutdown.set()
        self._unsubscribe()

    def _write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self._write_lock:
            self.stdout.write(line + "\n")
            self.stdout.flush()

    def _on_service_event(self, payload: dict[str, Any]) -> None:
        self._write({"protocolVersion": BRIDGE_PROTOCOL_VERSION, **payload})

    @staticmethod
    def _request_error(request_id: Any, error: SynapseError) -> dict[str, Any]:
        return {
            "protocolVersion": BRIDGE_PROTOCOL_VERSION,
            "id": request_id,
            "error": error.to_dict(),
        }

    @staticmethod
    def _protocol_error(request_id: Any, code: str, message: str) -> dict[str, Any]:
        return {
            "protocolVersion": BRIDGE_PROTOCOL_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message, "details": {}},
        }

    def handle_request(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._protocol_error(None, "invalid_request", "Each bridge request must be a JSON object.")
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str) or not method:
            return self._protocol_error(request_id, "invalid_request", "Bridge requests require a nonempty method.")
        if not isinstance(params, dict):
            return self._protocol_error(request_id, "invalid_params", "params must be a JSON object.")

        try:
            if method == "hello":
                result = {
                    "protocolVersion": BRIDGE_PROTOCOL_VERSION,
                    "synapseCtrlVersion": __version__,
                    "transport": "stdio",
                    "service": self.service.state(),
                }
            elif method == "service.state":
                result = self.service.state()
            elif method == "service.refresh":
                result = [device.to_dict() for device in self.service.refresh()]
            elif method == "devices.list":
                result = [device.to_dict() for device in self.service.list_devices(refresh=True)]
            elif method == "profiles.list":
                device = params.get("deviceId", params.get("device"))
                if not isinstance(device, str) or not device.strip():
                    raise SynapseError("invalid_argument", "profiles.list requires deviceId.")
                result = [profile.to_dict() for profile in self.service.list_profiles(device)]
            elif method == "status.get":
                result = self.service.status().to_dict()
            elif method == "profile.activate":
                device = params.get("deviceId", params.get("device"))
                profile = params.get("profileId", params.get("profile"))
                if not isinstance(device, str) or not device.strip():
                    raise SynapseError("invalid_argument", "profile.activate requires deviceId.")
                if not isinstance(profile, str) or not profile.strip():
                    raise SynapseError("invalid_argument", "profile.activate requires profileId.")
                timeout = params.get("timeout", 5.0)
                verify = params.get("verify", True)
                result = self.service.switch_profile(device, profile, timeout=timeout, verify=verify).to_dict()
            elif method == "shutdown":
                self._shutdown.set()
                result = {"shuttingDown": True}
            else:
                return self._protocol_error(request_id, "method_not_found", f"Unknown bridge method: {method}")
        except SynapseError as error:
            return self._request_error(request_id, error)
        except (TypeError, ValueError) as error:
            return self._protocol_error(request_id, "invalid_params", str(error))

        return {
            "protocolVersion": BRIDGE_PROTOCOL_VERSION,
            "id": request_id,
            "result": result,
        }

    def _parent_watch_loop(self) -> None:
        assert self.parent_pid is not None
        while not self._shutdown.wait(1.0):
            if psutil.pid_exists(self.parent_pid):
                continue
            self._shutdown.set()
            try:
                self.stdin.close()
            except Exception:
                pass
            return

    def run(self) -> int:
        self.service.start()
        if self.parent_pid is not None:
            if self.parent_pid <= 0:
                raise SynapseError("invalid_argument", "parent PID must be greater than zero.")
            self._parent_thread = threading.Thread(
                target=self._parent_watch_loop,
                name="SynapseCTRLParentWatch",
                daemon=True,
            )
            self._parent_thread.start()

        try:
            for raw_line in self.stdin:
                if self._shutdown.is_set():
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError as error:
                    self._write(self._protocol_error(None, "invalid_json", f"Invalid JSON: {error.msg}"))
                    continue
                response = self.handle_request(request)
                self._write(response)
                if isinstance(request, dict) and request.get("method") == "shutdown":
                    break
            return 0
        finally:
            self.close()
            self.service.close()
