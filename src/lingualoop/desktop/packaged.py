"""Private-runtime entry point used by the relocatable Windows launcher."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from dotenv import load_dotenv


def configuration_file() -> Path:
    explicit = os.environ.get("LINGUALOOP_CONFIG_FILE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    return local / "LinguaLoop" / ".env"


def main() -> int:
    # Resolve an explicit relative config before changing the working directory.
    config = configuration_file()
    os.chdir(Path(sys.executable).resolve().parent.parent)
    if "--mock" in sys.argv[1:]:
        # A demo/smoke launch must never persist sample state in the real user library.
        with TemporaryDirectory(prefix="lingualoop-packaged-mock-") as directory:
            from PySide6.QtCore import QSettings

            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, directory)
            old_data = os.environ.get("LINGUALOOP_DATA_DIR")
            os.environ["LINGUALOOP_DATA_DIR"] = directory
            try:
                return _run_desktop()
            finally:
                if old_data is None:
                    os.environ.pop("LINGUALOOP_DATA_DIR", None)
                else:
                    os.environ["LINGUALOOP_DATA_DIR"] = old_data
    # Existing process environment wins; never copy a developer's .env into the package.
    load_dotenv(config, override=False)
    return _run_desktop()


def _run_desktop() -> int:
    from lingualoop.desktop.app import main as desktop_main

    return desktop_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
