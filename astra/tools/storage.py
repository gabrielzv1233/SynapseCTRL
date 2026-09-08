import argparse
import json

from _synapse import connect, parse_json, renderer_state, shape, unique_storage


def main() -> int:
    p = argparse.ArgumentParser(description="Inspect apps.razer.com localStorage used by Synapse.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9229)
    p.add_argument("--key", help="Print one exact storage key")
    p.add_argument("--contains", help="Filter key names")
    p.add_argument("--raw", action="store_true", help="Do not JSON-decode values")
    p.add_argument("--shape", action="store_true", help="Show compact JSON structure")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = p.parse_args()

    with connect(args.host, args.port) as inspector:
        state = renderer_state(inspector)
    storage = unique_storage(state)

    if args.key:
        if args.key not in storage:
            print(f"Storage key not found: {args.key}")
            return 2
        value = storage[args.key] if args.raw else parse_json(storage[args.key])
        if args.shape:
            value = shape(value)
        if isinstance(value, str) and args.raw:
            print(value)
        else:
            print(json.dumps(value, indent=2, ensure_ascii=False))
        return 0

    rows = []
    for key in sorted(storage):
        if args.contains and args.contains.casefold() not in key.casefold():
            continue
        raw = storage[key]
        parsed = parse_json(raw)
        rows.append(
            {
                "key": key,
                "chars": len(raw),
                "parsedType": type(parsed).__name__,
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['key']:<42} {row['chars']:>8} chars  {row['parsedType']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
