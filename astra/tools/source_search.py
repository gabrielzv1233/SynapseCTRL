import argparse
import re
import zipfile
from pathlib import Path


def iter_files(root: Path):
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    yield str(path.relative_to(root)), path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
    elif zipfile.is_zipfile(root):
        with zipfile.ZipFile(root) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.file_size > 20_000_000:
                    continue
                try:
                    yield info.filename, zf.read(info).decode("utf-8", errors="ignore")
                except Exception:
                    pass
    else:
        raise SystemExit(f"Not a directory or zip: {root}")


def main() -> int:
    p = argparse.ArgumentParser(description="Search an extracted Synapse source tree or hunter ZIP without needing ripgrep setup.")
    p.add_argument("root", type=Path)
    p.add_argument("pattern")
    p.add_argument("--regex", action="store_true")
    p.add_argument("--case-sensitive", action="store_true")
    p.add_argument("--max", type=int, default=50)
    p.add_argument("--context", type=int, default=160, help="Characters before/after match")
    args = p.parse_args()

    flags = 0 if args.case_sensitive else re.I
    regex = re.compile(args.pattern if args.regex else re.escape(args.pattern), flags)
    found = 0
    for name, text in iter_files(args.root):
        for match in regex.finditer(text):
            start = max(0, match.start() - args.context)
            end = min(len(text), match.end() + args.context)
            snippet = text[start:end].replace("\r", "").replace("\n", "\\n")
            print(f"{name}:{match.start()}\n  {snippet}\n")
            found += 1
            if found >= args.max:
                return 0
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
