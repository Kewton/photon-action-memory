#!/usr/bin/env python3
"""CY-5: canary/non-canary 成功率比較スクリプト

~/.local/state/anvil/sessions/*/logs/eval.jsonl を走査し、
photon_canary 別の final_outcome 成功率を集計する。

使い方:
    python3 scripts/cy5_success_rate_analysis.py
    python3 scripts/cy5_success_rate_analysis.py --min-turns 10
    python3 scripts/cy5_success_rate_analysis.py --state-dir /path/to/anvil/sessions
    python3 scripts/cy5_success_rate_analysis.py --json   # JSON 出力
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


SUCCESS_OUTCOMES = {"done"}
FAILURE_OUTCOMES = {"transport_error", "missing_repo_edits", "unsafe_block", "no_progress"}

# rollout-check 相当の閾値
MIN_EVAL_TURNS_DEFAULT = 100


def _default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(xdg) / "anvil" / "sessions"


def _collect(sessions_dir: Path) -> list[dict]:
    records = []
    if not sessions_dir.exists():
        return records
    for entry in sorted(sessions_dir.iterdir()):
        log = entry / "logs" / "eval.jsonl"
        if not log.exists():
            continue
        try:
            with open(log, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # photon_eval が None のレコードも含める（non-canary 側として）
                    records.append({
                        "session_id": r.get("session_id", ""),
                        "photon_canary": r.get("photon_canary", 0),
                        "final_outcome": r.get("final_outcome") or "",
                        "prompt_adopted": (r.get("photon_eval") or {}).get("prompt_adopted"),
                        "success_score": (r.get("anvil_score") or {}).get("success_score"),
                        "photon_eval_present": r.get("photon_eval") is not None,
                    })
        except OSError:
            continue
    return records


def _analyse(records: list[dict]) -> dict:
    canary_group: dict[str, list] = defaultdict(list)   # "sampled" / "unsampled"
    for r in records:
        key = "sampled" if r["photon_canary"] > 0 else "unsampled"
        canary_group[key].append(r)

    def _stats(group: list[dict]) -> dict:
        total = len(group)
        if total == 0:
            return {"total": 0, "success": 0, "failure": 0, "other": 0, "success_rate": None}
        success = sum(1 for r in group if r["final_outcome"] in SUCCESS_OUTCOMES)
        failure = sum(1 for r in group if r["final_outcome"] in FAILURE_OUTCOMES)
        other = total - success - failure
        return {
            "total": total,
            "success": success,
            "failure": failure,
            "other": other,
            "success_rate": round(success / total * 100, 1) if total else None,
        }

    photon_turns = sum(1 for r in records if r["photon_eval_present"])
    adopted_turns = sum(1 for r in records if r["prompt_adopted"] is True)

    return {
        "total_records": len(records),
        "photon_eval_turns": photon_turns,
        "prompt_adopted_turns": adopted_turns,
        "sampled": _stats(canary_group["sampled"]),
        "unsampled": _stats(canary_group["unsampled"]),
        "canary_ratio_distribution": _canary_dist(records),
    }


def _canary_dist(records: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = defaultdict(int)
    for r in records:
        c = r["photon_canary"]
        if c == 0:
            dist["0 (0%)"] += 1
        elif c >= 1000:
            dist["1000 (100%)"] += 1
        elif c >= 500:
            dist[f"{c} (50%+)"] += 1
        elif c >= 100:
            dist[f"{c} (10%+)"] += 1
        else:
            dist[f"{c} (<10%)"] += 1
    return dict(dist)


def _print_report(result: dict, min_turns: int) -> None:
    pev = result["photon_eval_turns"]
    adopted = result["prompt_adopted_turns"]
    s = result["sampled"]
    u = result["unsampled"]

    print("=" * 60)
    print("CY-4/CY-5 Photon Canary 成功率レポート")
    print("=" * 60)

    # CY-4
    cy4_ok = pev >= min_turns
    cy4_mark = "✅" if cy4_ok else "❌"
    print(f"\n[CY-4] eval turns: {pev} / {min_turns} 必要  {cy4_mark}")
    print(f"       prompt_adopted turns: {adopted}")
    print(f"       あと {max(0, min_turns - pev)} turns 必要")

    # CY-5
    print(f"\n[CY-5] 成功率比較 (final_outcome=done を成功とみなす)")
    print(f"       sampled   (canary>0): {s['total']} turns  "
          f"success={s['success']}({s['success_rate']}%)"
          f"  failure={s['failure']}  other={s['other']}")
    print(f"       unsampled (canary=0): {u['total']} turns  "
          f"success={u['success']}({u['success_rate']}%)"
          f"  failure={u['failure']}  other={u['other']}")

    if s["success_rate"] is not None and u["success_rate"] is not None:
        delta = s["success_rate"] - u["success_rate"]
        sign = "+" if delta >= 0 else ""
        verdict = "問題なし (regression なし)" if abs(delta) <= 5 else "要確認 (>5pp 差)"
        print(f"\n       差分 (sampled - unsampled): {sign}{delta:.1f}pp  → {verdict}")
    else:
        print("\n       どちらかのグループにデータがありません")

    print(f"\n[canary 分布]")
    for k, v in sorted(result["canary_ratio_distribution"].items()):
        print(f"       {k}: {v} turns")

    print("\n" + "=" * 60)
    if not cy4_ok:
        print(f"⚠️  CY-4 未達: あと {min_turns - pev} eval turns が必要です")
        print("   ANVIL_PHOTON_ENABLED=true ANVIL_PHOTON_CANARY=500 で Anvil を使い続けてください")
    elif s["total"] < 20 or u["total"] < 20:
        print("⚠️  CY-5: 比較に十分なデータがありません (各 20 turns 以上推奨)")
    else:
        print("✅ CY-4/CY-5 条件を満たしています")


def main() -> int:
    parser = argparse.ArgumentParser(description="CY-5: canary/non-canary 成功率比較")
    parser.add_argument("--state-dir", type=Path, default=_default_state_root(),
                        help="Anvil sessions ディレクトリ (default: ~/.local/state/anvil/sessions)")
    parser.add_argument("--min-turns", type=int, default=MIN_EVAL_TURNS_DEFAULT,
                        help=f"CY-4 の最小 eval turns (default: {MIN_EVAL_TURNS_DEFAULT})")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="JSON 形式で出力")
    args = parser.parse_args()

    records = _collect(args.state_dir)
    if not records:
        print(f"eval.jsonl が見つかりません: {args.state_dir}", file=sys.stderr)
        return 1

    result = _analyse(records)

    if args.json_out:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_report(result, args.min_turns)

    return 0


if __name__ == "__main__":
    sys.exit(main())
