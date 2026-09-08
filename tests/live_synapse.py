"""Opt-in equivalence test against the preserved controller and real Synapse.

Run from the checkout with --switch-roundtrip to authorize the live mutation.
The original profile is restored in finally, including on assertion failures.
All inspection uses the supplied reference/diagnostics rather than new probes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from synapsectrl import SynapseClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import synapse_ctrl as reference  # noqa: E402


def reference_devices():
    target = reference.get_target("127.0.0.1", 9229)
    inspector = reference.Inspector(target["webSocketDebuggerUrl"])
    try:
        inspector.call("Runtime.enable")
        state = reference.get_renderer_state(inspector)
        devices = reference.build_devices(state)
        for device in devices:
            # The preserved prototype takes the first active field from the
            # storage family, which can be a stale profiles_stack. Read its
            # selected profile document through the same reference primitives.
            for renderer in state["renderers"]:
                raw = renderer.get("values", {}).get(device["profileSource"])
                if raw is not None:
                    device["profileSourceActive"] = reference.extract_active_profile(reference.parse_json(raw))
                    break
        return devices
    finally:
        inspector.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="Stable device ID; required when more than one device is controllable")
    parser.add_argument("--switch-roundtrip", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "astra/diagnostics/live-test.json")
    args = parser.parse_args()
    report = {}
    with SynapseClient() as client:
        status = client.status()
        assert status.state == "ready", status.to_dict()
        devices = client.list_devices()
        eligible = [device for device in devices if device.controllable and len(device.profiles) > 1 and (not args.device or device.id == args.device)]
        assert len(eligible) == 1, "Specify --device when more than one eligible device is connected."
        device = eligible[0]
        original = device.active_profile_id
        assert original, "Cannot safely run a roundtrip without the original active profile."
        expected = next(d for d in reference_devices() if d["containerId"].casefold() == device.container_id.casefold())
        assert {(p.id, p.name) for p in device.profiles} == {(p["guid"], p["name"]) for p in expected["profiles"]}
        assert original == expected["profileSourceActive"], "Active state changed during the baseline read; retry the test."
        report.update({"deviceId": device.id, "profileCount": len(device.profiles), "versions": status.versions,
                       "referenceDiscoveryEquivalent": True, "originalProfileId": original,
                       "legacyFamilyActiveProfileId": expected["activeProfile"],
                       "referenceProfileSourceActiveId": expected["profileSourceActive"]})
        if args.switch_roundtrip:
            target = next(profile for profile in device.profiles if profile.id != original)
            try:
                changed = client.switch_profile(device.id, target.id)
                report["sdkSwitch"] = changed.to_dict()
                assert changed.status == "verified", changed.to_dict()
                actual = next(d for d in reference_devices() if d["containerId"].casefold() == device.container_id.casefold())
                assert actual["profileSourceActive"] == target.id, "Reference storage read did not confirm product switch."
                report["referenceVerifiedSwitch"] = True
                already = client.switch_profile(device.id, target.id)
                assert already.status == "already_active" and not already.sent
                report["alreadyActive"] = already.to_dict()
                client.close()
                assert next(d for d in client.list_devices() if d.id == device.id).active_profile_id == target.id
                report["reconnectVerified"] = True
                run = subprocess.run([sys.executable, "-m", "synapsectrl", "switch", device.id, original, "--json"],
                                     cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
                report["cliRestore"] = json.loads(run.stdout)
                assert run.returncode == 0, (run.stdout, run.stderr)
                assert report["cliRestore"]["data"]["status"] == "verified"
            finally:
                restored = client.switch_profile(device.id, original)
                report["restore"] = restored.to_dict()
                assert restored.verified, f"Profile restore failed: {restored.to_dict()}"
                actual = next(d for d in reference_devices() if d["containerId"].casefold() == device.container_id.casefold())
                assert actual["profileSourceActive"] == original, "Reference could not verify original profile restoration."
                report["originalProfileRestored"] = True
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
