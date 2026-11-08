"""Bounded child-only probes; no microphone, model downloads, or cloud calls."""

import json
from pathlib import Path
import sys


def probe(config: dict) -> dict:
    name = config["runtime_id"]
    device = "cuda" if name.endswith("cuda") else "cpu"
    result = {"ok": True, "runtime_id": name, "device": device, "gpu_index": config["gpu_index"]}
    if name.startswith("ort-"):
        import os

        os.environ.pop("SHINAR_CUDA_DLL_DIR", None)
        from runtime_probe import probe as ort_probe

        result.update(ort_probe(device, config["gpu_index"]))
    elif name.startswith("melo-"):
        import os

        folder = Path(sys.executable).parent.parent
        os.environ["NLTK_DATA"] = str(folder / "support/nltk_data")
        os.environ["SHINAR_EVAL_BERT_DIR"] = config["resources"]["bert"]
        os.environ["LINGUALOOP_EVAL_BERT_DIR"] = config["resources"]["bert"]
        sys.path[:0] = [str(folder / "support/MeloTTS"), str(folder / "support/english_frontend")]
        import torch
        import transformers
        from melo.models import SynthesizerTrn
        from melo.split_utils import split_sentence
        from melo_text import english

        assert SynthesizerTrn and split_sentence and english

        if torch.__version__.split("+")[0] != "2.9.1" or transformers.__version__ != "4.57.3":
            raise ValueError("runtime_version_mismatch")
        target = f"cuda:{config['gpu_index']}" if device == "cuda" else "cpu"
        x = torch.ones((32, 32), device=target)
        y = x @ x
        if str(y.device) != target or not torch.allclose(y.cpu(), torch.full((32, 32), 32.0)):
            raise ValueError("runtime_computation_failed")
        result.update(torch_version=torch.__version__, actual_device=str(y.device))
    elif name == "voicevox-cpu":
        from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer

        dll = next(Path(config["resources"]["voicevox-ort"]).rglob("voicevox_onnxruntime.dll"))
        Synthesizer(
            Onnxruntime.load_once(filename=str(dll)),
            OpenJtalk(config["resources"]["dictionary"]),
            acceleration_mode="CPU",
        )
    elif name == "rtc-cpu":
        import numpy as np
        import onnxruntime
        from livekit import rtc, api

        apm = rtc.AudioProcessingModule(echo_cancellation=True)
        apm.set_stream_delay_ms(80)
        frame = rtc.AudioFrame(np.zeros(480, dtype=np.int16).tobytes(), 48000, 1, 480)
        apm.process_reverse_stream(frame)
        apm.process_stream(frame)
        result.update(ort_version=onnxruntime.__version__, apm_frame_samples=480)
        assert api.AccessToken
    else:
        raise ValueError("runtime_unknown")
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(probe(json.loads(sys.argv[1]))), flush=True)
    except Exception:
        print(json.dumps({"ok": False, "error": "speech_runtime_probe_failed"}), flush=True)
        raise SystemExit(1)
