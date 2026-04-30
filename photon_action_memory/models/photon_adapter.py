"""Optional PHOTON/MLX scoring adapter boundary."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

from photon_action_memory.models.checkpoint import CheckpointState, load_checkpoint

_logger = logging.getLogger(__name__)

CHECKPOINT_ENV = "PHOTON_ACTION_MEMORY_CHECKPOINT"
CHECKPOINT_STRICT_ENV = "PHOTON_ACTION_MEMORY_CHECKPOINT_STRICT"


def is_model_available() -> bool:
    """Return true only when optional runtime dependencies and checkpoint load."""

    if importlib.util.find_spec("mlx") is None:
        return False
    return load_configured_checkpoint_state() is not None


def load_configured_checkpoint_state() -> CheckpointState | None:
    """Load configured checkpoint state, returning unavailable on failure."""

    checkpoint_path = configured_checkpoint_path()
    if checkpoint_path is None:
        return None
    try:
        return load_checkpoint(checkpoint_path, verify_integrity=_strict_checkpoint_mode())
    except (OSError, ValueError) as exc:
        _logger.warning(
            "PHOTON checkpoint at %s is unavailable; falling back to deterministic ranking: %s",
            checkpoint_path,
            exc,
        )
        return None


def configured_checkpoint_path() -> Path | None:
    """Return the configured checkpoint directory, if any."""

    raw_path = os.environ.get(CHECKPOINT_ENV, "").strip()
    if not raw_path:
        return None
    return Path(raw_path)


def _strict_checkpoint_mode() -> bool:
    raw_value = os.environ.get(CHECKPOINT_STRICT_ENV, "").strip().lower()
    return raw_value in {"1", "true", "yes", "on", "strict"}
