"""Staleness Guard for ActionSummary freshness evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from photon_action_memory.api.schema_v2 import (
    ActionSummary,
    StalenessStatusKind,
    Validity,
)

_PROMPT_SAFE_PATH_LEN = 80
_COMMIT_DISPLAY_LEN = 8


def _safe_path(path: str) -> str:
    if len(path) > _PROMPT_SAFE_PATH_LEN:
        return path[:_PROMPT_SAFE_PATH_LEN] + "..."
    return path


# ---------------------------------------------------------------------------
# File fingerprint helpers
# ---------------------------------------------------------------------------


class FileFingerprinter:
    """Compute stable content fingerprints for file contents and line ranges.

    Fingerprints are 16-hex-char SHA-256 prefixes, stable across runs,
    cheap to store, and safe to include in prompt-visible reasons.
    """

    @staticmethod
    def fingerprint_content(content: str) -> str:
        """Return a 16-hex-char fingerprint for *content*."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @staticmethod
    def fingerprint_line_range(content: str, start: int, end: int) -> str:
        """Return a fingerprint for lines [start, end] (1-indexed, inclusive).

        Lines outside the valid range are silently clamped.
        """
        lines = content.splitlines()
        lo = max(0, start - 1)
        hi = min(len(lines), end)
        slice_text = "\n".join(lines[lo:hi])
        return hashlib.sha256(slice_text.encode()).hexdigest()[:16]

    @staticmethod
    def line_range_key(path: str, start: int, end: int) -> str:
        """Return the canonical dict key for a line-range fingerprint entry."""
        return f"{path}:{start}:{end}"


# ---------------------------------------------------------------------------
# Staleness context and result
# ---------------------------------------------------------------------------


@dataclass
class StalenessContext:
    """Current execution context for evaluating summary freshness.

    Set only the fields relevant to the checks you want to run; fields
    left as ``None`` are skipped without triggering a staleness signal.
    """

    current_commit: str | None = None
    current_branch: str | None = None
    current_task_signature: str | None = None

    # ``None`` = not tracking (skip check); ``{}`` = tracking but nothing found
    current_file_fingerprints: dict[str, str] | None = None
    current_line_fingerprints: dict[str, str] | None = None

    # Exact fact / hypothesis texts that have been refuted by later evidence
    refuted_claims: list[str] = field(default_factory=list)


@dataclass
class StalenessCheckResult:
    """Result of a :meth:`StalenessGuard.check` call."""

    status: StalenessStatusKind | str
    reason: str | None = None


# ---------------------------------------------------------------------------
# StalenessGuard
# ---------------------------------------------------------------------------


