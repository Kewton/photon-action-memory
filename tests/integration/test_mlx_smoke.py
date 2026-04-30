from __future__ import annotations

import os
from typing import Any

import pytest

from photon_action_memory.models.photon_adapter import is_model_available


def test_mlx_import_and_tiny_scoring_smoke() -> None:
    if os.environ.get("PHOTON_RUN_MLX_SMOKE") != "1":
        pytest.skip("MLX smoke is opt-in outside the dedicated macOS workflow")

    mx: Any = pytest.importorskip("mlx.core")

    assert isinstance(is_model_available(), bool)

    weights = mx.array([0.25, 0.75], dtype=mx.float32)
    features = mx.array([2.0, 4.0], dtype=mx.float32)
    score = mx.sum(weights * features)
    mx.eval(score)

    assert score.item() == pytest.approx(3.5)
