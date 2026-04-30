from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "commandmate_codex.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("commandmate_codex", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_worktrees_accepts_commandmate_shape() -> None:
    module = load_script()
    payload = """
    {
      "worktrees": [
        {
          "id": "repo-issue-1",
          "path": "/tmp/repo-issue-1",
          "status": "running",
          "sessionStatusByCli": {
            "codex": {"isProcessing": true}
          }
        }
      ]
    }
    """

    sessions = module.parse_worktrees(payload)

    assert len(sessions) == 1
    assert sessions[0].id == "repo-issue-1"
    assert sessions[0].is_processing is True


def test_build_send_command_defaults_to_no_agent() -> None:
    module = load_script()

    cmd = module.build_send_command("repo-issue-1", "hello")

    assert "--agent" not in cmd
    assert cmd[:4] == ["commandmatedev", "send", "repo-issue-1", "hello"]
