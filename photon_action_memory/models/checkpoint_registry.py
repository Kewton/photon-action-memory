"""Issue #126 — Action Memory PHOTON checkpoint registry, promotion, rollback.

The registry owns a directory layout of the form:

```
<registry_root>/
    candidates/
        <candidate_id>/      # one directory per candidate checkpoint
            manifest.json
            state.json
            weights.npz
            integrity.json
            action_memory_state.json   # optional (v2)
            photon_runtime/            # optional (v2)
    current                  # pointer to the active candidate dir
    previous                 # pointer to the previously active candidate dir
    promotion_report.json    # append-only log of promote/rollback decisions
```

``current`` and ``previous`` are pointer files (one line: relative path under
``candidates/``). A pointer file is used in preference to a symlink because
Windows and some filesystems do not allow symlinks without elevated
privileges; for portability, all promotion operations go through
``os.replace`` which is atomic on every supported platform.

The :data:`PHOTON_ACTION_MEMORY_CHECKPOINT` environment variable is an
*operator override*. When set, :meth:`CheckpointRegistry.resolve_active`
returns that path and :meth:`CheckpointRegistry.auto_promotion_enabled`
returns False so the auto promotion path stays out of the operator's way.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from photon_action_memory.models.checkpoint import (
    PROMOTION_REPORT_FILENAME,
    CheckpointError,
    CheckpointInvalid,
    CheckpointUnavailable,
    load_checkpoint_manifest,
    verify_checkpoint_integrity,
)

_logger = logging.getLogger(__name__)

CHECKPOINT_OVERRIDE_ENV = "PHOTON_ACTION_MEMORY_CHECKPOINT"
CHECKPOINT_ACTIVE_ENV = "PHOTON_CHECKPOINT_ACTIVE"
CHECKPOINT_DIR_ENV = "PHOTON_CHECKPOINT_DIR"

CURRENT_POINTER = "current"
PREVIOUS_POINTER = "previous"
CANDIDATES_DIRNAME = "candidates"


class CheckpointRegistryError(CheckpointError):
    """Base class for registry-level promotion failures."""


@dataclass(frozen=True)
class PromotionRecord:
    """One promote or rollback event."""

    event: str  # "promote" | "rollback"
    candidate_id: str
    previous_id: str | None
    reason: str
    created_at: str
    gate_report: Mapping[str, object] | None = None


class CheckpointRegistry:
    """Atomic current/previous pointer manager for Action Memory checkpoints."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.candidates_dir = self.root_dir / CANDIDATES_DIRNAME
        self.report_path = self.root_dir / PROMOTION_REPORT_FILENAME

    def initialize(self) -> None:
        """Create the registry directory layout if it does not yet exist."""
        self.candidates_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Active pointer resolution
    # ------------------------------------------------------------------

    def resolve_active(self, environ: Mapping[str, str] | None = None) -> Path | None:
        """Return the active checkpoint path or None when unavailable.

        Resolution order:

        1. ``PHOTON_ACTION_MEMORY_CHECKPOINT`` operator override.
        2. ``PHOTON_CHECKPOINT_ACTIVE`` direct pointer.
        3. ``current`` pointer file under ``root_dir``.
        4. ``current`` pointer file under ``PHOTON_CHECKPOINT_DIR``.
        """
        env = environ if environ is not None else os.environ
        override = (env.get(CHECKPOINT_OVERRIDE_ENV) or "").strip()
        if override:
            return Path(override)
        active = (env.get(CHECKPOINT_ACTIVE_ENV) or "").strip()
        if active:
            return Path(active)
        local = self._read_pointer(self.root_dir / CURRENT_POINTER)
        if local is not None:
            return local
        env_dir = (env.get(CHECKPOINT_DIR_ENV) or "").strip()
        if env_dir:
            env_local = self._read_pointer(Path(env_dir) / CURRENT_POINTER)
            if env_local is not None:
                return env_local
        return None

    def active_path(self) -> Path | None:
        """Read the current pointer for this registry directory."""
        return self._read_pointer(self.root_dir / CURRENT_POINTER)

    def previous_path(self) -> Path | None:
        """Read the previous pointer for this registry directory."""
        return self._read_pointer(self.root_dir / PREVIOUS_POINTER)

    def auto_promotion_enabled(self, environ: Mapping[str, str] | None = None) -> bool:
        """Return False when the operator override is active."""
        env = environ if environ is not None else os.environ
        return not (env.get(CHECKPOINT_OVERRIDE_ENV) or "").strip()

    # ------------------------------------------------------------------
    # Candidate registration + promotion
    # ------------------------------------------------------------------

    def register_candidate(self, candidate_path: str | Path) -> str:
        """Validate a candidate manifest and return its candidate id.

        The candidate directory must already live under
        ``<root>/candidates/<id>``; the registry does not copy or move
        external paths. ``load_checkpoint_manifest`` is used as the
        validation gate.
        """
        path = Path(candidate_path)
        try:
            resolved = path.resolve()
            self.candidates_dir.resolve()
        except OSError as exc:
            raise CheckpointRegistryError(f"could not resolve candidate path: {path}") from exc
        try:
            relative = resolved.relative_to(self.candidates_dir.resolve())
        except ValueError as exc:
            raise CheckpointRegistryError(
                f"candidate path {path} is not under {self.candidates_dir}"
            ) from exc
        if len(relative.parts) != 1:
            raise CheckpointRegistryError(
                f"candidate path must be a direct child of candidates/: {path}"
            )
        # Defence-in-depth: confirm the manifest can be parsed.
        load_checkpoint_manifest(path)
        return relative.parts[0]

    def promote(
        self,
        candidate_id: str,
        *,
        reason: str,
        gate_report: Mapping[str, object] | None = None,
        verify_integrity: bool = True,
    ) -> PromotionRecord:
        """Atomically swap ``current`` to point at ``candidate_id``."""
        if not candidate_id or "/" in candidate_id or candidate_id.startswith("."):
            raise CheckpointRegistryError(f"invalid candidate id: {candidate_id!r}")
        candidate_dir = self.candidates_dir / candidate_id
        if not candidate_dir.is_dir():
            raise CheckpointUnavailable(f"candidate directory missing: {candidate_dir}")
        # Re-validate before promoting; manifest must still parse and (when
        # requested) the integrity manifest must match the sidecar files.
        load_checkpoint_manifest(candidate_dir)
        if verify_integrity:
            try:
                verify_checkpoint_integrity(candidate_dir, strict=True)
            except (FileNotFoundError, ValueError) as exc:
                raise CheckpointInvalid(
                    f"candidate {candidate_id} failed integrity verification"
                ) from exc

        self.initialize()
        previous = self._read_pointer_id(self.root_dir / CURRENT_POINTER)
        if previous is not None and previous != candidate_id:
            self._write_pointer(self.root_dir / PREVIOUS_POINTER, previous)
        self._write_pointer(self.root_dir / CURRENT_POINTER, candidate_id)

        record = PromotionRecord(
            event="promote",
            candidate_id=candidate_id,
            previous_id=previous,
            reason=reason,
            created_at=_utc_now(),
            gate_report=dict(gate_report) if gate_report is not None else None,
        )
        self._append_report(record)
        return record

    def rollback(
        self,
        *,
        reason: str,
        gate_report: Mapping[str, object] | None = None,
    ) -> PromotionRecord:
        """Promote the previously-active candidate back to current."""
        previous = self._read_pointer_id(self.root_dir / PREVIOUS_POINTER)
        if previous is None:
            raise CheckpointRegistryError("no previous checkpoint to rollback to")
        current = self._read_pointer_id(self.root_dir / CURRENT_POINTER)
        if current == previous:
            raise CheckpointRegistryError(f"previous pointer already matches current: {previous}")
        # Swap current and previous: the candidate that *was* current now
        # becomes the new previous so a second rollback can revert again.
        self._write_pointer(self.root_dir / CURRENT_POINTER, previous)
        if current is not None:
            self._write_pointer(self.root_dir / PREVIOUS_POINTER, current)
        record = PromotionRecord(
            event="rollback",
            candidate_id=previous,
            previous_id=current,
            reason=reason,
            created_at=_utc_now(),
            gate_report=dict(gate_report) if gate_report is not None else None,
        )
        self._append_report(record)
        return record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_pointer(self, pointer_path: Path) -> Path | None:
        candidate_id = self._read_pointer_id(pointer_path)
        if candidate_id is None:
            return None
        candidate_dir = self.candidates_dir / candidate_id
        if not candidate_dir.exists():
            _logger.warning(
                "registry pointer %s -> %s missing on disk",
                pointer_path,
                candidate_dir,
            )
            return None
        return candidate_dir

    def _read_pointer_id(self, pointer_path: Path) -> str | None:
        if not pointer_path.exists():
            return None
        try:
            content = pointer_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not content:
            return None
        # Pointer files contain the candidate id only — reject anything that
        # looks like a path traversal so the resolver stays inside the
        # candidates/ directory.
        if "/" in content or "\\" in content or content.startswith(".."):
            _logger.warning("registry pointer %s contains unsafe value", pointer_path)
            return None
        return content

    def _write_pointer(self, pointer_path: Path, candidate_id: str) -> None:
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = pointer_path.with_suffix(pointer_path.suffix + ".tmp")
        tmp.write_text(candidate_id + "\n", encoding="utf-8")
        os.replace(tmp, pointer_path)

    def _append_report(self, record: PromotionRecord) -> None:
        rows: list[dict[str, object]]
        if self.report_path.exists():
            try:
                raw = json.loads(self.report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = []
            rows = list(raw) if isinstance(raw, list) else []
        else:
            rows = []
        rows.append(
            {
                "event": record.event,
                "candidate_id": record.candidate_id,
                "previous_id": record.previous_id,
                "reason": record.reason,
                "created_at": record.created_at,
                "gate_report": dict(record.gate_report) if record.gate_report else None,
            }
        )
        tmp = self.report_path.with_suffix(self.report_path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.report_path)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


__all__ = [
    "CHECKPOINT_ACTIVE_ENV",
    "CHECKPOINT_DIR_ENV",
    "CHECKPOINT_OVERRIDE_ENV",
    "CANDIDATES_DIRNAME",
    "CURRENT_POINTER",
    "CheckpointRegistry",
    "CheckpointRegistryError",
    "PREVIOUS_POINTER",
    "PromotionRecord",
]
