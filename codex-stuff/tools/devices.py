import argparse
import json

from _synapse import build_devices, connect, renderer_state


def main() -> int:
    p = argparse.ArgumentParser(description="Discover normalized Synapse devices and software profiles.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9229)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    with connect(args.host, args.port) as inspector:
        devices = build_devices(renderer_state(inspector))

    if args.json:
        print(json.dumps(devices, indent=2, ensure_ascii=False))
        return 0

    for device in devices:
        print(device["name"])
        print(f"  id:         {device['id']}")
        print(f"  vendorId:   {device['vendorId']}")
        print(f"  productId:  {device['productId']}")
        print(f"  container:  {device['containerId']}")
        print(f"  channel:    {device['channel']}")
        print(f"  state:      {device['storageKey']}")
        print(f"  profiles:   {device['profileSource']}")
        for profile in device["profiles"]:
            active = " *" if profile["guid"] == device["activeProfile"] else ""
            print(f"    - {profile['name']} [{profile['guid']}]{active}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
