import argparse
import json

from _synapse import connect, electron_probe, get_targets


def main() -> int:
    p = argparse.ArgumentParser(description="Probe Synapse's Node/Electron inspector.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9229)
    args = p.parse_args()

    print("Inspector targets:")
    print(json.dumps(get_targets(args.host, args.port), indent=2))
    print()
    with connect(args.host, args.port) as inspector:
        print("Electron probe:")
        print(json.dumps(electron_probe(inspector), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
