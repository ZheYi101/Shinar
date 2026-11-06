"""Pinned, explicitly prepared continuous-voice assets; no download during capture."""

from pathlib import Path
import hashlib
import importlib.util
from functools import lru_cache

from lingualoop.local_speech.catalog import ModelPackage
from lingualoop.local_speech.downloads import ModelStore

VAD_PACKAGE = ModelPackage(
    id="silero-vad",
    revision="v6_2_3",
    name="Silero VAD 6.2.3",
    task="vad",
    adapter="silero-vad",
    languages=["zh", "en", "ja"],
    scenarios=["conversation"],
    streaming="512 samples at 16 kHz, recurrent ONNX state",
    license_note="MIT",
    sources=["https://github.com/snakers4/silero-vad/releases/tag/v6.2.3"],
    notes="CPU-only endpoint detection; not speech recognition.",
    required_files=["silero_vad.onnx", "LICENSE"],
    files=[
        {
            "path": "silero_vad.onnx",
            "url": "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.3/src/silero_vad/data/silero_vad.onnx",
            "size": 2327524,
            "sha256": "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
        },
        {
            "path": "LICENSE",
            "url": "https://raw.githubusercontent.com/snakers4/silero-vad/v6.2.3/LICENSE",
            "size": 1075,
            "sha256": "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b",
        },
    ],
)


def dependencies_ready() -> bool:
    try:
        return all(
            importlib.util.find_spec(name) is not None for name in ("livekit.rtc", "onnxruntime")
        )
    except ModuleNotFoundError:
        return False


def vad_path(root: Path, *, verify: bool = False) -> Path:
    store = ModelStore(root)
    if not store.installed(VAD_PACKAGE):
        raise RuntimeError("voice_assets_not_prepared")
    folder = store.model_path(VAD_PACKAGE)
    if verify:
        for item in VAD_PACKAGE.files:
            if hashlib.sha256((folder / item.path).read_bytes()).hexdigest() != item.sha256:
                raise RuntimeError("voice_asset_checksum_mismatch")
    return folder / "silero_vad.onnx"


def prepare_assets(root: Path, *, cancel=None, progress=lambda done, total: None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return ModelStore(root).install(VAD_PACKAGE, cancel=cancel, progress=progress)


def server_package() -> ModelPackage:
    from .local_server import ARCHIVE_NAME, ARCHIVE_SHA256, RELEASE_URL, SERVER_VERSION

    return ModelPackage(
        id="livekit-server",
        revision=SERVER_VERSION.replace(".", "_"),
        name="LiveKit local SFU",
        task="runtime",
        adapter="resource",
        languages=[],
        scenarios=["conversation"],
        streaming="not applicable",
        license_note="Apache-2.0",
        sources=[RELEASE_URL],
        notes="Explicitly prepared loopback-only SFU.",
        required_files=[ARCHIVE_NAME],
        files=[
            {
                "path": ARCHIVE_NAME,
                "url": RELEASE_URL,
                "size": 19616198,
                "sha256": ARCHIVE_SHA256,
            }
        ],
    )


@lru_cache(maxsize=64)
def _verified_file(path: str, size: int, modified_ns: int, expected: str) -> bool:
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == expected


def prepared_assets(root: Path) -> bool:
    """Ready means verified VAD and SFU, rather than the presence of marker files."""
    from .local_server import ARCHIVE_NAME, ARCHIVE_SHA256

    try:
        folder = vad_path(root).parent
        paths = [(folder / item.path, item.sha256) for item in VAD_PACKAGE.files]
        paths.append((root / "sfu" / ARCHIVE_NAME, ARCHIVE_SHA256))
        return all(
            _verified_file(str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns, sha)
            for path, sha in paths
        )
    except (ValueError, RuntimeError, OSError):
        return False
