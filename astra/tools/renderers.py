import argparse
import json

from _synapse import connect, renderer_state


def main() -> int:
    p = argparse.ArgumentParser(description="List Synapse Electron webContents/renderers.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9229)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    with connect(args.host, args.port) as inspector:
        state = renderer_state(inspector, include_values=False)

    if args.json:
        print(json.dumps(state, indent=2))
        return 0

    print(f"PID: {state['pid']}  process.type={state['processType']!r}")
    print(f"BrowserWindows={state['browserWindowCount']} webContents={state['webContentsCount']}")
    for r in state["renderers"]:
        print(f"[{r['id']}] {r.get('type')} {r.get('windowName')!r}")
        print(f"    {r.get('href', '')}")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
