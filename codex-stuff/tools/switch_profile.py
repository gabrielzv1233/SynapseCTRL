import argparse
import json

from _synapse import (
    build_devices,
    connect,
    renderer_state,
    select_by_name_or_id,
    switch_profile,
    wait_for_profile,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Test Synapse software-profile switching through its internal systray path.")
    p.add_argument("device", help="Device name substring, normalized id, productId, or containerId")
    p.add_argument("profile", help="Profile name or GUID")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9229)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    with connect(args.host, args.port) as inspector:
        devices = build_devices(renderer_state(inspector))
        device = select_by_name_or_id(
            devices,
            args.device,
            id_keys=("id", "productId", "containerId"),
        )
        if not device:
            raise SystemExit(f"Device not uniquely found: {args.device}")

        profile = select_by_name_or_id(
            device["profiles"],
            args.profile,
            id_keys=("guid",),
        )
        if not profile:
            raise SystemExit(f"Profile not uniquely found: {args.profile}")

        result = {
            "device": device,
            "profile": profile,
            "alreadyActive": device.get("activeProfile") == profile["guid"],
            "sent": False,
            "verified": False,
        }
        if not args.dry_run and not result["alreadyActive"]:
            result["transport"] = switch_profile(inspector, device, profile)
            result["sent"] = bool(result["transport"].get("sent"))
            result["verified"] = wait_for_profile(inspector, device, profile["guid"])
        elif result["alreadyActive"]:
            result["verified"] = True

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Device:  {device['name']}")
        print(f"Profile: {profile['name']} [{profile['guid']}]")
        print(f"Channel: {device['channel']}")
        print(f"Container: {device['containerId']}")
        if args.dry_run:
            print("DRY RUN: no message sent")
        elif result["alreadyActive"]:
            print("Already active")
        else:
            print(f"Sent: {result['sent']}  Verified: {result['verified']}")
    return 0 if result["verified"] or args.dry_run else 3


if __name__ == "__main__":
    raise SystemExit(main())
