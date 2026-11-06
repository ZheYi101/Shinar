from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


def safe_relative(value: str) -> str:
    if not value or "\\" in value or ":" in value:
        raise ValueError("模型路径必须是相对路径。")
    path = PurePosixPath(value)
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
    }
    if path.is_absolute() or any(
        not part
        or part in {"..", "."}
        or part.endswith((".", " "))
        or part.split(".")[0].upper() in reserved
        or any(ord(c) < 32 for c in part)
        for part in parts
    ):
        raise ValueError("模型路径越界。")
    return value


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0)
    archive_root: str | None = None
    unpacked_limit: int = Field(default=0, ge=0)

    @field_validator("path", "archive_root")
    @classmethod
    def paths(cls, value):
        return safe_relative(value) if value is not None else value

    @field_validator("url")
    @classmethod
    def https(cls, value):
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
        ):
            raise ValueError("模型仅从 HTTPS 下载。")
        return value

    @model_validator(mode="after")
    def archive_budget(self):
        if self.archive_root and not self.unpacked_limit:
            raise ValueError("压缩包必须限制展开大小。")
        return self


class ModelPackage(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    revision: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: str
    task: Literal["stt", "tts", "vad", "runtime"]
    languages: list[str]
    scenarios: list[Literal["conversation", "import", "reading"]]
    streaming: str
    license_note: str
    sources: list[str]
    adapter: Literal[
        "sensevoice", "sensevoice-ort", "reazon", "zipformer", "kokoro", "vits", "candidate", "silero-vad", "voicevox", "melo_english", "resource"
    ] = "candidate"
    files: list[Artifact] = Field(default_factory=list)
    required_files: list[str] = Field(default_factory=list)
    notes: str
    # A conservative admission budget, NOT a claimed model minimum or measurement.
    evaluation_budget_mb: int = 2048

    @field_validator("required_files")
    @classmethod
    def required_paths(cls, values):
        return [safe_relative(v) for v in values]

    @model_validator(mode="after")
    def complete(self):
        if bool(self.files) != bool(self.required_files) or (
            self.files and self.adapter == "candidate"
        ):
            raise ValueError("可下载包必须有运行适配器与完整文件清单。")
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("重复模型文件。")
        return self

    @property
    def download_bytes(self):
        return sum(f.size for f in self.files)

    @property
    def fingerprint(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load_catalog() -> list[ModelPackage]:
    content = files(__package__).joinpath("catalog.json").read_text(encoding="utf-8")
    packages = [ModelPackage.model_validate(item) for item in json.loads(content)]
    if len({p.id for p in packages}) != len(packages):
        raise ValueError("重复模型标识。")
    return packages
