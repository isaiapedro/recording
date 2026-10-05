"""Local storage boundary for the Video service.

Recorded media is sensitive Personal data.  All media inputs and generated
artifacts therefore stay below the service-owned recordings root; callers
cannot redirect this service to another workspace location.
"""
from __future__ import annotations

import os
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
RECORDINGS_ROOT = SERVICE_ROOT / "projects" / "recordings"


class StorageBoundaryError(ValueError):
    """Raised when a path falls outside the service-owned recordings root."""


def recordings_root() -> Path:
    """Return the canonical recording root, creating it with private defaults."""
    RECORDINGS_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = RECORDINGS_ROOT.resolve()
    root.chmod(0o700)
    return root


def recording_path(value: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve a caller path only when it is contained in ``recordings_root``.

    Relative paths are interpreted relative to the recording root, not the
    caller's working directory.  This makes CLI invocation location harmless.
    """
    root = recordings_root()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise StorageBoundaryError(
            f"Path must remain under the service recording root: {root}"
        ) from exc
    if candidate == root:
        raise StorageBoundaryError("A recording file path, not the recording root, is required")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"Recording file not found: {candidate}")
    return candidate


def output_path(value: str | Path, *, suffix: str) -> Path:
    """Return a confined output path and create only its confined parent."""
    path = recording_path(value)
    if path.suffix.lower() != suffix:
        raise StorageBoundaryError(f"Output must use the {suffix} extension: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def write_private_text(path: Path, content: str) -> None:
    """Write a service-owned metadata artifact without widening file access."""
    path = recording_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
