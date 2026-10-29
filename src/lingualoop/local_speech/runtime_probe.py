"""Executed in the optional child interpreter, never in the Qt process."""

from __future__ import annotations

import json
import os
from importlib.metadata import version
from pathlib import Path
import sys
import tempfile


def probe(device: str, gpu_index: int) -> dict:
    import onnx
    import numpy as np
    import onnxruntime as ort
    import sherpa_onnx

    if ort.__version__ != "1.23.2" or sherpa_onnx.__version__.split("+")[0] != "1.13.8":
        raise ValueError("Runtime version mismatch")
    if device == "cpu" and version("sherpa-onnx-core") != "1.13.8":
        raise ValueError("CPU native core version mismatch")
    if device == "cuda":
        directory = os.getenv("LINGUALOOP_CUDA_DLL_DIR")
        dll_handle = os.add_dll_directory(directory) if directory and os.name == "nt" else None
        ort.preload_dlls(directory=directory)
    providers = (
        [("CUDAExecutionProvider", {"device_id": gpu_index})]
        if device == "cuda"
        else ["CPUExecutionProvider"]
    )
    node = onnx.helper.make_node("MatMul", ["x", "y"], ["z"])
    info = lambda name: onnx.helper.make_tensor_value_info(name, onnx.TensorProto.FLOAT, [32, 32])
    model = onnx.helper.make_model(
        onnx.helper.make_graph([node], "probe", [info("x"), info("y")], [info("z")]),
        opset_imports=[onnx.helper.make_opsetid("", 17)],
        ir_version=9,
    )
    with tempfile.TemporaryDirectory(prefix="lingualoop-runtime-") as directory:
        options = ort.SessionOptions()
        options.enable_profiling = True
        options.profile_file_prefix = str(Path(directory) / "probe")
        session = ort.InferenceSession(model.SerializeToString(), options, providers=providers)
        values = np.ones((32, 32), dtype=np.float32)
        result = session.run(None, {"x": values, "y": values})[0]
        if not np.allclose(result, 32):
            raise ValueError("Incorrect computation")
        trace = json.loads(Path(session.end_profiling()).read_text())
        actual = [item.get("args", {}) for item in trace]
        cuda_nodes = sum(
            item.get("provider") == "CUDAExecutionProvider" and item.get("op_name") == "MatMul"
            for item in actual
        )
        if device == "cuda" and not cuda_nodes:
            raise ValueError("Silent CPU fallback")
    return {
        "ok": True,
        "device": device,
        "gpu_index": gpu_index,
        "ort_version": ort.__version__,
        "sherpa_version": sherpa_onnx.__version__,
        "cuda_matmul_nodes": cuda_nodes,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(probe(sys.argv[1], int(sys.argv[2]))), flush=True)
    except Exception:
        print(json.dumps({"ok": False, "error": "Runtime computation probe failed"}), flush=True)
        raise SystemExit(1)
