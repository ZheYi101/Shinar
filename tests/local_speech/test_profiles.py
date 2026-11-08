import asyncio
from dataclasses import replace
import hashlib
import json
import subprocess
import sys

import pytest

from shinar.local_speech.profiles import LocalSpeechProfile, LocalSpeechProvider, instance_key
from shinar.local_speech.processes import pid_exists, run_owned


def test_model_identity_excludes_dynamic_voice_and_language_but_keeps_device():
    spec = {"adapter": "sensevoice-ort", "language": "zh", "provider": "cuda", "path": "weights"}
    assert instance_key(spec) == instance_key({**spec, "language": "ja"})
    assert instance_key(spec) != instance_key({**spec, "provider": "cpu"})
    legacy = {**spec, "adapter": "sensevoice"}
    assert instance_key(legacy) != instance_key({**legacy, "language": "ja"})
    melo = {"adapter": "melo_english", "speaker_id": 0, "provider": "cuda"}
    assert instance_key(melo) == instance_key({**melo, "speaker_id": 3})


def test_prepared_profile_checks_hashes_voice_terms_and_language(tmp_path):
    weights = tmp_path / "model.vvm"
    weights.write_bytes(b"fixture")
    assets = json.dumps({str(weights): hashlib.sha256(b"fixture").hexdigest()})
    spec = dict(
        id="voice",
        adapter="voicevox",
        task="tts",
        language="ja",
        provider="cpu",
        model_file=str(weights),
        license_accepted=True,
    )
    profile = LocalSpeechProfile(
        "tts",
        "ja",
        "voice",
        sys.executable,
        json.dumps(spec),
        attribution="VOICEVOX:ずんだもん",
        assets_json=assets,
    )
    profile.validate_assets()
    with pytest.raises(ValueError, match="license"):
        replace(profile, attribution="").validate_assets()
    with pytest.raises(ValueError, match="mismatch"):
        replace(profile, language="en").validate_assets()
    weights.write_bytes(b"changed")
    with pytest.raises(ValueError, match="asset_mismatch"):
        profile.validate_assets()


def test_bound_provider_does_not_reresolve_between_sentences():
    async def run():
        first = LocalSpeechProfile("tts", "en", "one", sys.executable, "{}")
        second = replace(first, package_id="two")

        class Service:
            selected = first
            observed = []

            async def resolve(self, task, language):
                return self.selected

            async def execute(self, profile, **payload):
                self.observed.append(profile.package_id)
                return {"audio": "eA=="}

        service = Service()
        binding = await LocalSpeechProvider(service, "tts").bind("en")
        service.selected = second
        await binding.synthesize("First.")
        await binding.synthesize("Second.")
        assert service.observed == ["one", "one"]

    asyncio.run(run())


def test_owned_timeout_reaps_actual_python_descendant(tmp_path):
    pid_file = tmp_path / "owned-pids.txt"
    script = (
        "import os, subprocess, sys, time; from pathlib import Path; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "Path(sys.argv[1]).write_text(f'{os.getpid()} {child.pid}'); time.sleep(60)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable, "-c", script, str(pid_file)], timeout=5)
    assert pid_file.is_file(), "The fixture must start its child before exercising timeout cleanup"
    pids = [int(value) for value in pid_file.read_text().split()]
    assert len(pids) == 2
    assert all(not pid_exists(pid) for pid in pids)
