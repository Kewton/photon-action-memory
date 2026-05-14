"""Multilingual overlap detector for task↔summary quality gating.

The legacy detector used a Latin-only token regex (``[a-z0-9]+``), which made
cross-lingual combinations such as a Japanese task paired with an English seed
invisible to the quality gate. This module replaces that with four switchable
modes:

- ``ascii``        — legacy ``[a-z0-9]+`` tokens (kept for parity tests).
- ``multilingual`` — Latin tokens + CJK character bigrams + a small JP→EN
  canonical-form bridge for the verbs and nouns that dominate coding-task
  vocabulary. Strict superset of ``ascii`` for Latin-only inputs.
- ``embedding``    — multilingual sentence embedding similarity, behind an
  optional ``sentence-transformers`` extra. Falls back to ``multilingual``
  when the dependency is unavailable.
- ``hybrid``       — multilingual lexical overlap combined with embedding
  similarity (max), so semantic overlap can still trip thresholds the lexical
  signal missed.

Default mode is ``multilingual`` and can be overridden with the
``PHOTON_OVERLAP_DETECTOR_MODE`` environment variable.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, cast

OverlapDetectorMode = Literal["ascii", "multilingual", "embedding", "hybrid"]

_VALID_MODES: frozenset[str] = frozenset({"ascii", "multilingual", "embedding", "hybrid"})
_DEFAULT_MODE: OverlapDetectorMode = "multilingual"
_ENV_VAR = "PHOTON_OVERLAP_DETECTOR_MODE"

_LOG = logging.getLogger(__name__)

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Hiragana (U+3040–U+309F), Katakana (U+30A0–U+30FF), CJK Unified Ideographs
# (U+4E00–U+9FFF). Long-vowel mark (U+30FC) is in the Katakana block already.
_CJK_RUN_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]+")

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)

# Map common Japanese coding-task vocabulary to a canonical English token so
# JP↔EN combinations share lexical signal. Entries are matched as substrings
# on the raw text before CJK-bigram extraction so multi-character lemmas
# (e.g. ``インタラクティブ``) survive intact.
_JP_TO_CANONICAL: dict[str, str] = {
    # actions / verbs
    "追加": "add",
    "作成": "create",
    "削除": "delete",
    "除去": "remove",
    "修正": "fix",
    "実装": "implement",
    "編集": "edit",
    "変更": "change",
    "更新": "update",
    "書き": "write",
    "書く": "write",
    "設定": "set",
    "上書き": "overwrite",
    "置換": "replace",
    "入れ替え": "replace",
    "挿入": "insert",
    "検証": "verify",
    "確認": "verify",
    "テスト": "test",
    "実行": "run",
    "読み": "read",
    "読む": "read",
    "検索": "search",
    # nouns common in coding tasks
    "ボタン": "button",
    "ページ": "page",
    "ファイル": "file",
    "要素": "element",
    "ルート": "route",
    "ルーター": "router",
    "コンポーネント": "component",
    "テスト用": "test",
    "ユーザー": "user",
    "ユーザ": "user",
    "コード": "code",
    "サーバー": "server",
    "サーバ": "server",
    "クライアント": "client",
    "リクエスト": "request",
    "レスポンス": "response",
    "インタラクティブ": "interactive",
    "動的": "dynamic",
    "静的": "static",
    "ネイティブ": "native",
    "プロジェクト": "project",
}


@dataclass(frozen=True)
class OverlapResult:
    """Outcome of an overlap computation between two texts.

    ``overlap`` is the share of ``summary`` tokens also present in
    ``task`` tokens; ``novel`` is its complement. Both are in [0.0, 1.0].
    """

    overlap: float
    novel: float
    summary_token_count: int
    task_token_count: int
    mode: OverlapDetectorMode


def get_default_overlap_mode() -> OverlapDetectorMode:
    """Return the configured default detector mode.

    Reads ``PHOTON_OVERLAP_DETECTOR_MODE``; unknown values fall back to
    ``multilingual`` with a warning so misconfigured environments do not
    silently regress to ASCII-only behaviour.
    """
    raw = (os.environ.get(_ENV_VAR) or "").strip().lower()
    if not raw:
        return _DEFAULT_MODE
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    _LOG.warning(
        "Unknown %s=%r; falling back to %r",
        _ENV_VAR,
        raw,
        _DEFAULT_MODE,
    )
    return _DEFAULT_MODE


def tokenize(text: str, *, mode: OverlapDetectorMode | None = None) -> set[str]:
    """Tokenize ``text`` under the requested detector ``mode``."""
    effective = mode or get_default_overlap_mode()
    if effective == "ascii":
        return _ascii_tokens(text)
    # multilingual / embedding / hybrid all share the same lexical tokenizer;
    # embedding and hybrid add a semantic boost in compute_overlap().
    return _multilingual_tokens(text)


def compute_overlap(
    summary_text: str,
    task_text: str,
    *,
    mode: OverlapDetectorMode | None = None,
) -> OverlapResult:
    """Compute summary↔task overlap under ``mode``.

    For ``embedding`` / ``hybrid``, an attempt is made to load a multilingual
    sentence embedder; on failure the detector logs once and falls back to
    the lexical ``multilingual`` path so the quality gate remains useful in
    environments without the optional dependency.
    """
    effective = mode or get_default_overlap_mode()
    task_tokens = tokenize(task_text, mode=effective)
    summary_tokens = tokenize(summary_text, mode=effective)
    if not summary_tokens or not task_tokens:
        return OverlapResult(
            overlap=0.0,
            novel=1.0 if summary_tokens else 0.0,
            summary_token_count=len(summary_tokens),
            task_token_count=len(task_tokens),
            mode=effective,
        )
    lexical_overlap = len(summary_tokens & task_tokens) / len(summary_tokens)
    overlap = lexical_overlap
    if effective in {"embedding", "hybrid"}:
        semantic = _semantic_overlap(summary_text, task_text)
        if semantic is not None:
            overlap = max(lexical_overlap, semantic) if effective == "hybrid" else semantic
    return OverlapResult(
        overlap=overlap,
        novel=max(0.0, 1.0 - overlap),
        summary_token_count=len(summary_tokens),
        task_token_count=len(task_tokens),
        mode=effective,
    )


# ---------------------------------------------------------------------------
# tokenization helpers


def _ascii_tokens(text: str) -> set[str]:
    return {token for token in _LATIN_TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS}


def _multilingual_tokens(text: str) -> set[str]:
    """Latin tokens + CJK bigrams + JP→canonical-EN bridge."""
    if not text:
        return set()
    canonical_terms: list[str] = []
    stripped = text
    for jp, canonical in _JP_TO_CANONICAL.items():
        if jp in stripped:
            canonical_terms.append(canonical)
            stripped = stripped.replace(jp, " ")
    tokens: set[str] = _ascii_tokens(stripped)
    tokens.update(canonical_terms)
    tokens.update(_cjk_bigrams(stripped))
    return tokens


def _cjk_bigrams(text: str) -> set[str]:
    """Yield character bigrams over each CJK run in ``text``.

    Bigrams give an effective bag-of-words for CJK text without needing a
    morphological analyser. Single-character runs fall back to the character
    itself so isolated kanji still contribute signal.
    """
    bigrams: set[str] = set()
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            bigrams.add(run)
            continue
        for i in range(len(run) - 1):
            bigrams.add(run[i : i + 2])
    return bigrams


# ---------------------------------------------------------------------------
# embedding hook (optional dependency)

_EMBEDDER: object | None = None
_EMBEDDER_FAILED: bool = False


def _semantic_overlap(summary_text: str, task_text: str) -> float | None:
    """Return cosine similarity ∈ [0,1] from a multilingual embedder.

    Returns ``None`` when no embedder is available so callers can fall back to
    the lexical signal. The embedder is imported lazily and cached for the
    process lifetime; loading is attempted only once.
    """
    global _EMBEDDER, _EMBEDDER_FAILED
    if _EMBEDDER_FAILED:
        return None
    embedder = _EMBEDDER
    if embedder is None:
        embedder = _try_load_embedder()
        if embedder is None:
            _EMBEDDER_FAILED = True
            return None
        _EMBEDDER = embedder
    try:
        encode = cast(Any, embedder).encode
        vectors = encode([summary_text, task_text])
        return _cosine_to_unit(vectors[0], vectors[1])
    except Exception as exc:  # pragma: no cover - depends on optional dep
        _LOG.warning("multilingual embedder failed during encode: %s", exc)
        _EMBEDDER_FAILED = True
        return None


def _try_load_embedder() -> object | None:
    try:
        sentence_transformers = import_module("sentence_transformers")
    except ImportError:
        _LOG.info(
            "sentence-transformers not installed; install photon-action-memory[embedding]"
            " to enable embedding/hybrid overlap detection"
        )
        return None
    sentence_transformer_cls = cast(Any, sentence_transformers).SentenceTransformer
    model_name = os.environ.get(
        "PHOTON_OVERLAP_EMBEDDER_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    try:
        return cast(object, sentence_transformer_cls(model_name))
    except Exception as exc:  # pragma: no cover - depends on network / cache
        _LOG.warning("failed to load multilingual embedder %r: %s", model_name, exc)
        return None


def _cosine_to_unit(a: Any, b: Any) -> float:
    import math

    seq_a: list[float] = [float(x) for x in cast(Iterable[Any], a)]
    seq_b: list[float] = [float(x) for x in cast(Iterable[Any], b)]
    if not seq_a or not seq_b or len(seq_a) != len(seq_b):
        return 0.0
    dot = sum(x * y for x, y in zip(seq_a, seq_b, strict=False))
    na = math.sqrt(sum(x * x for x in seq_a))
    nb = math.sqrt(sum(y * y for y in seq_b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    cosine = dot / (na * nb)
    # Map cosine [-1, 1] → [0, 1] so it composes with lexical ratios.
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


__all__ = [
    "OverlapDetectorMode",
    "OverlapResult",
    "compute_overlap",
    "get_default_overlap_mode",
    "tokenize",
]
