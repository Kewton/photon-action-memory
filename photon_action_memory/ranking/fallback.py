"""No-model deterministic fallback ranking."""

from __future__ import annotations

from dataclasses import dataclass, field

from photon_action_memory.api.schema import EvidenceItem, Suggestion, SuggestRequest
from photon_action_memory.ranking.candidates import extract_candidates, extract_file_paths
from photon_action_memory.ranking.guards import is_destructive_command


@dataclass
class _FileCandidate:
    target: str
    score: int
    first_seen: int
    inspect: bool = False
    evidence_ids: list[str] = field(default_factory=list)


def rank_candidates(candidates: list[str], *, limit: int) -> list[str]:
    """Return deterministic top-k candidates."""
    return extract_candidates(candidates)[: max(limit, 0)]


def build_ranked_suggestions(
    request: SuggestRequest,
    *,
    evidence: list[EvidenceItem],
    limit: int,
) -> list[Suggestion]:
    """Build deterministic fallback suggestions for a suggest request."""
    if limit <= 0:
        return []

    suggestions: list[Suggestion] = []
    evidence_ids = {item.id for item in evidence}

    for candidate in _rank_file_candidates(request):
        suggestions.append(
            Suggestion(
                kind="inspect" if candidate.inspect else "read",
                target=candidate.target,
                confidence=_confidence(candidate.score),
                reason=_file_reason(candidate),
                evidence_ids=[item for item in candidate.evidence_ids if item in evidence_ids],
            )
        )
        if len(suggestions) >= limit:
            return suggestions

    for suggestion in _command_suggestions(request, evidence):
        if is_destructive_command(suggestion.command or ""):
            continue
        suggestions.append(suggestion)
        if len(suggestions) >= limit:
            return suggestions

    suggestions.append(
        Suggestion(
            kind="search",
            query=_fallback_query(request),
            confidence=0.2,
            reason="No model checkpoint is available; search is a low-risk fallback action.",
            evidence_ids=[item.id for item in evidence[:1]],
        )
    )
    return suggestions[:limit]


def _rank_file_candidates(request: SuggestRequest) -> list[_FileCandidate]:
    candidates: dict[str, _FileCandidate] = {}
    first_seen = 0
    touched_files = extract_candidates(
        [item for item in request.working_memory.touched_files if item]
    )
    touched_set = set(touched_files)

    for target in touched_files:
        first_seen = _record_candidate(
            candidates,
            target,
            score=50,
            first_seen=first_seen,
            inspect=False,
            evidence_id=None,
        )

    task_text = " ".join(
        part for part in (request.task.user_request, request.task.summary or "") if part
    )
    for raw_target in extract_file_paths(task_text):
        target = _canonical_target(raw_target, touched_files)
        first_seen = _record_candidate(
            candidates,
            target,
            score=80 if target in touched_set else 55,
            first_seen=first_seen,
            inspect=False,
            evidence_id=None,
        )

    for index, event in enumerate(request.recent_events, start=1):
        payload = event.model_dump()
        error = _is_error_event(payload)
        evidence_id = f"evt_{index:03d}"
        metadata_targets = _metadata_targets(payload)
        summary_targets = extract_file_paths(event.summary)
        for raw_target in metadata_targets + summary_targets:
            target = _canonical_target(raw_target, touched_files)
            score = 70
            if target in touched_set:
                score += 30
            if error:
                score += 100
            first_seen = _record_candidate(
                candidates,
                target,
                score=score,
                first_seen=first_seen,
                inspect=error,
                evidence_id=evidence_id,
            )

    return sorted(
        candidates.values(),
        key=lambda item: (-item.score, item.first_seen, item.target),
    )


def _record_candidate(
    candidates: dict[str, _FileCandidate],
    target: str,
    *,
    score: int,
    first_seen: int,
    inspect: bool,
    evidence_id: str | None,
) -> int:
    clean_target = target.strip()
    if not clean_target:
        return first_seen

    existing = candidates.get(clean_target)
    if existing is None:
        existing = _FileCandidate(
            target=clean_target,
            score=score,
            first_seen=first_seen,
            inspect=inspect,
        )
        candidates[clean_target] = existing
        first_seen += 1
    else:
        existing.score = max(existing.score, score)
        existing.inspect = existing.inspect or inspect

    if evidence_id and evidence_id not in existing.evidence_ids:
        existing.evidence_ids.append(evidence_id)
    return first_seen


def _metadata_targets(payload: dict[str, object]) -> list[str]:
    targets: list[str] = []
    for key in ("target", "file", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            targets.append(value)
    return extract_candidates(targets)


def _canonical_target(target: str, touched_files: list[str]) -> str:
    if "/" in target:
        return target
    matches = [item for item in touched_files if item.rsplit("/", maxsplit=1)[-1] == target]
    if len(matches) == 1:
        return matches[0]
    return target


def _is_error_event(payload: dict[str, object]) -> bool:
    text = " ".join(
        str(payload.get(key) or "") for key in ("type", "status", "summary", "kind")
    ).lower()
    return any(
        marker in text
        for marker in ("error", "failed", "failure", "exception", "traceback", "panic")
    )


def _command_suggestions(request: SuggestRequest, evidence: list[EvidenceItem]) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    text = " ".join(event.summary.lower() for event in request.recent_events)
    evidence_ids = [item.id for item in evidence[:1]]
    if "pytest" in text or "test" in text:
        suggestions.append(
            Suggestion(
                kind="test",
                command="pytest -q",
                confidence=0.25,
                reason="Recent test output was present; rerun the focused test suite.",
                evidence_ids=evidence_ids,
            )
        )
    if "build" in text:
        suggestions.append(
            Suggestion(
                kind="build",
                command="python -m build",
                confidence=0.2,
                reason="Recent build output was present; rerun the package build.",
                evidence_ids=evidence_ids,
            )
        )
    return suggestions


def _confidence(score: int) -> float:
    if score >= 170:
        return 0.55
    if score >= 100:
        return 0.45
    return 0.35


def _file_reason(candidate: _FileCandidate) -> str:
    if candidate.inspect:
        return "Deterministic fallback prioritized a file from a recent error event."
    return "Deterministic fallback prioritized a touched or recently mentioned file."


def _fallback_query(request: SuggestRequest) -> str:
    summary = request.task.summary or request.task.user_request
    if summary:
        return summary[:120]
    return request.request_id
