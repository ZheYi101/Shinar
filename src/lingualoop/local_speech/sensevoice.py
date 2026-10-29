"""SenseVoice's documented ONNX metadata frontend and CTC decode, in a child only."""

from __future__ import annotations

import itertools
import os
from pathlib import Path


class SenseVoiceOrt:
    def __init__(self, spec: dict, threads: int):
        import numpy as np
        import onnxruntime as ort

        self.np, self.spec = np, spec
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        if spec.get("provider") == "cuda":
            # Packaged NVIDIA wheels, a matching Torch runtime, or a user's CUDA runtime.
            directory = os.getenv("LINGUALOOP_CUDA_DLL_DIR")
            self.dll_handle = (
                os.add_dll_directory(directory) if directory and os.name == "nt" else None
            )
            ort.preload_dlls(directory=directory)
            providers = [
                (
                    "CUDAExecutionProvider",
                    {
                        "device_id": spec.get("gpu_index", 0),
                        "gpu_mem_limit": spec.get("vram_budget_mb", 3072) * 1024**2,
                        "arena_extend_strategy": "kSameAsRequested",
                        "cudnn_conv_algo_search": "HEURISTIC",
                    },
                ),
                "CPUExecutionProvider",
            ]
        path = Path(spec["path"])
        self.session = ort.InferenceSession(str(path / "model.onnx"), options, providers=providers)
        if (
            spec.get("provider") == "cuda"
            and "CUDAExecutionProvider" not in self.session.get_providers()
        ):
            raise ValueError("GPU 模型加载失败，未静默改用 CPU。请检查驱动和 GPU 运行环境。")
        self.metadata = self.session.get_modelmeta().custom_metadata_map
        self.mean = np.fromstring(self.metadata["neg_mean"], sep=",", dtype=np.float32)
        self.scale = np.fromstring(self.metadata["inv_stddev"], sep=",", dtype=np.float32)
        self.tokens = {}
        for line in (path / "tokens.txt").read_text(encoding="utf-8").splitlines():
            symbol, identifier = line.rsplit(" ", 1)
            self.tokens[int(identifier)] = symbol.replace("▁", " ")

    def transcribe(self, rate: int, samples) -> str:
        import kaldi_native_fbank as knf

        np = self.np
        options = knf.FbankOptions()
        options.frame_opts.samp_freq = rate
        options.frame_opts.dither = 0.0
        options.frame_opts.snip_edges = True
        options.frame_opts.window_type = "hamming"
        options.mel_opts.num_bins = 80
        options.mel_opts.low_freq = 20
        options.mel_opts.high_freq = 0
        fbank = knf.OnlineFbank(options)
        waveform = samples * (32768 if self.metadata["normalize_samples"] == "0" else 1)
        fbank.accept_waveform(rate, waveform.tolist())
        fbank.input_finished()
        if not fbank.num_frames_ready:
            raise ValueError("录音过短，无法识别。")
        frames = np.stack([fbank.get_frame(i) for i in range(fbank.num_frames_ready)])
        window = int(self.metadata["lfr_window_size"])
        shift = int(self.metadata["lfr_window_shift"])
        positions = (
            np.arange((len(frames) + shift - 1) // shift)[:, None] * shift
            + np.arange(window)[None, :]
            - (window - 1) // 2
        )
        stacked = frames[positions.clip(0, len(frames) - 1)].reshape(-1, 80 * window)
        features = np.ascontiguousarray((stacked + self.mean) * self.scale)[None]
        logits = self.session.run(
            None,
            {
                "x": features,
                "x_length": np.array([features.shape[1]], dtype=np.int32),
                "language": np.array(
                    [int(self.metadata["lang_" + self.spec["language"]])], dtype=np.int32
                ),
                "text_norm": np.array([int(self.metadata["without_itn"])], dtype=np.int32),
            },
        )[0]
        ids = [key for key, _ in itertools.groupby(logits[0].argmax(axis=-1).tolist()) if key != 0]
        return "".join(self.tokens[i] for i in ids[4:]).strip()
