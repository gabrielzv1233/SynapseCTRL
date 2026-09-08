import argparse
import json
import platform
import time
from pathlib import Path

from _synapse import (
    build_devices,
    connect,
    electron_probe,
    get_targets,
    parse_json,
    renderer_state,
    shape,
    unique_storage,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Create a compact Synapse diagnostic snapshot for an LLM/developer.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9229)
    p.add_argument("--out", default="synapse-diagnostics.json")
    p.add_argument("--include-storage", action="store_true", help="Include full selected localStorage values; can be large")
    args = p.parse_args()

    result = {
        "generatedUnix": time.time(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "inspectorTargets": get_targets(args.host, args.port),
    }

    with connect(args.host, args.port) as inspector:
        result["probe"] = electron_probe(inspector)
        state = renderer_state(inspector)
        result["renderers"] = [
            {
                "id": r.get("id"),
                "type": r.get("type"),
                "windowName": r.get("windowName"),
                "href": r.get("href"),
                "title": r.get("title"),
                "error": r.get("error"),
                "storageKeys": sorted(r.get("values", {}).keys()),
            }
            for r in state["renderers"]
        ]
        result["devices"] = build_devices(state)
        storage = unique_storage(state)
        result["storageIndex"] = {
            key: {
                "chars": len(raw),
                "shape": shape(parse_json(raw), max_depth=3),
            }
            for key, raw in storage.items()
            if key == "connectedDeviceInfo" or key.startswith("synapse_")
        }
        if args.include_storage:
            result["storage"] = {
                key: parse_json(raw)
                for key, raw in storage.items()
                if key == "connectedDeviceInfo" or key.startswith("synapse_")
            }

    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
