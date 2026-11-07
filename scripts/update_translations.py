"""Extract Qt translations without reading user configuration or calling services."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def qt_tool(name: str) -> str:
    executable = Path(sys.executable).with_name(name + (".exe" if sys.platform == "win32" else ""))
    resolved = str(executable) if executable.is_file() else shutil.which(name)
    if not resolved:
        raise SystemExit(f"Missing {name}; install the desktop extra first.")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--locale", default="zh_CN", choices=("zh_CN",), help="Only Chinese ships in this version."
    )
    parser.add_argument(
        "--compile", action="store_true", help="Compile finished translations to QM."
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    desktop = root / "src/lingualoop/desktop"
    catalog = desktop / "translations" / f"lingualoop_{args.locale}.ts"
    sources = [
        str(desktop / "qml"),
        *(
            str(desktop / name)
            for name in ("workspace.py", "viewmodel.py", "audio.py", "speech_library.py",
                         "voice.py", "continuous_voice.py", "voice_readiness.py", "speech_jobs.py", "speech_errors.py", "ai_services.py", "reader_runtime.py", "worker.py", "lifecycle.py", "shutdown.py", "learning_presentation.py", "reader_workspace.py", "speech_library_operations.py", "continuous_voice_presentation.py")
        ),
    ]
    subprocess.run(
        [
            qt_tool("pyside6-lupdate"),
            *sources,
            "-source-language",
            "zh_CN",
            "-target-language",
            args.locale,
            "-locations",
            "relative",
            "-no-obsolete",
            "-ts",
            str(catalog),
        ],
        check=True,
    )
    if args.compile:
        subprocess.run(
            [qt_tool("pyside6-lrelease"), str(catalog), "-qm", str(catalog.with_suffix(".qm"))],
            check=True,
        )


if __name__ == "__main__":
    main()
