# 01. Concept and Delta from v0.1.0

## 1. 背景

Coding Agent は、問題解決のために多くの tool action を実行する。

代表例:

- grep / ripgrep
- file read
- test
- build
- lint
- edit
- diff inspection
- stack trace inspection
- repo structure inspection

これらの action は有用だが、同時に大量の raw context を発生させる。

- grep の全文出力
- test stdout / stderr
- build log
- stack trace
- file content
- 過去の失敗仮説
- 既に読んだ file の断片
- 既に試した command

この raw context をそのまま prompt に入れ続けると、次の問題が起こる。

1. token cost が増える
2. local LLM の prefill latency が増える
3. VRAM / KV cache を圧迫する
4. 小型モデルが不要情報に引っ張られる
5. 失敗した仮説が事実のように残る
6. 同じ search/read/test を繰り返す
7. task drift が起こる
8. session が長くなるほど prompt が汚れる

v0.2.0 では、この問題を **action-induced context pollution** と呼ぶ。

## 2. v0.2.0 の仮説

v0.2.0 の仮説は次である。

Coding Agent は、過去の tool/action について raw log 全体を知る必要はない。多くの場合、必要なのは以下の概要である。

- 何をしたか
- 何が分かったか
- 何が未解決か
- 何を避けるべきか
- どの evidence を必要時に展開できるか
- 次に何をすべきか

したがって、v0.2.0 では raw tool log を prompt に入れない。raw log は local event store に保存し、prompt には ActionSummary / ContextPack のみを入れる。

## 3. v0.2.0 の基本方針

```
Default:         summary-only
When needed:     summary + selected evidence snippet
Denied by default:
  - raw tool stdout/stderr
  - full grep output
  - full test output
  - full build log
  - full file content already summarized
  - stale summary
  - ungrounded hypothesis
  - repeated failed command output
```

## 4. v0.1.0 から v0.2.0 への進化

### v0.1.0

```
Question:
  現在の task state, repo state, recent tool results, past sessions から、
  agent は次に何をすべきか？
Output:
  suggestions
  evidence
  warnings
```

### v0.2.0

```
Question:
  次の LLM prompt に何を入れるべきか？
  何を入れてはいけないか？
  summary だけで足りるか？
  evidence を展開すべきか？
  古い情報や失敗仮説が context を汚していないか？
Output:
  ContextPack
  ActionSummary
  EvidenceRef
  ContextAdmissionDecision
  SummaryValidationResult
```

## 5. 新しい設計メッセージ

v0.2.0 は「より多く覚える memory」ではない。

```
v0.1.0: remember useful actions
v0.2.0: remember useful actions without polluting context
```

より短く表現すると次である。

> 覚えるための memory ではなく、  
> 汚さずに動くための memory。

## 6. 差別化ポイント

v0.2.0 の差別化は、次に集約する。

- retrieval memory ではなく action-state controller
- context を増やすのではなく context を制限する
- raw log ではなく evidence-grounded summary を prompt に入れる
- summary から必要時だけ evidence へ top-down に降りる
- next action と context admission を同じ SessionActionState から制御する
- local LLM の限られた context / VRAM / attention を守る

## 7. 強い不変条件

v0.2.0 では次の invariant を守る。

| Invariant | 内容 |
|-----------|------|
| Invariant 1 | raw event は local store に保存してよいが、prompt には直接入れない。 |
| Invariant 2 | prompt に入る memory item は summary / warning / selected evidence のみ。 |
| Invariant 3 | fact-like statement は evidence_id なしに prompt-visible にしない。 |
| Invariant 4 | hypothesis は hypothesis として明示し、fact と混ぜない。 |
| Invariant 5 | failed action は done ではなく failed_attempts / avoid として扱う。 |
| Invariant 6 | commit hash / file fingerprint が変わったら summary を stale にする。 |
| Invariant 7 | detail は evidence_id から on-demand に展開する。 |
| Invariant 8 | ContextPack は token budget と pollution budget を持つ。 |
| Invariant 9 | sidecar は final decision maker ではなく advisor である。 |
| Invariant 10 | sidecar failure 時も agent は fail-open で継続する。 |
