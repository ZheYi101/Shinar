"""Report configuration presence and device counts without sending requests."""
from pathlib import Path

from dotenv import load_dotenv

from shinar.providers.speech import SpeechSettings


def main():
    load_dotenv(Path.cwd() / ".env")
    ready = True
    for kind in ("STT", "TTS"):
        try:
            SpeechSettings.from_env(kind)
        except ValueError:
            # Do not print validation details, which may contain configuration.
            print(f"{kind}: incomplete or invalid; check SHINAR_{kind}_* in .env.example")
            ready = False
        else:
            print(f"{kind}: configured (connectivity not verified)")
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtMultimedia import QMediaDevices

        app = QCoreApplication.instance() or QCoreApplication([])
        inputs, outputs = QMediaDevices.audioInputs(), QMediaDevices.audioOutputs()
        print(f"Audio devices: {len(inputs)} input(s), {len(outputs)} output(s)")
        ready = ready and bool(inputs and outputs)
    except ImportError:
        print("Qt Multimedia unavailable; install the desktop extra")
        ready = False
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
