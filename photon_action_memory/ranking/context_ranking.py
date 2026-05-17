"""Issue #126 — Ranking modes for /v1/context/pack.

Four modes are supported and selected via the
``PHOTON_CONTEXT_PACK_RANKING`` environment variable:

* ``deterministic`` — the existing feedback-adjusted ordering. Default.
* ``photon_shadow`` — compute PHOTON scores but keep deterministic order;
  emit a comparison report so we can measure drift before promoting.
* ``photon_canary`` — apply PHOTON ordering to a subset of requests.
* ``photon`` — apply PHOTON ordering to all requests, after hard gates.

In every mode the operator-controlled answer-leak / safety / staleness /
contradiction gates run first. PHOTON scoring only *re-orders* candidates
that are already admitted into the pack; it can never re-admit an
omitted candidate, and an item ending up at ``score=0`` does not get
suppressed unless an upstream gate already excluded it.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from photon_action_memory.api.schema_v2 import (
    ContextPack,
    ContextPackItem,
    ContextPackWarning,
)
from photon_action_memory.eval.summary_feedback import SummaryFeedbackRecord
from photon_action_memory.models.photon_scorer import (
    ActionMemoryPhotonScorer,
    SummaryCandidate,
)

_logger = logging.getLogger(__name__)

RANKING_MODE_ENV = "PHOTON_CONTEXT_PACK_RANKING"
CANARY_RATIO_ENV = "PHOTON_CONTEXT_PACK_CANARY_RATIO"
PHOTON_WEIGHT_ENV = "PHOTON_CONTEXT_PACK_PHOTON_WEIGHT"

RankingMode = Literal[
    "deterministic",
    "photon_shadow",
    "photon_canary",
    "photon",
]
_VALID_MODES: frozenset[str] = frozenset(
    {"deterministic", "photon_shadow", "photon_canary", "photon"}
)
DEFAULT_MODE: RankingMode = "deterministic"
DEFAULT_PHOTON_WEIGHT: float = 0.4
DEFAULT_CANARY_RATIO: float = 0.1


def resolve_ranking_mode(
    environ: Mapping[str, str] | None = None,
) -> RankingMode:
    """Return the configured ranking mode, defaulting to deterministic."""
    env = environ if environ is not None else os.environ
    raw = (env.get(RANKING_MODE_ENV) or "").strip().lower()
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    return DEFAULT_MODE


def resolve_photon_weight(
    environ: Mapping[str, str] | None = None,
) -> float:
    env = environ if environ is not None else os.environ
    raw = (env.get(PHOTON_WEIGHT_ENV) or "").strip()
    if not raw:
        return DEFAULT_PHOTON_WEIGHT
    try:
        weight = float(raw)
    except ValueError:
        return DEFAULT_PHOTON_WEIGHT
    return max(0.0, min(1.0, weight))


def resolve_canary_ratio(
    environ: Mapping[str, str] | None = None,
) -> float:
    env = environ if environ is not None else os.environ
    raw = (env.get(CANARY_RATIO_ENV) or "").strip()
    if not raw:
        return DEFAULT_CANARY_RATIO
    try:
        ratio = float(raw)
    except ValueError:
        return DEFAULT_CANARY_RATIO
    return max(0.0, min(1.0, ratio))


@dataclass(frozen=True)
class ScoredItem:
    """An item with its base / photon / final score (for shadow reports)."""

    item_id: str
    base_score: float
    photon_score: float
    live_delta: float
    final_score: float


@dataclass
class RankingResult:
    """Outcome of applying a ranking mode to a built ContextPack."""

    pack: ContextPack
    mode: RankingMode
    applied_mode: RankingMode
    scored_items: list[ScoredItem] = field(default_factory=list)
    warnings: list[ContextPackWarning] = field(default_factory=list)
    model_version: str | None = None
    fallback_reason: str | None = None


def apply_ranking_mode(
    pack: ContextPack,
    *,
    mode: RankingMode,
    scorer: ActionMemoryPhotonScorer | None,
    task_text: str,
    request_id: str,
    repo_id: str | None,
    feedback_map: Mapping[str, SummaryFeedbackRecord] | None = None,
    feedback_max_updated_at: str | None = None,
    photon_weight: float = DEFAULT_PHOTON_WEIGHT,
    canary_ratio: float = DEFAULT_CANARY_RATIO,
) -> RankingResult:
    """Apply the configured ranking mode to ``pack.items``.

    Hard gates have already run in :func:`build_context_pack`. This
    function only re-orders the *admitted* items so PHOTON scores cannot
    override the safety / staleness / answer-leak / contradiction gates.

    The function never raises: a missing scorer, an unavailable PHOTON
    model, or a degenerate input simply leaves the deterministic order in
    place and records a ``ranking_mode_fallback`` warning so telemetry can
    track the fail-open reason.
    """
    if mode == "deterministic" or not pack.items:
        return RankingResult(pack=pack, mode=mode, applied_mode="deterministic")

    if scorer is None:
        return _fallback(
            pack=pack,
            mode=mode,
            reason="scorer_unavailable",
        )

    applied_mode: RankingMode = mode
    if mode == "photon_canary" and not _canary_includes(request_id, canary_ratio):
        applied_mode = "photon_shadow"

    candidates = [
        SummaryCandidate(summary_id=item.id, text="", evidence_ids=tuple(item.evidence_ids))
        for item in pack.items
    ]
    try:
        score_result = scorer.score(
            request_id=request_id,
            repo_id=repo_id,
            task_text=task_text,
            candidate_summaries=candidates,
        )
    except Exception as exc:  # pragma: no cover — defensive
        _logger.warning("photon scorer raised in ranking mode %s: %s", mode, exc)
        return _fallback(pack=pack, mode=mode, reason="scorer_error")

    if getattr(score_result, "warnings", ()) and "photon_unavailable" in score_result.warnings:
        return _fallback(
            pack=pack,
            mode=mode,
            reason="photon_unavailable",
            model_version=score_result.model_version,
        )

    photon_by_id = {entry.summary_id: entry.score for entry in score_result.summary_scores}
    scored_items: list[ScoredItem] = []
    base_lookup = {item.id: index for index, item in enumerate(pack.items)}
    item_count = max(1, len(pack.items))
    for item in pack.items:
        base_score = 1.0 - base_lookup[item.id] / item_count
        photon_score = float(photon_by_id.get(item.id, 0.0))
        live_delta = _live_feedback_delta(
            item=item,
            feedback_map=feedback_map,
            feedback_max_updated_at=feedback_max_updated_at,
        )
        final = _clamp(
            base_score * (1.0 - photon_weight) + photon_score * photon_weight + live_delta
        )
        scored_items.append(
            ScoredItem(
                item_id=item.id,
                base_score=round(base_score, 4),
                photon_score=round(photon_score, 4),
                live_delta=round(live_delta, 4),
                final_score=round(final, 4),
            )
        )

    warnings = list(pack.warnings)
    if applied_mode == "photon_shadow":
        warnings.append(
            ContextPackWarning(
                kind="ranking_report",
                message=_shadow_report(scored_items, mode=mode),
            )
        )
        shadow_pack = pack.model_copy(update={"warnings": warnings})
        return RankingResult(
            pack=shadow_pack,
            mode=mode,
            applied_mode=applied_mode,
            scored_items=scored_items,
            warnings=warnings,
            model_version=score_result.model_version,
        )

    reordered = _reorder_items(pack.items, scored_items)
    new_pack = pack.model_copy(update={"items": reordered, "warnings": warnings})
    return RankingResult(
        pack=new_pack,
        mode=mode,
        applied_mode=applied_mode,
        scored_items=scored_items,
        warnings=warnings,
        model_version=score_result.model_version,
    )


def _fallback(
    *,
    pack: ContextPack,
    mode: RankingMode,
    reason: str,
    model_version: str | None = None,
) -> RankingResult:
    warnings = list(pack.warnings) + [
        ContextPackWarning(
            kind="ranking_mode_fallback",
            message=f"requested={mode} fallback_reason={reason}",
        )
    ]
    new_pack = pack.model_copy(update={"warnings": warnings})
    return RankingResult(
        pack=new_pack,
        mode=mode,
        applied_mode="deterministic",
        warnings=warnings,
        model_version=model_version,
        fallback_reason=reason,
    )


def _reorder_items(
    items: Sequence[ContextPackItem],
    scored: Sequence[ScoredItem],
) -> list[ContextPackItem]:
    by_id = {item.id: item for item in items}
    order = sorted(
        enumerate(scored),
        key=lambda pair: (-pair[1].final_score, pair[0]),
    )
    return [by_id[entry.item_id] for _, entry in order if entry.item_id in by_id]


def _shadow_report(scored: Sequence[ScoredItem], *, mode: RankingMode) -> str:
    rows = [
        f"{entry.item_id}:b={entry.base_score}:p={entry.photon_score}:f={entry.final_score}"
        for entry in scored
    ]
    return f"mode={mode} " + ";".join(rows)


def _live_feedback_delta(
    *,
    item: ContextPackItem,  # noqa: ARG001 — kept for stable contract
    feedback_map: Mapping[str, SummaryFeedbackRecord] | None,  # noqa: ARG001
    feedback_max_updated_at: str | None,  # noqa: ARG001
) -> float:
    """Return a tiny delta from feedback that postdates the checkpoint cut.

    Phase 4 keeps the architectural seam for ``live_feedback_delta`` but
    does not double count: the existing ``summary_feedback`` aggregate
    table does not yet carry per-row timestamps, so we cannot tell
    *which* feedback is newer than ``manifest.source.feedback_max_updated_at``.
    Returning 0.0 here is the conservative answer — the deterministic
    feedback ordering in ``build_context_pack`` still surfaces the
    aggregate, and the trained PHOTON score dominates the final order.

    When per-row feedback timestamps land in a follow-up, this function
    is the single place to start emitting a bounded ±0.05 delta.
    """
    return 0.0


def _canary_includes(request_id: str, ratio: float) -> bool:
    if ratio <= 0.0:
        return False
    if ratio >= 1.0:
        return True
    digest = hashlib.sha256(request_id.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / 2**64
    return bucket < ratio


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = [
    "CANARY_RATIO_ENV",
    "DEFAULT_CANARY_RATIO",
    "DEFAULT_MODE",
    "DEFAULT_PHOTON_WEIGHT",
    "PHOTON_WEIGHT_ENV",
    "RANKING_MODE_ENV",
    "RankingMode",
    "RankingResult",
    "ScoredItem",
    "apply_ranking_mode",
    "resolve_canary_ratio",
    "resolve_photon_weight",
    "resolve_ranking_mode",
]
