"""Synchronous settings cannot slip past a maintenance or relocation lease."""

from threading import Event, Thread

import pytest

from shinar.configuration_location import save_speech_location
from shinar.desktop.speech_library.viewmodel import SpeechLibraryViewModel
from shinar.local_speech.compute import load_compute
from shinar.local_speech.model_profile import voices
from shinar.local_speech.storage import atomic_json
from shinar.local_speech.storage_lease import storage_lease


@pytest.mark.parametrize("retired", [False, True])
def test_settings_refuse_maintenance_or_retired_root(qt_app, tmp_path, retired):
    root = tmp_path / "speech"
    root.mkdir()
    entered, release = Event(), Event()
    if retired:
        destination, config = tmp_path / "new", tmp_path / "location.json"
        destination.mkdir()
        save_speech_location(destination, config)
        atomic_json(root / ".storage-moved.json", {
            "destination": str(destination), "config_path": str(config),
        })
        thread = None
    else:
        def maintenance():
            with storage_lease(root, exclusive=True):
                entered.set()
                release.wait(5)

        thread = Thread(target=maintenance)
        thread.start()
        assert entered.wait(2)
    library = SpeechLibraryViewModel(root)
    try:
        library.setCompute("local_stt", True)
        library.acceptVoiceTerms("voicevox-japanese", True)
        library.selectVoice("melo-english-en", voices("melo-english-en")[0]["id"])
        assert not load_compute(root).local_stt
        assert not (root / "compute.json").exists()
        assert not (root / "voice-terms.json").exists()
        assert not (root / "voices.json").exists()
        assert "维护" in library.status
    finally:
        release.set()
        if thread:
            thread.join(timeout=2)
            assert not thread.is_alive()
        library.close()
