"""Switch with stable IDs or unambiguous names: python examples/switch_profile.py DEVICE PROFILE."""

import argparse
import json
import sys

from synapsectrl import SynapseClient, SynapseError


def main() -> int:
    parser = argparse.ArgumentParser(description="Switch and verify a Synapse software profile.")
    parser.add_argument("device", help="device ID from 'synapsectrl devices' or an unambiguous name")
    parser.add_argument("profile", help="profile GUID from 'synapsectrl profiles DEVICE' or an unambiguous name")
    args = parser.parse_args()
    try:
        with SynapseClient() as client:
            result = client.switch_profile(args.device, args.profile, timeout=5.0)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.verified:
            return 0
        return 3 if result.status == "timeout" else 1
    except SynapseError as error:
        print(json.dumps(error.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
