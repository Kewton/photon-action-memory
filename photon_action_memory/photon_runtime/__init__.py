"""Slim port boundary for ``photon-mlx`` runtime code.

This package marks the location of the future slim port of select modules
from the ``photon-mlx`` repository. The current build does **not** ship
ported MLX code: ``PhotonMLXAdapter`` still imports ``mlx.core`` lazily via
``importlib`` from :mod:`photon_action_memory.models.photon_adapter`.

When a real slim port lands, the contract recorded in
``UPSTREAM.md`` MUST be updated in the same change. CI continues to pass
without MLX installed because nothing here is imported by the default
import path of :mod:`photon_action_memory`.
"""

from __future__ import annotations

__all__: list[str] = []
