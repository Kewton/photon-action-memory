"""LLM-backed ActionSummary draft generator (opt-in, fail-open).

The generator is only constructed when ``PHOTON_SUMMARY_GENERATOR=llm``.
Importing this module must never trigger an MLX or model download; the MLX
import lives in :func:`_load_mlx_generator` and is exercised lazily inside
:meth:`LLMDraftSummaryGenerator.build`.

Every error path returns a deterministic rule-based summary plus a
closed-enum fallback reason. The pipeline cannot bypass schema validation,
evidence-grounding, the answer-leak quality gate, or the fidelity checker.
The prompt fed to the model is built from a small allowlist DTO
(:class:`SummaryDraftEventFrame`) so raw stdout/stderr, full diffs, full
user prompts, secrets, and home paths cannot reach the model.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from photon_action_memory.api.schema_v2 import (
    DEFAULT_SCHEMA_VERSION_V2,
    ActionChunk,
    ActionSummary,
    Fact,
    Hypothesis,
    Validity,
)
from photon_action_memory.context.raw_policy import has_sensitive_content
from photon_action_memory.eval.summary_fidelity import SummaryFidelityChecker
from photon_action_memory.governance.answer_leak import evaluate_summary_quality
from photon_action_memory.memory.sanitizer import sanitize_text_with_report
from photon_action_memory.memory.summaries import (
    ActionSummaryBuilder,
    SummaryCanonicalizer,
)
from photon_action_memory.memory.summary_generator import (
    RuleBasedSummaryGenerator,
    SummaryGenerationAborted,
    SummaryGeneratorFallbackReason,
    SummaryGeneratorReport,
)

_logger = logging.getLogger(__name__)

# Env knobs (also referenced by `make_summary_generator`).
SUMMARY_LLM_MODEL_ENV = "PHOTON_SUMMARY_LLM_MODEL"
SUMMARY_LLM_FALLBACK_POLICY_ENV = "PHOTON_SUMMARY_LLM_FALLBACK_POLICY"
SUMMARY_LLM_TEMPERATURE_ENV = "PHOTON_SUMMARY_LLM_TEMPERATURE"
SUMMARY_LLM_MAX_TOKENS_ENV = "PHOTON_SUMMARY_LLM_MAX_TOKENS"
SUMMARY_LLM_SEED_ENV = "PHOTON_SUMMARY_LLM_SEED"

_DEFAULT_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
_DEFAULT_TEMPERATURE = 0.1
_DEFAULT_MAX_TOKENS = 512
_DEFAULT_SEED = 1729

# Per-evidence excerpt is intentionally small — the model only needs a hint
# that the event exists, not its full body.
_EVIDENCE_EXCERPT_CHARS = 320
_EVIDENCE_EXCERPT_LIMIT = 8


class MlxUnavailable(RuntimeError):
    """MLX (or mlx_lm) is not installed."""


class ModelUnavailable(RuntimeError):
    """The configured model identifier cannot be resolved locally."""


@dataclass(frozen=True)
class LLMDraftConfig:
    """Resolved configuration for the LLM draft generator."""

    model: str = _DEFAULT_MODEL
    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS
    seed: int = _DEFAULT_SEED
    fallback_policy: str = "rule_based"


@dataclass(frozen=True)
class SummaryDraftEvent:
    """Sanitized event excerpt safe to send to the LLM."""

    event_id: str
    excerpt: str


@dataclass(frozen=True)
class SummaryDraftEventFrame:
    """Allowlist DTO assembled from a chunk before LLM exposure.

    Only fields named here may reach the model. The frame strips raw
    stdout/stderr, full diffs, full user prompts, secrets, and home paths
    via :func:`sanitize_text_with_report` and re-checks every survivor with
    :func:`has_sensitive_content`. Anything still flagged is dropped.
    """

    chunk_id: str
    kind: str
    outcome: str
    summary: str
    evidence_ids: tuple[str, ...]
    event_excerpts: tuple[SummaryDraftEvent, ...] = field(default_factory=tuple)


def build_llm_draft_config(env: Mapping[str, str]) -> LLMDraftConfig:
    """Resolve :class:`LLMDraftConfig` from environment variables."""
    policy = (env.get(SUMMARY_LLM_FALLBACK_POLICY_ENV) or "rule_based").strip().lower()
    if policy not in {"rule_based", "abort"}:
        policy = "rule_based"
    return LLMDraftConfig(
        model=(env.get(SUMMARY_LLM_MODEL_ENV) or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL,
        temperature=_safe_float(env.get(SUMMARY_LLM_TEMPERATURE_ENV), _DEFAULT_TEMPERATURE),
        max_tokens=_safe_int(env.get(SUMMARY_LLM_MAX_TOKENS_ENV), _DEFAULT_MAX_TOKENS),
        seed=_safe_int(env.get(SUMMARY_LLM_SEED_ENV), _DEFAULT_SEED),
        fallback_policy=policy,
    )


def _safe_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _safe_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def build_event_frame(
    chunk: ActionChunk,
    evidence_records: Sequence[Mapping[str, Any]] | None,
) -> SummaryDraftEventFrame:
    """Build the allowlist :class:`SummaryDraftEventFrame` for ``chunk``.

    All textual fields are sanitized before they enter the frame. The chunk
    summary itself is sanitized too: even though it was already processed
    on ingest, summaries can be authored by callers and a defence-in-depth
    second pass is cheap.
    """
    safe_summary = sanitize_text_with_report(chunk.summary).text
    if has_sensitive_content(safe_summary):
        # Drop offending content rather than risk leaking it to the model.
        safe_summary = ""

    excerpts = _build_event_excerpts(chunk.event_ids, evidence_records)

    return SummaryDraftEventFrame(
        chunk_id=chunk.chunk_id,
        kind=str(chunk.kind),
        outcome=str(chunk.outcome),
        summary=safe_summary,
        evidence_ids=tuple(chunk.event_ids),
        event_excerpts=excerpts,
    )


def _build_event_excerpts(
    event_ids: Sequence[str],
    evidence_records: Sequence[Mapping[str, Any]] | None,
) -> tuple[SummaryDraftEvent, ...]:
    if not evidence_records:
        return ()
    by_id: dict[str, Mapping[str, Any]] = {}
    for record in evidence_records:
        eid = record.get("evidence_id") or record.get("event_id")
        if isinstance(eid, str) and eid:
            by_id[eid] = record

    out: list[SummaryDraftEvent] = []
    for event_id in event_ids[:_EVIDENCE_EXCERPT_LIMIT]:
        matched_record = by_id.get(event_id)
        if matched_record is None:
            continue
        text = _extract_evidence_text(matched_record)
        if not text:
            continue
        sanitized = sanitize_text_with_report(text, max_chars=_EVIDENCE_EXCERPT_CHARS).text
        if not sanitized or has_sensitive_content(sanitized):
            continue
        out.append(SummaryDraftEvent(event_id=event_id, excerpt=sanitized))
    return tuple(out)


_EVIDENCE_TEXT_FIELDS = ("content", "text", "message", "output", "body", "summary")


def _extract_evidence_text(record: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _EVIDENCE_TEXT_FIELDS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


_SYSTEM_PROMPT = (
    "You convert one ActionChunk into a JSON ActionSummary. "
    "Output STRICT JSON only — no prose, no markdown, no thinking tags. "
    "Every fact MUST cite at least one evidence_id taken verbatim from the "
    "chunk's evidence_ids. Do not invent evidence_ids. Use hypotheses for "
    "unconfirmed claims and failed_attempts for failures. Never include raw "
    "stdout, stderr, file paths, secrets, or the user's prompt."
)


def build_user_prompt(frame: SummaryDraftEventFrame) -> str:
    """Serialize the allowlist frame to the JSON the model is asked to expand."""
    payload = {
        "chunk_id": frame.chunk_id,
        "kind": frame.kind,
        "outcome": frame.outcome,
        "summary": frame.summary,
        "evidence_ids": list(frame.evidence_ids),
        "events": [{"event_id": ev.event_id, "excerpt": ev.excerpt} for ev in frame.event_excerpts],
        "schema": {
            "facts": [{"text": "...", "evidence_ids": ["..."], "confidence": 0.0}],
            "hypotheses": [
                {"text": "...", "evidence_ids": ["..."], "confidence": 0.0, "status": "open"},
            ],
            "failed_attempts": [
                {"action": "...", "outcome": "...", "evidence_ids": ["..."]},
            ],
            "next_hints": [{"kind": "...", "reason": "...", "confidence": 0.0}],
        },
    }
    return json.dumps(payload, ensure_ascii=False)


GeneratorCallable = Callable[[str, str, LLMDraftConfig], str]


@dataclass
class LLMDraftSummaryGenerator:
    """Optional LLM-backed generator. Falls back deterministically on error."""

    config: LLMDraftConfig
    generator_callable: GeneratorCallable
    rule_based: RuleBasedSummaryGenerator = field(default_factory=RuleBasedSummaryGenerator)
    canonicalizer: SummaryCanonicalizer = field(default_factory=SummaryCanonicalizer)

    @classmethod
    def from_config(
        cls,
        config: LLMDraftConfig,
        *,
        generator_callable: GeneratorCallable | None = None,
    ) -> LLMDraftSummaryGenerator:
        callable_ = generator_callable or _load_mlx_generator(config)
        return cls(config=config, generator_callable=callable_)

    def build(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None = None,
        evidence_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[ActionSummary, SummaryGeneratorReport]:
        try:
            return self._build_or_raise(
                chunk,
                summary_id=summary_id,
                evidence_records=evidence_records,
            )
        except _LLMFallback as fallback:
            return self._fallback(chunk, summary_id, evidence_records, fallback.reason)

    def _build_or_raise(
        self,
        chunk: ActionChunk,
        *,
        summary_id: str | None,
        evidence_records: Sequence[Mapping[str, Any]] | None,
    ) -> tuple[ActionSummary, SummaryGeneratorReport]:
        try:
            frame = build_event_frame(chunk, evidence_records)
        except Exception as exc:  # noqa: BLE001 — sanitization is best-effort
            _logger.warning(
                "summary draft frame build failed for chunk=%s err=%s",
                chunk.chunk_id,
                type(exc).__name__,
            )
            raise _LLMFallback("generation_exception") from exc

        prompt = build_user_prompt(frame)
        try:
            raw_output = self.generator_callable(_SYSTEM_PROMPT, prompt, self.config)
        except MlxUnavailable as exc:
            raise _LLMFallback("mlx_unavailable") from exc
        except ModelUnavailable as exc:
            raise _LLMFallback("model_unavailable") from exc
        except Exception as exc:  # noqa: BLE001 — boundary; reason logged only by name
            _logger.warning(
                "summary draft generation failed chunk=%s exc=%s",
                chunk.chunk_id,
                type(exc).__name__,
            )
            raise _LLMFallback("generation_exception") from exc

        if not raw_output or not raw_output.strip():
            raise _LLMFallback("empty_output")

        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError) as exc:
            raise _LLMFallback("invalid_json") from exc
        if not isinstance(parsed, Mapping):
            raise _LLMFallback("invalid_json")

        try:
            summary = self._materialize_summary(chunk, parsed, summary_id)
        except _SchemaInvalid as exc:
            raise _LLMFallback("schema_validation_failed") from exc

        summary = self.canonicalizer.canonicalize(summary).summary

        quality = evaluate_summary_quality(summary)
        if quality.status != "clean":
            raise _LLMFallback("quality_gate_rejected")

        if evidence_records:
            try:
                checker = SummaryFidelityChecker(records=[dict(r) for r in evidence_records])
                result = checker.check(summary)
                if result.status == "invalid":
                    raise _LLMFallback("fidelity_invalid")
            except _LLMFallback:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "summary draft fidelity check failed chunk=%s exc=%s",
                    chunk.chunk_id,
                    type(exc).__name__,
                )
                raise _LLMFallback("generation_exception") from exc

        return summary, SummaryGeneratorReport(generator_used="llm")

    def _fallback(
        self,
        chunk: ActionChunk,
        summary_id: str | None,
        evidence_records: Sequence[Mapping[str, Any]] | None,
        reason: SummaryGeneratorFallbackReason,
    ) -> tuple[ActionSummary, SummaryGeneratorReport]:
        if self.config.fallback_policy == "abort":
            raise SummaryGenerationAborted(reason)
        summary, _ = self.rule_based.build(
            chunk,
            summary_id=summary_id,
            evidence_records=evidence_records,
        )
        return summary, SummaryGeneratorReport(
            generator_used="rule_based",
            fallback_reason=reason,
        )

    def _materialize_summary(
        self,
        chunk: ActionChunk,
        parsed: Mapping[str, Any],
        summary_id: str | None,
    ) -> ActionSummary:
        """Build an :class:`ActionSummary` from the LLM JSON.

        Only ``facts``, ``hypotheses``, ``failed_attempts``, and
        ``next_hints`` are read from the model output; everything else (ids,
        session metadata, ``actions_done``) is filled deterministically from
        ``chunk`` so the LLM cannot rewrite history or invent evidence.
        """
        allowed_evidence = set(chunk.event_ids)

        facts: list[Fact] = []
        for raw in _as_sequence(parsed.get("facts")):
            text = _coerce_str(raw.get("text"))
            if not text:
                continue
            evidence = _filter_evidence(raw.get("evidence_ids"), allowed_evidence)
            if not evidence:
                raise _SchemaInvalid("fact missing valid evidence_id")
            confidence = _coerce_float(raw.get("confidence"), default=0.7)
            facts.append(Fact(text=text, evidence_ids=evidence, confidence=confidence))

        hypotheses: list[Hypothesis] = []
        for raw in _as_sequence(parsed.get("hypotheses")):
            text = _coerce_str(raw.get("text"))
            if not text:
                continue
            evidence = _filter_evidence(raw.get("evidence_ids"), allowed_evidence)
            confidence = _coerce_float(raw.get("confidence"), default=0.5)
            status_raw = _coerce_str(raw.get("status")) or "open"
            status = status_raw if status_raw in {"open", "confirmed", "rejected"} else "open"
            hypotheses.append(
                Hypothesis(
                    text=text,
                    evidence_ids=evidence,
                    confidence=confidence,
                    status=status,
                )
            )

        # We keep failed_attempts / next_hints deterministic — start from the
        # rule-based pass so behaviour stays consistent and the LLM cannot
        # silently delete a failure record.
        baseline = ActionSummaryBuilder().build(chunk, summary_id=summary_id)

        return baseline.model_copy(
            update={
                "schema_version": DEFAULT_SCHEMA_VERSION_V2,
                "facts": facts,
                "hypotheses": hypotheses,
                "validity": Validity(status="valid"),
            }
        )


class _LLMFallback(Exception):
    """Internal control-flow signal; never escapes :meth:`build`."""

    def __init__(self, reason: SummaryGeneratorFallbackReason) -> None:
        super().__init__(reason)
        self.reason: SummaryGeneratorFallbackReason = reason


class _SchemaInvalid(ValueError):
    """Raised when LLM output cannot be coerced into a safe :class:`ActionSummary`."""


def _as_sequence(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_float(value: Any, *, default: float) -> float:
    if isinstance(value, int | float):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return default
        if 0.0 <= f <= 1.0:
            return f
    return default


def _filter_evidence(value: Any, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item in allowed]


def _load_mlx_generator(config: LLMDraftConfig) -> GeneratorCallable:
    """Build the actual MLX-backed generator callable.

    This function is invoked lazily and only when the LLM generator is
    constructed via the factory in ``llm`` mode. It must raise
    :class:`MlxUnavailable` or :class:`ModelUnavailable` (never network-fetch)
    so CI without ``mlx_lm`` keeps passing.
    """
    if not _model_present_locally(config.model):
        raise ModelUnavailable(f"model not found locally: {config.model}")

    try:
        mlx_lm = importlib.import_module("mlx_lm")
    except ModuleNotFoundError as exc:
        if exc.name in {"mlx", "mlx_lm", "mlx.core"}:
            raise MlxUnavailable("optional dependency 'mlx_lm' is not installed") from exc
        raise
    load = getattr(mlx_lm, "load", None)
    generate = getattr(mlx_lm, "generate", None)
    if load is None or generate is None:
        raise MlxUnavailable("mlx_lm is missing 'load'/'generate' entry points")

    model, tokenizer = load(config.model)

    def _call(system_prompt: str, user_prompt: str, cfg: LLMDraftConfig) -> str:
        formatted = f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>\n"
        result = generate(
            model,
            tokenizer,
            prompt=formatted,
            temp=cfg.temperature,
            max_tokens=cfg.max_tokens,
            seed=cfg.seed,
            verbose=False,
        )
        return str(result) if result is not None else ""

    return _call


def _model_present_locally(model_id: str) -> bool:
    """Best-effort local-only check so we never trigger a network download."""
    try:
        hub = importlib.import_module("huggingface_hub")
    except ModuleNotFoundError:
        # huggingface_hub is part of mlx_lm; if it is missing the user is in
        # an unsupported state anyway. Treat as unavailable to be safe.
        return False

    try_to_load_from_cache = getattr(hub, "try_to_load_from_cache", None)
    if not callable(try_to_load_from_cache):
        return False

    config_path = try_to_load_from_cache(repo_id=model_id, filename="config.json")
    if not config_path:
        return False
    return os.path.exists(config_path)


__all__ = [
    "LLMDraftConfig",
    "LLMDraftSummaryGenerator",
    "MlxUnavailable",
    "ModelUnavailable",
    "SUMMARY_LLM_FALLBACK_POLICY_ENV",
    "SUMMARY_LLM_MAX_TOKENS_ENV",
    "SUMMARY_LLM_MODEL_ENV",
    "SUMMARY_LLM_SEED_ENV",
    "SUMMARY_LLM_TEMPERATURE_ENV",
    "SummaryDraftEvent",
    "SummaryDraftEventFrame",
    "build_event_frame",
    "build_llm_draft_config",
    "build_user_prompt",
]
