"""After a successful upgrade, remove only files retired by the runtime policy."""

from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
import sys


def cleanup(app: Path, layout: dict) -> int:
    runtime = app.resolve() / "runtime"
    if runtime.is_symlink() or not runtime.is_dir() or layout.get("policy") != "windows-slim-v1":
        raise ValueError("Invalid runtime layout")
    retained = {PureWindowsPath(name).as_posix().casefold() for name in layout["retained"]}
    targets = []
    for name in layout["retired"]:
        relative = PureWindowsPath(name)
        if (
            not name
            or relative.is_absolute()
            or relative.root
            or relative.drive
            or ".." in relative.parts
            or ":" in name
            or relative.as_posix().casefold() in retained
        ):
            raise ValueError("Invalid retired runtime path")
        target = runtime.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(runtime) or target.is_symlink():
            raise ValueError("Retired runtime path escaped the installation")
        targets.append(target)
    removed = 0
    for target in targets:
        if target.is_file():
            target.unlink()
            removed += 1
    return removed


def main() -> int:
    try:
        app = Path(sys.argv[1]).resolve()
        if app != Path(__file__).resolve().parent:
            raise ValueError("Cleanup must run in its own installation")
        layout = json.loads((app / "RUNTIME_LAYOUT.json").read_text(encoding="utf-8"))
        print(json.dumps({"retired_files_removed": cleanup(app, layout)}))
        return 0
    except (ValueError, KeyError, TypeError, OSError, IndexError):
        print("Runtime cleanup did not finish; application files and user data are retained.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
