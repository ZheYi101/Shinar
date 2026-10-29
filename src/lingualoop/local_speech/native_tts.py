"""Optional TTS frontends, imported only inside an isolated inference worker."""

import io
from pathlib import Path
from types import SimpleNamespace
import wave


class NativeTts:
    def __init__(self, spec: dict, threads: int) -> None:
        self.adapter = spec["adapter"]
        self.speaker_id = spec.get("style_id", spec.get("speaker_id", 0))
        if self.adapter == "melo_english":
            from melo_english import MeloEnglish

            self.engine = MeloEnglish(spec, threads)
        else:
            if not spec.get("license_accepted") or spec.get("provider", "cpu") != "cpu":
                raise ValueError(
                    "VOICEVOX requires accepted voice terms and the validated CPU profile."
                )
            from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile

            dictionary = spec.get("dictionary")
            if not dictionary:
                import pyopenjtalk

                dictionary = pyopenjtalk.OPEN_JTALK_DICT_DIR
                if isinstance(dictionary, bytes):
                    dictionary = dictionary.decode()
            if not Path(dictionary).is_dir():
                raise ValueError("voicevox_dictionary_missing")
            self.engine = Synthesizer(
                Onnxruntime.load_once(filename=spec["onnxruntime"]),
                OpenJtalk(dictionary),
                acceleration_mode="CPU",
                cpu_num_threads=threads,
            )
            with VoiceModelFile.open(spec["model_file"]) as model:
                self.engine.load_voice_model(model)

    def generate(self, text: str, *, sid: int = 0, callback=None):
        import numpy as np

        if self.adapter == "melo_english":
            samples, rate = self.engine.synthesize(text, self.speaker_id)
        else:
            audio = self.engine.tts(text, self.speaker_id)
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
                    raise ValueError("voicevox_unexpected_audio_format")
                samples = (
                    np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32)
                    / 32768
                )
                rate = wav.getframerate()
        if callback:
            callback(samples, 1.0)
        return SimpleNamespace(samples=samples, sample_rate=rate)
