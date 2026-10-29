"""Optional local speech catalog and evaluation tools; independent of the GUI/core."""

RUNTIME_VERSION = "1.13.8"


def adapter_revision(adapter: str) -> int:
    """Measurement/selection compatibility, independent of downloaded package bytes."""
    return 2 if adapter == "zipformer" else 1
