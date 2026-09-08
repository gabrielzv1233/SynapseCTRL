import argparse
import json

from _synapse import connect, renderer_eval


def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate JavaScript in the Synapse main process or a renderer. Powerful diagnostic tool.")
    sub = p.add_subparsers(dest="mode", required=True)

    main_p = sub.add_parser("main", help="Evaluate in Electron browser/main process")
    main_p.add_argument("expression")

    renderer_p = sub.add_parser("renderer", help="Evaluate in one renderer")
    renderer_p.add_argument("expression")
    renderer_p.add_argument("--name", help="Exact window.apiElectron.windowName")
    renderer_p.add_argument("--id", type=int, help="webContents id")
    renderer_p.add_argument("--url-contains")

    for child in (main_p, renderer_p):
        child.add_argument("--host", default="127.0.0.1")
        child.add_argument("--port", type=int, default=9229)

    args = p.parse_args()
    with connect(args.host, args.port) as inspector:
        if args.mode == "main":
            value = inspector.evaluate(args.expression)
        else:
            value = renderer_eval(
                inspector,
                args.expression,
                window_name=args.name,
                renderer_id=args.id,
                url_contains=args.url_contains,
            )
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
