"""Owned NLTK data for standalone speech workers; never use network or home caches."""

from pathlib import Path
from zipfile import BadZipFile


ARCHIVES = (
    "corpora/cmudict.zip",
    "taggers/averaged_perceptron_tagger.zip",
    "taggers/averaged_perceptron_tagger_eng.zip",
)
DIRECTORIES = (
    "", "corpora/cmudict", "taggers/averaged_perceptron_tagger",
    "taggers/averaged_perceptron_tagger_eng",
)


def validate_nltk_data(data_directory) -> None:
    root = Path(data_directory)
    if not all((root / name).is_file() for name in ARCHIVES) or not all(
        (root / name).is_dir() for name in DIRECTORIES
    ):
        raise ValueError("speech_runtime_nltk_missing")


def configure_offline_nltk(data_directory) -> None:
    root = Path(data_directory)
    validate_nltk_data(root)
    import nltk

    def reject_download(*_args, **_kwargs):
        raise ValueError("speech_runtime_nltk_missing")

    nltk.data.path = [str(root)]
    nltk.download = reject_download
    try:
        # g2p_en checks the archives themselves, even when the unpacked data exists.
        for name in ARCHIVES:
            nltk.data.find(name, paths=[str(root)])
    except (LookupError, OSError, BadZipFile) as error:
        raise ValueError("speech_runtime_nltk_missing") from error
