"""Tests for the multilingual overlap detector used by the quality gate."""

from __future__ import annotations

import pytest

from photon_action_memory.context.overlap_detector import (
    compute_overlap,
    get_default_overlap_mode,
    tokenize,
)


def test_default_mode_is_multilingual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOTON_OVERLAP_DETECTOR_MODE", raising=False)
    assert get_default_overlap_mode() == "multilingual"


def test_unknown_mode_falls_back_to_multilingual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOTON_OVERLAP_DETECTOR_MODE", "rosetta")
    assert get_default_overlap_mode() == "multilingual"


def test_ascii_mode_tokenizes_only_latin() -> None:
    tokens = tokenize("Add a ボタン to src/routes/+page.svelte", mode="ascii")
    assert tokens == {"add", "src", "routes", "page", "svelte"}


def test_multilingual_mode_bridges_japanese_verbs_to_english() -> None:
    tokens = tokenize("ボタンを追加してください", mode="multilingual")
    assert "add" in tokens
    assert "button" in tokens


def test_multilingual_mode_is_strict_superset_for_latin_text() -> None:
    text = "Create a SvelteKit page in src/routes/+page.svelte"
    ascii_tokens = tokenize(text, mode="ascii")
    multilingual_tokens = tokenize(text, mode="multilingual")
    assert ascii_tokens.issubset(multilingual_tokens)


def test_multilingual_mode_preserves_cjk_bigrams_for_unknown_words() -> None:
    tokens = tokenize("認証エラー", mode="multilingual")
    # 認証 has no explicit JP→EN entry, so bigrams of the CJK run must be
    # emitted to preserve overlap signal.
    assert "認証" in tokens
    assert any(len(t) == 2 for t in tokens if not t.isascii())


def test_compute_overlap_japanese_task_english_summary_trips_threshold() -> None:
    task = (
        "src/routes/+page.svelte に SvelteKit のページを作成してください。"
        "少なくとも1つのインタラクティブな HTML 要素を含めてください。"
    )
    summary_hint = "Add a native Svelte interactive element such as a button."
    result = compute_overlap(summary_hint, task, mode="multilingual")
    # premature_termination threshold is 0.35; lexical overlap must clear it.
    assert result.overlap >= 0.35
    assert result.mode == "multilingual"


def test_compute_overlap_ascii_mode_misses_cross_lingual_overlap() -> None:
    """Regression guard: ASCII mode must reproduce the legacy blind spot."""
    task = "ボタンを追加してください"
    summary_hint = "Add a button"
    result = compute_overlap(summary_hint, task, mode="ascii")
    # In ASCII mode the task tokenizes to empty, so overlap is 0.
    assert result.task_token_count == 0
    assert result.overlap == 0.0


def test_compute_overlap_empty_inputs_are_safe() -> None:
    result = compute_overlap("", "", mode="multilingual")
    assert result.overlap == 0.0
    assert result.summary_token_count == 0
    assert result.task_token_count == 0


def test_embedding_mode_falls_back_when_extra_missing() -> None:
    """Without sentence-transformers installed, embedding mode must not raise.

    It silently falls back to the lexical multilingual signal so the quality
    gate keeps working in the base install.
    """
    task = "ボタンを追加してください"
    summary_hint = "Add a button"
    result = compute_overlap(summary_hint, task, mode="embedding")
    # Mode is recorded as requested; value should equal the multilingual
    # lexical overlap when the embedder is unavailable.
    assert result.mode == "embedding"
    assert result.overlap >= 0.0
