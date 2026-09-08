"""Persistent SynapseCTRL service core shared by long-lived transports."""

from __future__ import annotations

from collections.abc import Callable
import threading
import time
from typing import Any

from .client import SynapseClient
from .errors import SynapseError
from .models import Device, Profile, Status, SwitchResult


EventHandler = Callable[[dict[str, Any]], None]


def _positive_interval(value: float, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SynapseError("invalid_argument", f"{name} must be a positive number of seconds.") from exc
    if result <= 0:
        raise SynapseError("invalid_argument", f"{name} must be greater than zero.")
    return result


class SynapseService:
    """Keep one SynapseClient alive and maintain a small observable state cache.

    The service owns one client, serializes refreshes, and optionally runs a
    watcher thread. Transports such as the stdio bridge and HTTP server should
    use this layer instead of implementing their own polling/reconnect logic.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 9229,
        timeout: float = 8.0,
        poll_interval: float = 0.75,
        unavailable_interval: float = 2.0,
        client: SynapseClient | None = None,
    ) -> None:
        self.poll_interval = _positive_interval(poll_interval, "poll interval")
        self.unavailable_interval = _positive_interval(unavailable_interval, "unavailable interval")
        self._client = client or SynapseClient(host=host, port=port, timeout=timeout)
        self._state_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._callbacks: list[EventHandler] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "starting"
        self._devices: tuple[Device, ...] = ()
        self._last_error: dict[str, Any] | None = None
        self._updated_at_ms: int | None = None

    def __enter__(self) -> SynapseService:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        """Start the background watcher. Safe to call more than once."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._watch_loop,
                name="SynapseCTRLService",
                daemon=True,
            )
            self._thread.start()

    def close(self) -> None:
        """Stop watching and close the persistent inspector connection."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(self.unavailable_interval, 2.0) + 1.0)
        self._client.close()
        with self._state_lock:
            self._thread = None

    def subscribe(self, callback: EventHandler) -> Callable[[], None]:
        """Subscribe to service events and return an unsubscribe callback."""
        if not callable(callback):
            raise SynapseError("invalid_argument", "event callback must be callable.")
        with self._state_lock:
            self._callbacks.append(callback)

        def unsubscribe() -> None:
            with self._state_lock:
                try:
                    self._callbacks.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data}
        with self._state_lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            try:
                callback(payload)
            except Exception:
                # A transport must not be able to kill the service watcher.
                continue

    def _watch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:
                # refresh() already records SynapseError failures. Unexpected
                # failures are isolated so a long-lived bridge does not die.
                pass
            with self._state_lock:
                interval = self.poll_interval if self._state == "ready" else self.unavailable_interval
            self._stop.wait(interval)

    @staticmethod
    def _device_map(devices: tuple[Device, ...]) -> dict[str, Device]:
        return {device.id: device for device in devices}

    def _apply_ready(self, devices: tuple[Device, ...]) -> None:
        with self._state_lock:
            previous_state = self._state
            previous_devices = self._devices
            previous_map = self._device_map(previous_devices)
            current_map = self._device_map(devices)
            self._state = "ready"
            self._devices = devices
            self._last_error = None
            self._updated_at_ms = int(time.time() * 1000)

        if previous_state != "ready":
            self._emit("synapse.available", {"state": "ready"})

        if set(previous_map) != set(current_map):
            self._emit("devices.changed", {"deviceIds": list(current_map)})

        for device_id, current in current_map.items():
            previous = previous_map.get(device_id)
            if previous is None:
                continue
            if previous.active_profile_id != current.active_profile_id:
                self._emit(
                    "profile.changed",
                    {
                        "deviceId": device_id,
                        "previousProfileId": previous.active_profile_id,
                        "profileId": current.active_profile_id,
                    },
                )
            elif (
                previous.controllable != current.controllable
                or previous.connected != current.connected
                or previous.profiles != current.profiles
                or previous.name != current.name
            ):
                self._emit("device.changed", {"deviceId": device_id, "device": current.to_dict()})

    def _apply_unavailable(self, error: SynapseError) -> None:
        error_dict = error.to_dict()
        with self._state_lock:
            previous_state = self._state
            previous_error = self._last_error
            self._state = "unavailable"
            self._devices = ()
            self._last_error = error_dict
            self._updated_at_ms = int(time.time() * 1000)
        if previous_state != "unavailable" or previous_error != error_dict:
            self._emit("synapse.unavailable", {"state": "unavailable", "error": error_dict})

    def refresh(self) -> tuple[Device, ...]:
        """Refresh the state cache immediately and return discovered devices."""
        with self._refresh_lock:
            try:
                devices = tuple(self._client.list_devices())
            except SynapseError as error:
                self._apply_unavailable(error)
                raise
            self._apply_ready(devices)
            return devices

    def state(self) -> dict[str, Any]:
        """Return the latest cached state without performing I/O."""
        with self._state_lock:
            return {
                "state": self._state,
                "synapseAvailable": self._state == "ready",
                "devices": [device.to_dict() for device in self._devices],
                "error": dict(self._last_error) if self._last_error is not None else None,
                "updatedAtMs": self._updated_at_ms,
            }

    def list_devices(self, *, refresh: bool = True) -> tuple[Device, ...]:
        if refresh:
            return self.refresh()
        with self._state_lock:
            return self._devices

    def list_profiles(self, device: str) -> tuple[Profile, ...]:
        """Read profiles using the persistent client, preserving SDK selection rules."""
        try:
            profiles = tuple(self._client.list_profiles(device))
        except SynapseError as error:
            if error.code in {"inspector_unreachable", "transport_lost"}:
                self._apply_unavailable(error)
            raise
        return profiles

    def status(self) -> Status:
        """Return the full SDK status report using the persistent client."""
        return self._client.status()

    def switch_profile(
        self,
        device: str,
        profile: str,
        *,
        timeout: float = 5.0,
        verify: bool = True,
    ) -> SwitchResult:
        """Switch through SynapseCTRL, then refresh cache/events immediately."""
        result = self._client.switch_profile(device, profile, timeout=timeout, verify=verify)
        if result.status in {"verified", "already_active"}:
            try:
                self.refresh()
            except SynapseError:
                # The switch result remains authoritative; the watcher will
                # reconnect and repair cached state independently.
                pass
        return result
