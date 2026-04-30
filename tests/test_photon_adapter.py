from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from photon_action_memory import SCHEMA_VERSION
from photon_action_memory.api.schema import EvidenceItem, SuggestRequest
from photon_action_memory.api.server import build_fallback_suggestions
from photon_action_memory.models.checkpoint import (
    CHECKPOINT_FORMAT,
    CheckpointInvalid,
    load_checkpoint_manifest,
)
from photon_action_memory.models.photon_adapter import (
    CHECKPOINT_ENV,
    MlxUnavailable,
    PhotonMLXAdapter,
    configured_checkpoint_path,
    is_model_available,
)
from photon_action_memory.models.state import ActionCandidate, PhotonScoringState


class _FakeArray(list[float]):
    def item(self) -> float:
        return self[0]


class _FakeMlx:
    float32 = "float32"

    def array(self, values: list[float], *, dtype: object | None = None) -> _FakeArray:
        return _FakeArray(values)


def _request(*, user_request: str = "read src/high.py") -> SuggestRequest:
    return SuggestRequest.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": "req-photon-adapter",
            "agent": {"name": "codex"},
            "repo": {"root": "/repo", "name": "example"},
            "task": {"user_request": user_request, "mode": "act"},
            "working_memory": {"touched_files": ["src/low.py", "src/high.py"]},
            "recent_events": [],
            "budget": {"max_suggestions": 2, "max_evidence_chars": 4000},
        }
    )


def _write_manifest(path: Path, *, state: dict[str, object] | None = None) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": CHECKPOINT_FORMAT,
                "model_version": "photon-test-mlx",
                "state": state or {},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_default_import_path_does_not_require_mlx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CHECKPOINT_ENV, raising=False)

    assert configured_checkpoint_path() is None
    assert is_model_available() is False


def test_missing_mlx_dependency_is_model_unavailable(tmp_path: Path) -> None:
    checkpoint = _write_manifest(tmp_path / "manifest.json")

    assert is_model_available(checkpoint, import_module=lambda _name: _raise_mlx()) is False


def test_checkpoint_manifest_drops_unknown_state_keys(tmp_path: Path) -> None:
    checkpoint = _write_manifest(tmp_path / "manifest.json", state={"bias": 0.4, "extra": 1})

    manifest = load_checkpoint_manifest(checkpoint)

    assert manifest.state == {"bias": 0.4}
    assert manifest.warnings == ("dropped unknown checkpoint state key: extra",)


def test_checkpoint_manifest_strict_mode_rejects_unknown_state_keys(tmp_path: Path) -> None:
    checkpoint = _write_manifest(tmp_path / "manifest.json", state={"bias": 0.4, "extra": 1})

    with pytest.raises(CheckpointInvalid, match="unknown keys"):
        load_checkpoint_manifest(checkpoint, strict=True)


def test_adapter_raises_typed_error_when_mlx_missing(tmp_path: Path) -> None:
    checkpoint = _write_manifest(tmp_path / "manifest.json")

    with pytest.raises(MlxUnavailable):
        PhotonMLXAdapter.from_checkpoint(checkpoint, import_module=lambda _name: _raise_mlx())


def test_fake_mlx_smoke_scores_actions_files_and_evidence(tmp_path: Path) -> None:
    checkpoint = _write_manifest(
        tmp_path / "manifest.json",
        state={
            "bias": 0.1,
            "action_weights": {"read": 0.2},
            "file_weights": {"src/high.py": 0.4},
            "evidence_weights": {"evt_001": 0.3},
        },
    )
    adapter = PhotonMLXAdapter.from_checkpoint(
        checkpoint,
        import_module=lambda _name: _FakeMlx(),
    )
    state = PhotonScoringState(request_id="req", task_text="read src/high.py")

    actions = adapter.score_actions(
        state,
        [
            ActionCandidate(kind="read", target="src/low.py"),
            ActionCandidate(kind="read", target="src/high.py"),
        ],
    )
    files = adapter.score_files(state, ["src/high.py"])
    evidence = adapter.score_evidence(
        state,
        [EvidenceItem(id="evt_001", kind="tool_result", summary="opened src/high.py")],
    )

    assert actions[0].score == pytest.approx(0.3)
    assert actions[1].score == pytest.approx(0.75)
    assert files[0].score == pytest.approx(0.55)
    assert evidence[0].score == pytest.approx(0.4)


def test_suggest_falls_back_when_configured_checkpoint_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "bad.json"
    checkpoint.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))

    response = build_fallback_suggestions(_request())

    assert response.model_version == "photon-action-memory-v0.1.0-fallback"
    assert response.suggestions[0].target == "src/high.py"
    assert [warning.kind for warning in response.warnings] == ["model_unavailable"]


def test_suggest_uses_configured_fake_mlx_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _write_manifest(
        tmp_path / "manifest.json",
        state={"bias": 0.1, "file_weights": {"src/high.py": 0.7}},
    )
    monkeypatch.setenv(CHECKPOINT_ENV, str(checkpoint))
    monkeypatch.setattr(
        "photon_action_memory.models.photon_adapter.importlib.import_module",
        lambda _name: _FakeMlx(),
    )

    response = build_fallback_suggestions(_request(user_request="choose next file"))

    assert response.model_version == "photon-test-mlx"
    assert response.suggestions[0].target == "src/high.py"
    assert response.suggestions[0].confidence == pytest.approx(0.8)
    assert response.warnings == []


def _raise_mlx() -> SimpleNamespace:
    raise ModuleNotFoundError("No module named 'mlx'", name="mlx")