class StalenessGuard:
    """Evaluate an ActionSummary against the current context to detect staleness.

    Staleness triggers (checked in priority order):

    1. A refuted claim matches a summary fact or hypothesis -> *contradicted*
    2. Commit hash changed                                  -> *stale*
    3. Branch changed                                       -> *stale*
    4. Task signature changed                               -> *stale*
    5. Referenced file fingerprint changed                  -> *stale*
    6. Referenced file missing from current fingerprints    -> *unknown*
    7. Referenced line-range fingerprint changed            -> *partial*
    8. Referenced line range missing from current           -> *unknown*

    All returned reasons are prompt-safe: no raw file contents or event payloads
    are included, only stable identifiers (paths, truncated commit prefixes).
    """

    def check(
        self,
        summary: ActionSummary,
        context: StalenessContext,
        *,
        summary_branch: str | None = None,
        summary_file_fingerprints: dict[str, str] | None = None,
        summary_line_fingerprints: dict[str, str] | None = None,
    ) -> StalenessCheckResult:
        """Return a :class:`StalenessCheckResult` for *summary* given *context*.

        Parameters
        ----------
        summary:
            The summary whose freshness is being evaluated.
        context:
            The current execution context (commit, branch, fingerprints, ...).
        summary_branch:
            The git branch active when the summary was created.  Compared
            against ``context.current_branch`` when both are provided.
        summary_file_fingerprints:
            File-path -> fingerprint map as of summary creation time.
            Compared against ``context.current_file_fingerprints``.
        summary_line_fingerprints:
            ``"path:start:end"`` -> fingerprint map as of summary creation time.
            Compared against ``context.current_line_fingerprints``.
        """
        # 1. Contradiction (highest priority)
        if context.refuted_claims:
            claim_texts: set[str] = {f.text for f in summary.facts}
            claim_texts.update(h.text for h in summary.hypotheses)
            for refuted in context.refuted_claims:
                if refuted in claim_texts:
                    return StalenessCheckResult(
                        status="contradicted",
                        reason="fact contradicted by later evidence",
                    )

        # 2. Commit hash changed
        if (
            summary.commit is not None
            and context.current_commit is not None
            and summary.commit != context.current_commit
        ):
            sc = summary.commit[:_COMMIT_DISPLAY_LEN]
            cc = context.current_commit[:_COMMIT_DISPLAY_LEN]
            return StalenessCheckResult(
                status="stale",
                reason=f"commit changed ({sc}->{cc})",
            )

        # 3. Branch changed
        if (
            summary_branch is not None
            and context.current_branch is not None
            and summary_branch != context.current_branch
        ):
            return StalenessCheckResult(
                status="stale",
                reason=f"branch changed ({summary_branch}->{context.current_branch})",
            )

        # 4. Task signature changed
        if (
            summary.task_signature is not None
            and context.current_task_signature is not None
            and summary.task_signature != context.current_task_signature
        ):
            return StalenessCheckResult(
                status="stale",
                reason="task signature changed",
            )

        # 5-6. File-level fingerprint changed or missing
        if summary_file_fingerprints is not None and context.current_file_fingerprints is not None:
            for path, expected_fp in summary_file_fingerprints.items():
                current_fp = context.current_file_fingerprints.get(path)
                if current_fp is None:
                    return StalenessCheckResult(
                        status="unknown",
                        reason=f"referenced file not found: {_safe_path(path)}",
                    )
                if current_fp != expected_fp:
                    return StalenessCheckResult(
                        status="stale",
                        reason=f"referenced file changed: {_safe_path(path)}",
                    )

        # 7-8. Line-range fingerprint changed or missing
        if summary_line_fingerprints is not None and context.current_line_fingerprints is not None:
            for key, expected_fp in summary_line_fingerprints.items():
                current_fp = context.current_line_fingerprints.get(key)
                if current_fp is None:
                    return StalenessCheckResult(
                        status="unknown",
                        reason=f"referenced line range not found: {key}",
                    )
                if current_fp != expected_fp:
                    return StalenessCheckResult(
                        status="partial",
                        reason=f"referenced line range changed: {key}",
                    )

        return StalenessCheckResult(status="valid")

    def apply(
        self,
        summary: ActionSummary,
        context: StalenessContext,
        *,
        summary_branch: str | None = None,
        summary_file_fingerprints: dict[str, str] | None = None,
        summary_line_fingerprints: dict[str, str] | None = None,
    ) -> ActionSummary:
        """Return a copy of *summary* with :attr:`~ActionSummary.validity` set.

        Calls :meth:`check` and returns a new :class:`~ActionSummary` whose
        ``validity`` reflects the guard result.  The original is never mutated.
        """
        result = self.check(
            summary,
            context,
            summary_branch=summary_branch,
            summary_file_fingerprints=summary_file_fingerprints,
            summary_line_fingerprints=summary_line_fingerprints,
        )
        new_validity = Validity(status=result.status, reason=result.reason)
        return summary.model_copy(update={"validity": new_validity})


__all__ = [
    "FileFingerprinter",
    "StalenessCheckResult",
    "StalenessContext",
    "StalenessGuard",
]
