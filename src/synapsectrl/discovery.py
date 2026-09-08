"""Normalize Synapse renderer snapshots without trusting cached device identities.

Middleware names establish live identity. Storage only supplies profile state and
metadata; ambiguous shared product state is never used to verify a device switch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from .models import Device, Profile

_MIDDLEWARE = re.compile(r"^(?:win-)?usb_(\d+)_(\d+)_(\{[0-9a-f-]+\})_mw$", re.I)
_FAMILY = re.compile(r"^synapse_(\d+)(?:_|$)", re.I)
_CONTAINER = re.compile(r"^\{?([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\}?$", re.I)
_ACTIVE_KEYS = {
    "activeprofile", "activeprofileguid", "activeprofileid", "currentprofile",
    "currentprofileguid", "currentprofileid", "selectedprofileguid",
}
_ID_KEYS = ("guid", "profileguid", "profileid", "id")
_NAME_KEYS = ("productname", "devicename", "displayname", "editionname", "name")


@dataclass
class Discovery:
    devices: list[Device] = field(default_factory=list)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Scope:
    vendor: int | None = None
    product: int | None = None
    container: str | None = None
    serial: str | None = None
    invalid: bool = False


@dataclass
class _Identity:
    vendor: int
    product: int
    container: str
    channel: str
    renderer: Any
    raw_name: str
    serial: str | None = None
    name: str | None = None

    @property
    def id(self) -> str:
        return f"razer:{self.vendor}:{self.product}:{_container(self.container)}"


@dataclass
class _Node:
    path: tuple[str | int, ...]
    scope: _Scope
    value: dict[str, Any]


@dataclass
class _Candidate:
    source: str
    node: _Node
    profiles: tuple[Profile, ...]
    conflicts: bool = False
    active: str | None = None
    issue: str | None = None
    specificity: int = 0


def _fields(value: dict) -> dict[str, Any]:
    return {str(key).casefold(): item for key, item in value.items()}


def _decode(value: Any) -> Any:
    for _ in range(8):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            break
    return value


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _container(value: str) -> str:
    return value.strip().strip("{}").casefold()


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16 if value.casefold().startswith("0x") else 10)
        except ValueError:
            pass
    return None


def _scope(parent: _Scope, value: dict) -> _Scope:
    fields = _fields(value)
    changes: dict[str, Any] = {}
    for attribute, names in (
        ("vendor", ("vendorid", "vid")),
        ("product", ("productid", "pid")),
        ("container", ("containerid", "devicecontainerid")),
        ("serial", ("serialnumber", "serialno")),
    ):
        for name in names:
            if fields.get(name) in (None, ""):
                continue
            raw = fields[name]
            parsed = _integer(raw) if attribute in ("vendor", "product") else _text(raw)
            if parsed is None:
                changes["invalid"] = True
            else:
                changes[attribute] = _container(parsed) if attribute == "container" else parsed
            break
    return replace(parent, **changes)


def _nodes(value: Any, initial: _Scope) -> list[_Node]:
    """Decode nested persisted reducers too, with bounded traversal for schema drift."""
    nodes: list[_Node] = []
    pending = [(value, (), initial)]
    visited = 0
    while pending and visited < 100_000:
        current, path, scope = pending.pop()
        visited += 1
        if len(path) > 48:
            continue
        current = _decode(current)
        if isinstance(current, dict):
            scope = _scope(scope, current)
            nodes.append(_Node(path, scope, current))
            for key, child in reversed(list(current.items())):
                child_scope = scope
                if isinstance(key, str) and _CONTAINER.fullmatch(key):
                    child_scope = replace(scope, container=_container(key))
                elif path and str(path[-1]).casefold() in {"devicemetadatas", "devicesbyserial"}:
                    child_scope = replace(scope, serial=str(key))
                pending.append((child, (*path, str(key)), child_scope))
        elif isinstance(current, list):
            pending.extend((child, (*path, index), scope) for index, child in reversed(list(enumerate(current))))
    return nodes


def _matches(scope: _Scope, identity: _Identity) -> bool:
    return not scope.invalid and all((
        scope.vendor is None or scope.vendor == identity.vendor,
        scope.product is None or scope.product == identity.product,
        scope.container is None or scope.container == _container(identity.container),
        scope.serial is None or identity.serial is not None and scope.serial.casefold() == identity.serial.casefold(),
    ))


def _unique(scope: _Scope, identity: _Identity, identities: list[_Identity]) -> bool:
    return _matches(scope, identity) and sum(_matches(scope, other) for other in identities) == 1


def _localized(value: Any) -> str | None:
    value = _decode(value)
    if isinstance(value, dict):
        fields = _fields(value)
        return next((_text(fields[key]) for key in ("en", "en-us", "en-gb") if _text(fields.get(key))), None)
    return _text(value)


def _enrich(identity: _Identity, identities: list[_Identity], nodes: list[_Node], *, connected_info: bool = False) -> None:
    names: list[tuple[tuple[int, int], str]] = []
    serials: list[tuple[tuple[int, int], str]] = []
    for node in nodes:
        # A serial cannot establish its own link to a live middleware instance.
        if not connected_info and node.scope.serial is not None and not _matches(node.scope, identity):
            continue
        scope = replace(node.scope, serial=None)
        if not _unique(scope, identity, identities) or scope.product is None and scope.container is None:
            continue
        fields = _fields(node.value)
        rank = (int(scope.container is not None), int(scope.vendor is not None))
        serial = _text(fields.get("serialnumber")) or _text(fields.get("serialno"))
        name_keys = _NAME_KEYS if connected_info else _NAME_KEYS[:-1]
        name = next((_localized(fields[key]) for key in name_keys if _localized(fields.get(key))), None)
        if serial:
            serials.append((rank, serial))
        if name:
            names.append((rank, name))
    for attribute, choices in (("name", names), ("serial", serials)):
        if getattr(identity, attribute) is not None or not choices:
            continue
        best = max(rank for rank, _ in choices)
        values = {value.casefold(): value for rank, value in choices if rank == best}
        if len(values) == 1:
            setattr(identity, attribute, next(iter(values.values())))


def _profiles(node: _Node) -> tuple[tuple[Profile, ...], bool]:
    raw = _decode(_fields(node.value).get("profiles"))
    if not isinstance(raw, list):
        return (), False
    found: dict[str, Profile] = {}
    conflicts = False
    for value in raw:
        value = _decode(value)
        if not isinstance(value, dict):
            continue
        fields = _fields(value)
        profile_id = next((_text(fields[key]) for key in _ID_KEYS if _text(fields.get(key))), None)
        name = _text(fields.get("name")) or _text(fields.get("profilename"))
        if not profile_id or not name:
            continue
        old = found.get(profile_id.casefold())
        if old is not None and old.name != name:
            conflicts = True
        found.setdefault(profile_id.casefold(), Profile(id=profile_id, name=name))
    return tuple(found.values()), conflicts


def _active_values(node: _Node) -> list[str]:
    found = []
    for key, value in _fields(node.value).items():
        if key not in _ACTIVE_KEYS:
            continue
        value = _decode(value)
        if isinstance(value, dict):
            fields = _fields(value)
            value = next((fields[name] for name in _ID_KEYS if _text(fields.get(name))), None)
        if text := _text(value):
            found.append(text)
    return found


def _within(path: tuple, parent: tuple) -> bool:
    return path[:len(parent)] == parent


def _pair(candidate: _Candidate, candidates: list[_Candidate], nodes: list[_Node], identity: _Identity, identities: list[_Identity]) -> None:
    """Prefer the nearest active field; never combine unrelated profile reducers."""
    path = candidate.node.path
    usable = [node for node in nodes if _matches(node.scope, identity)]
    for depth in range(len(path), -1, -1):
        ancestor = path[:depth]
        if depth < len(path) and sum(_within(other.node.path, ancestor) for other in candidates) > 1:
            break
        direct = [node for node in usable if node.path == ancestor and _active_values(node)]
        descendants = [
            node for node in usable
            if _within(node.path, ancestor) and _active_values(node)
            and not any(other is not candidate and _within(node.path, other.node.path) for other in candidates)
        ]
        # A product-wide current field is insufficient with two identical
        # devices. Their attributed container/serial metadata can still resolve
        # the shared list without treating the product-wide field as evidence.
        related = direct if any(_unique(node.scope, identity, identities) for node in direct) else descendants
        if not related:
            continue
        attributable = [node for node in related if _unique(node.scope, identity, identities)]
        if not attributable:
            candidate.issue = "Active profile state is shared by multiple devices and cannot be attributed to this device."
            return
        values = {value.casefold() for node in attributable for value in _active_values(node)}
        if len(values) != 1:
            candidate.issue = "Conflicting active profile fields exist in the selected profile scope."
            return
        active = next(iter(values))
        profile = next((profile for profile in candidate.profiles if profile.id.casefold() == active), None)
        if profile is None:
            candidate.issue = "The active profile identifier is absent from the discovered profile list."
            return
        candidate.active = profile.id
        candidate.specificity = max(candidate.specificity, *(int(node.scope.container is not None or node.scope.serial is not None) for node in attributable))
        return
    candidate.issue = "No active profile could be paired with the discovered profile list."


def _rank(candidate: _Candidate) -> tuple[int, int, int]:
    key = candidate.source.casefold()
    source_rank = 1
    if re.fullmatch(r"synapse_\d+(?:_\{[0-9a-f-]+\})?", key):
        source_rank = 2
    context = key + "/" + "/".join(map(str, candidate.node.path)).casefold()
    if any(word in context for word in ("stack", "history", "backup", "archive")):
        source_rank = 0
    return candidate.specificity, source_rank, len(candidate.profiles)


def normalize(state: dict[str, Any]) -> Discovery:
    """Return durable device models and internal diagnostics for a renderer snapshot."""
    result = Discovery()
    raw_renderers = state.get("renderers", []) if isinstance(state, dict) else []
    if not isinstance(raw_renderers, list):
        result.warnings.append("Renderer enumeration returned an unexpected schema.")
        return result
    identities: list[_Identity] = []
    storage: dict[str, list[Any]] = {}
    seen: set[str] = set()
    for renderer in raw_renderers:
        if not isinstance(renderer, dict):
            result.warnings.append("Ignored a malformed renderer entry.")
            continue
        if renderer.get("error"):
            result.warnings.append(f"Renderer {renderer.get('id', '?')} could not be inspected.")
        name = _text(renderer.get("windowName")) or ""
        if match := _MIDDLEWARE.fullmatch(name):
            vendor, product, container = match.groups()
            identity = _Identity(int(vendor), int(product), container, re.sub(r"^win-", "", name, flags=re.I), renderer.get("id"), name)
            if identity.id not in seen:
                seen.add(identity.id)
                identities.append(identity)
        elif re.match(r"^(?:win-)?usb_", name, re.I) and name.casefold().endswith("_mw"):
            result.warnings.append(f"Unrecognized middleware identity: {name}")
        values = renderer.get("values")
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if not isinstance(key, str):
                continue
            if key.casefold() != "connecteddeviceinfo" and not _FAMILY.match(key):
                continue
            value = _decode(value)
            variants = storage.setdefault(key, [])
            if value not in variants:
                variants.append(value)

    documents: list[tuple[str, list[_Node]]] = []
    info_nodes: list[_Node] = []
    for key, variants in storage.items():
        if len(variants) > 1:
            result.warnings.append(f"Storage key {key} changed between renderer snapshots.")
        family = _FAMILY.match(key)
        scope = _Scope(product=int(family.group(1))) if family else _Scope()
        if family:
            suffix = key[family.end(1):].lstrip("_")
            qualifier = suffix.split("}", 1)[0] + "}" if suffix.startswith("{") else suffix
            if _CONTAINER.fullmatch(qualifier):
                scope = replace(scope, container=_container(qualifier))
            if not any(_matches(scope, identity) for identity in identities):
                result.warnings.append(f"Cached storage {key} has no matching live middleware device.")
        for value in variants:
            if not isinstance(value, (dict, list)):
                result.warnings.append(f"Storage key {key} is not a readable JSON object or array.")
                continue
            nodes = _nodes(value, scope)
            if family:
                documents.append((key, nodes))
            else:
                info_nodes.extend(nodes)

    for identity in identities:
        _enrich(identity, identities, info_nodes, connected_info=True)
    # Metadata collection precedes active-state matching, so serial-qualified
    # state can be resolved independently of storage-key enumeration order.
    metadata = [
        node for _, nodes in documents for node in nodes
        if "profiles" not in tuple(str(part).casefold() for part in node.path)
    ]
    for identity in identities:
        _enrich(identity, identities, metadata)
    for identity in sorted(identities, key=lambda item: item.id):
        candidates: list[_Candidate] = []
        storage_keys = []
        for source, nodes in documents:
            if int(_FAMILY.match(source).group(1)) != identity.product:
                continue
            storage_keys.append(source)
            relevant = [node for node in nodes if _matches(node.scope, identity)]
            local = []
            for node in relevant:
                profiles, conflicts = _profiles(node)
                if profiles:
                    local.append(_Candidate(source, node, profiles, conflicts, specificity=int(node.scope.container is not None or node.scope.serial is not None)))
            for candidate in local:
                _pair(candidate, local, relevant, identity, identities)
            candidates.extend(local)

        selected = None
        issue = "No software profiles were discovered for this live middleware device."
        if candidates:
            best_rank = max(map(_rank, candidates))
            strongest = [candidate for candidate in candidates if _rank(candidate) == best_rank]
            selected = strongest[0]
            signatures = {(tuple(sorted((profile.id.casefold(), profile.name) for profile in candidate.profiles)), candidate.active, candidate.issue, candidate.conflicts) for candidate in strongest}
            if len(signatures) > 1:
                issue = "Multiple equally strong profile states disagree; device control is unavailable until discovery is unambiguous."
            elif selected.conflicts:
                issue = "Conflicting names exist for the same profile identifier."
            else:
                issue = selected.issue
        active = selected.active if selected and issue is None else None
        profiles = tuple(replace(profile, active=profile.id == active) for profile in selected.profiles) if selected else ()
        device = Device(
            id=identity.id, name=identity.name or f"Razer device PID {identity.product}",
            vendor_id=identity.vendor, product_id=identity.product, container_id=identity.container,
            serial_number=identity.serial, connected=True, profiles_supported=bool(profiles),
            controllable=issue is None, unavailable_reason=issue, active_profile_id=active, profiles=profiles,
        )
        result.devices.append(device)
        result.details[device.id] = {
            "channel": identity.channel, "rendererId": identity.renderer,
            "profileSource": selected.source if selected else None,
            "profilePath": list(selected.node.path) if selected else None,
            "storageKeys": sorted(set(storage_keys)), "rawWindowName": identity.raw_name,
            "issues": [issue] if issue else [],
        }
    return result
