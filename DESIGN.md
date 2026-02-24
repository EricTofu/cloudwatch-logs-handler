# CloudWatch Logs Handler — 設計ドキュメント

> 作成日: 2026-02-19 | 更新日: 2026-02-22

## 1. 背景・課題

- AWS上の1つのアカウントに**複数プロジェクト**が存在し、**同じロググループ**にログを出力している
- ログストリーム名にプロジェクト識別子が含まれるが、ログ本文には含まれない
- 各プロジェクトごとに**特定のキーワードを監視**し、Slackに通知したい
- 将来的にはロググループをプロジェクトごとに分離する予定

## 2. 要件

| カテゴリ | 要件 |
|---------|------|
| 監視 | 複数プロジェクトのキーワード検知を1つの Lambda で実現 |
| 通知先 | GLOBAL / プロジェクト / キーワード 単位でカスタマイズ可能 |
| 通知内容 | テンプレートベースで GLOBAL / プロジェクト / キーワード 単位でカスタマイズ可能 |
| 通知頻度 | 重複抑制 + 再通知間隔。間隔はカスタマイズ可能 |
| 緊急度 | critical / warning / info の3段階。通知先・通知方法に連動 |
| 除外リスト | キーワードに一致しても特定パターンを含むログは通知対象外にできる |
| 可視化 | キーワード検出頻度を CloudWatch ダッシュボードで可視化 |
| 設定管理 | DynamoDB でリアルタイムに設定変更可能 |
| 将来対応 | ロググループ分離後も Lambda コード変更なしで動作 |

## 3. アーキテクチャ

### 3.1 全体構成図

```
                    ┌─────────────────────┐
                    │  DynamoDB            │
                    │  ┌───────────────┐   │
                    │  │ GLOBAL CONFIG │   │
                    │  │ PROJECT (×N)  │   │
                    │  │ STATE (自動)   │   │
                    │  └───────────────┘   │
                    └──────────┬──────────┘
                         読み取り / 書き込み
                               │
  EventBridge ──────────► Lambda (monitor)
  (5分間隔)                    │
                               ├──── CloudWatch Logs API で検索
                               │         │
                               │     共有ロググループ
                               │     /aws/app/shared-logs
                               │         ├── project-a/stream-1
                               │         ├── project-b/stream-1
                               │         └── ...
                               │
                               ├──── PutMetricData (可視化用)
                               │         │
                               │     CloudWatch メトリクス
                               │         └── ダッシュボード
                               │
                               └──── SNS Publish (通知)
                                         │
                               ┌─────────┼─────────┐
                               │         │         │
                          SNS Topic  SNS Topic  SNS Topic
                         (critical)  (warning)   (info)
                               │         │         │
                          Chatbot    Chatbot    Chatbot
                               │         │         │
                          Slack      Slack      Slack
```

### 3.2 データフロー

```
┌──────────────────────────────────────────────────────────────────────┐
│ Lambda 実行フロー（5分ごと）                                          │
│                                                                      │
│  ① DynamoDB から GLOBAL + 全 PROJECT を取得                           │
│          │                                                           │
│          ▼                                                           │
│  ② プロジェクトごとにログ検索                                          │
│     ┌──────────────────────────────────────────┐                     │
│     │ for each project:                        │                     │
│     │   for each monitor:                      │                     │
│     │     FilterLogEvents(                     │                     │
│     │       log_group, stream_prefix, keyword, │                     │
│     │       start=last_searched_at,            │                     │
│     │       end=now - 2min                     │                     │
│     │     )                                    │                     │
│     └──────────────────────────────────────────┘                     │
│          │                                                           │
│          ▼                                                           │
│  ③ 除外パターンでフィルタリング                                        │
│     ┌──────────────────────────────────────────┐                     │
│     │ PROJECT.exclude_patterns で除外            │                     │
│     │ MONITOR.exclude_patterns で除外            │                     │
│     └──────────────────────────────────────────┘                     │
│          │                                                           │
│          ▼                                                           │
│  ④ 状態遷移の判定（DynamoDB STATE を参照）                              │
│     ┌───────────────────────────────────────────────────────┐        │
│     │ 検出あり & status=OK      → NOTIFY（初回通知）          │        │
│     │ 検出あり & status=ALARM   → 再通知間隔チェック           │        │
│     │ 検出なし & status=ALARM   → RECOVER（復旧）            │        │
│     │ 検出なし & status=OK      → NOOP                      │        │
│     └───────────────────────────────────────────────────────┘        │
│          │                                                           │
│          ▼                                                           │
│  ⑤ 通知送信（該当する場合のみ）                                        │
│     ┌─────────────────────────────────────────────┐                  │
│     │ 通知先: MONITOR → PROJECT → GLOBAL の順で解決  │                  │
│     │ テンプレート: 同上の優先順位で解決              │                  │
│     │ 検出ログの先頭 N 行を含める                    │                  │
│     └─────────────────────────────────────────────┘                  │
│          │                                                           │
│          ▼                                                           │
│  ⑥ DynamoDB STATE 更新 & PutMetricData                               │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 将来の移行パス

```
【現在: 共有ロググループ】              【将来: 分離後】

 /aws/app/shared-logs                 /aws/app/project-a ←─┐
      │                               /aws/app/project-b    │
  Lambda が stream_prefix で           /aws/app/project-c    │
  プロジェクトを識別して検索                                    │
                                      DynamoDB の設定変更のみ │
                                      override_log_group ────┘
                                      stream_prefix → null

                                      Lambda コードは変更なし！
```

## 4. DynamoDB テーブル設計

### テーブル名: `log-monitor`

**キー構成**: `pk` (Partition Key) + `sk` (Sort Key)

**レコード種類は2つだけ**（+ Lambda 自動管理の STATE）:

```
pk              sk              管理者          説明
──────────────  ──────────────  ──────────────  ──────────────────
GLOBAL          CONFIG          人間が編集       グローバル設定
PROJECT         project-a       人間が編集       プロジェクト設定
PROJECT         project-b       人間が編集       プロジェクト設定
STATE           project-a#ERROR Lambda が自動管理 状態（人間は触らない）
STATE           project-a#TIMEOUT Lambda が自動管理 状態
```

### 4.1 GLOBAL#CONFIG（グローバル設定 — 1レコード）

SNS通知先、デフォルトテンプレート、デフォルト値をすべて1レコードに集約。

```json
{
  "pk": "GLOBAL",
  "sk": "CONFIG",

  "source_log_group": "/aws/app/shared-logs",
  "metric_namespace": "LogMonitor",
  "max_log_lines": 20,

  "defaults": {
    "severity": "warning",
    "renotify_min": 60,
    "notify_on_recover": true
  },

  "sns_topics": {
    "critical": "arn:aws:sns:ap-northeast-1:123456789:critical-alerts",
    "warning":  "arn:aws:sns:ap-northeast-1:123456789:warning-alerts",
    "info":     "arn:aws:sns:ap-northeast-1:123456789:info-alerts"
  },

  "notification_template": {
    "subject": "[{severity}] {project} - {keyword} 検出",
    "body": "🚨 *{project}* で *{keyword}* が {count}件 検出\n⏰ {detected_at}\n📁 {log_group}\n---\n{log_lines}"
  }
}
```

### 4.2 PROJECT レコード（プロジェクト設定 — 1プロジェクト1レコード）

モニター、除外パターン、プロジェクト固有の通知先・テンプレートをすべて1レコードに集約。

```json
{
  "pk": "PROJECT",
  "sk": "project-a",

  "display_name": "Project Alpha",
  "stream_prefix": "project-a",
  "override_log_group": null,
  "enabled": true,
  "exclude_patterns": ["healthcheck", "ping OK"],
  "last_searched_at": "2026-02-20T05:10:00Z",

  "override_sns_topics": {
    "critical": "arn:aws:sns:...:project-a-critical",
    "warning":  "arn:aws:sns:...:project-a-warning"
  },

  "notification_template": {
    "subject": "[{severity}] Project Alpha - {keyword}",
    "body": "🔔 *Project Alpha*\nキーワード: {keyword}\n検出数: {count}\n---\n{log_lines}"
  },

  "monitors": [
    {
      "keyword": "ERROR",
      "severity": "critical",
      "exclude_patterns": ["ERROR: connection reset", "ERROR: cache miss"]
    },
    {
      "keyword": "TIMEOUT",
      "severity": "warning",
      "renotify_min": null
    },
    {
      "keyword": "OOM",
      "severity": "critical",
      "override_sns_topic": "arn:aws:sns:...:team-b-alerts",
      "notification_template": {
        "subject": "[OOM] Project Alpha - 緊急",
        "body": "💀 *OOM 発生！*\n即時対応が必要です\n---\n{log_lines}"
      }
    }
  ]
}
```

**最小構成**（カスタマイズ不要な場合）:

```json
{
  "pk": "PROJECT",
  "sk": "project-b",
  "display_name": "Project Beta",
  "stream_prefix": "project-b",
  "enabled": true,
  "monitors": [
    { "keyword": "ERROR", "severity": "critical" },
    { "keyword": "WARN",  "severity": "info" }
  ]
}
```

指定しないフィールドはすべて GLOBAL のデフォルトにフォールバック。

> **Note**: `last_searched_at` は Lambda が自動管理するフィールドのため、人間が設定する必要はない。初回実行時は自動的に直近5分間を検索する。

### 4.3 STATE レコード（Lambda 自動管理 — 人間は触らない）

```json
{
  "pk": "STATE",
  "sk": "project-a#ERROR",
  "status": "ALARM",
  "last_detected_at": "2026-02-20T05:10:00Z",
  "last_notified_at": "2026-02-20T05:10:00Z",
  "detection_count": 42,
  "current_streak": 3
}
```

STATE は Lambda が初回検出時に自動作成。人間が手動で作成する必要はない。

## 5. カスタマイズ詳細

### 5.1 通知先の解決（3段階フォールバック）

```
優先順位（高 → 低）:

  1. MONITOR の override_sns_topic     ← キーワード固有の通知先
  2. PROJECT の override_sns_topics    ← プロジェクト固有の通知先
  3. GLOBAL の sns_topics              ← デフォルト通知先
```

| ケース | 解決結果 |
|--------|---------|
| project-a の ERROR (severity=critical) | project-a-critical（PROJECT で指定） |
| project-a の OOM (severity=critical) | team-b-alerts（MONITOR で指定） |
| project-b の ERROR (severity=critical) | GLOBAL の critical topic（指定なし → デフォルト） |

### 5.2 通知内容の解決（3段階フォールバック）

```
優先順位（高 → 低）:

  1. MONITOR の notification_template  ← キーワード固有テンプレート
  2. PROJECT の notification_template  ← プロジェクト固有テンプレート
  3. GLOBAL の notification_template   ← デフォルトテンプレート
```

**テンプレート変数**:

| 変数 | 内容 |
|------|------|
| `{project}` | プロジェクト表示名 |
| `{keyword}` | 検出キーワード |
| `{severity}` | 緊急度（CRITICAL / WARNING / INFO） |
| `{count}` | 今回の検出数 |
| `{detected_at}` | 検出時刻（JST） |
| `{log_group}` | ロググループ名 |
| `{stream_name}` | 検出されたストリーム名 |
| `{log_lines}` | 検出ログ（最大 N 行） |
| `{streak}` | 連続検出回数 |

### 5.3 通知頻度

```
                    renotify_min
                    (ALARM 継続時の再通知間隔)
                         │
──────┬──────────────────┼──────────────────────────→ 時間
      │                  │
  初回検出             再通知（ALARM 継続中）
  → 即座に通知！       renotify_min 経過ごとに再通知
```

| パラメータ | スコープ | 説明 |
|-----------|---------|------|
| `renotify_min` | MONITOR → GLOBAL defaults | ALARM 継続時の再通知間隔。`null` = 再通知なし |

**動作例**（renotify_min: 60, notify_on_recover: true）:

```
05:00  ERROR 検出 → 通知 ✅（OK → ALARM）
05:05  ERROR 検出 → 通知しない（SUPPRESS）
05:10  ERROR 検出 → 通知しない（SUPPRESS）
06:00  ERROR 検出 → 再通知 ✅（renotify_min 経過）
07:00  ERROR 検出なし → 復旧通知 ✅（ALARM → OK, RECOVER）
07:05  ERROR 検出 → 通知 ✅（新たなインシデント）
```

### 5.4 緊急度

| 緊急度 | 用途 | 通知先（例） | 再通知間隔（推奨） |
|--------|------|-------------|-------------------|
| `critical` | サービス停止レベル | #alerts-critical | 30分 |
| `warning` | 要注意・調査必要 | #alerts-warning | 60分 |
| `info` | 参考情報 | #alerts-info | null（再通知なし） |

### 5.5 除外リスト（ホワイトリスト）

キーワードに一致しても、**特定パターンを含むログを通知対象外**にする。
除外パターンの指定には**正規表現（Regex）**をサポートし、柔軟なフィルタリングを可能にする。

```
除外判定の順序:

  1. keyword にマッチするログを検出
  2. PROJECT の exclude_patterns に一致 → 除外（全キーワード共通）
  3. MONITOR の exclude_patterns に一致 → 除外（そのキーワードのみ）
  4. どちらにも一致しない → 検出結果として残る
```

**動作例**（keyword: "ERROR"）:

```
  "ERROR: database connection failed"        → ✅ 通知対象
  "ERROR: connection reset by peer"          → ❌ 除外（MONITOR パターン）
  "ERROR during healthcheck handler"         → ❌ 除外（PROJECT パターン）
  "ERROR: out of memory"                     → ✅ 通知対象

  除外後の検出数: 2件（通知・メトリクスはこの数で計算）
```

### 5.6 復旧通知（RECOVER）

ALARM 状態のモニターがエラーを検出しなくなった場合、`ALARM → OK` に遷移する。
`notify_on_recover: true`（GLOBAL defaults）の場合、復旧通知を送信する。

```
検出あり → ALARM 継続（再通知 or 抑制）
検出なし → 復旧通知 ✅（notify_on_recover: true の場合）
         → 状態のみ更新（notify_on_recover: false の場合）
```

## 6. Lambda 処理ロジック

### 6.1 メイン処理フロー

```python
def handler(event, context):
    db = DynamoDBClient("log-monitor")

    # 1. 設定を一括取得 (Pagination 考慮)
    global_config = db.get("GLOBAL", "CONFIG")
    projects = query_all_projects(db)
    states = query_all_states(db)

    # CloudWatch Logsの取り込み遅延（Ingestion Delay）対策として、
    # 検索終了時刻を現在より2分前に設定し、ログの取りこぼしを防ぐ
    search_end = now_jst() - timedelta(minutes=2)

    for project in projects:
        if not project.get("enabled", True):
            continue

        log_group = project.get("override_log_group") or global_config["source_log_group"]
        
        # 検索開始時刻はプロジェクト単位で管理
        search_start = project.get("last_searched_at") or (search_end - timedelta(minutes=5))

        for monitor in project["monitors"]:
            # 2. ログ検索 (boto3 自動リトライ & Pagination 考慮)
            raw_matches = filter_log_events_with_pagination(
                log_group=log_group,
                stream_prefix=project["stream_prefix"],
                keyword=monitor["keyword"],
                start_time=search_start,
                end_time=search_end
            )

            # 3. 除外フィルタリング (正規表現サポート)
            excludes = project.get("exclude_patterns", []) + monitor.get("exclude_patterns", [])
            matches = apply_exclusions_regex(raw_matches, excludes)

            # 4. メトリクス送信（常に実行）
            put_metric_data(
                namespace=global_config["metric_namespace"],
                dimensions={"Project": project["sk"], "Keyword": monitor["keyword"]},
                value=len(matches)
            )

            # 5. 状態遷移 & 通知判定
            state = find_state(states, project["sk"], monitor["keyword"])
            action = evaluate_state(state, matches, monitor, global_config)

            if action in ("NOTIFY", "RENOTIFY", "RECOVER"):
                topic_arn = resolve_sns_topic(monitor, project, global_config)
                template = resolve_template(monitor, project, global_config)
                message = render_message(template, project, monitor, matches, action)
                sns_publish(topic_arn, message)

            # 6. STATE 更新
            update_state(db, project["sk"], monitor["keyword"], matches, action)

        # 7. プロジェクトごとの検索実行タイムスタンプ更新
        # エラー発生時の影響を他プロジェクトに波及させないため、プロジェクト単位で記録する
        db.update("PROJECT", project["sk"], last_searched_at=search_end)
```

### 6.2 フォールバック解決ロジック

```python
def resolve_sns_topic(monitor, project, global_config):
    severity = monitor.get("severity") or global_config["defaults"]["severity"]

    # 1. MONITOR 固有
    if monitor.get("override_sns_topic"):
        return monitor["override_sns_topic"]

    # 2. PROJECT 固有
    project_topics = project.get("override_sns_topics", {})
    if severity in project_topics:
        return project_topics[severity]

    # 3. GLOBAL デフォルト
    return global_config["sns_topics"][severity]


def resolve_template(monitor, project, global_config):
    # 1. MONITOR 固有  →  2. PROJECT 固有  →  3. GLOBAL デフォルト
    return (monitor.get("notification_template")
            or project.get("notification_template")
            or global_config["notification_template"])
```

### 6.3 状態遷移ロジック

```python
def evaluate_state(state, matches, monitor, global_config):
    count = len(matches)
    status = state.get("status", "OK") if state else "OK"
    defaults = global_config["defaults"]
    renotify = monitor.get("renotify_min", defaults["renotify_min"])
    notify_on_recover = defaults.get("notify_on_recover", False)

    if count > 0:
        if status == "OK":
            return "NOTIFY"
        elif status == "ALARM":
            last = state.get("last_notified_at")
            if last and renotify and minutes_since(last) >= renotify:
                return "RENOTIFY"
            return "SUPPRESS"
    else:
        if status == "ALARM":
            return "RECOVER" if notify_on_recover else "RECOVER_SILENT"
        return "NOOP"
```

### 6.4 堅牢性・API制限対策

CloudWatch Logs および DynamoDB の API 制限や挙動に対応するため、以下の対策を実装に組み込む。

1. **APIレート制限対策 (自動リトライ)**: `FilterLogEvents` はスロットリングが発生しやすいため、boto3 の設定で `Standard Retry Mode` を有効化し、適切なエクスポネンシャルバックオフを行う。
2. **ページネーションの処理**: 大量ログヒット時やプロジェクト数増加時に備え、`FilterLogEvents` の `nextToken` および DynamoDB クエリの `LastEvaluatedKey` を処理するループ（ページネーション）を実装する。
3. **取り込み遅延（Ingestion Delay）バッファ**: CloudWatch Logsへの反映遅延によるログの取りこぼしを防ぐため、検索期間の末尾を `現在時刻 - 2分` のようにバッファを持たせる。
4. **タイムアウト時の安全設計**: `last_searched_at` はプロジェクト内の全モニター処理完了後に更新する。Lambda がタイムアウトした場合、未更新のプロジェクトは次回実行時に同じ期間を再検索するが、STATE の仕組み（既に `ALARM` ならば `SUPPRESS`）により重複通知は発生しない。
5. **初回デプロイ時のフォールバック**: `last_searched_at` が未設定の新規プロジェクトは、初回実行時に `search_end - 5分` を自動的に検索開始時刻として使用する。

## 7. CloudWatch メトリクス & ダッシュボード

Lambda が `PutMetricData` で送信：

```
Namespace: LogMonitor
MetricName: KeywordDetectionCount
Dimensions:
  - Project: "project-a"
  - Keyword: "ERROR"
Value: (除外後の検出数)
Period: 300 (5分)
```

## 8. コスト試算

5プロジェクト × 5キーワード = 25モニターの場合：

| 項目 | 月額コスト |
|------|-----------|
| Lambda（5分×月8,640回、512MB、平均30秒） | ~$1.10 |
| DynamoDB（オンデマンド、小規模読み書き） | ~$0（無料枠内） |
| CloudWatch カスタムメトリクス（25個） | ~$4.50 |
| SNS（月数百通知想定） | ~$0（無料枠内） |
| CloudWatch Logs API（FilterLogEvents） | ~$0.01 |
| **合計** | **~$5.61/月** |

## 9. 管理運用

### 新プロジェクト追加 → 1レコード作成するだけ

```json
{
  "pk": "PROJECT",
  "sk": "project-c",
  "display_name": "Project Charlie",
  "stream_prefix": "project-c",
  "enabled": true,
  "monitors": [
    { "keyword": "ERROR", "severity": "critical" },
    { "keyword": "WARN",  "severity": "info" }
  ]
}
```

STATE レコードは Lambda が初回検出時に自動作成。

### キーワード追加 → monitors 配列に要素追加

### プロジェクト固有の通知先 → override_sns_topics を追加

### 一時停止 → `"enabled": false` に変更

## 10. 実装順序

```
1. DynamoDB テーブル作成 & GLOBAL + PROJECT レコード投入
     ↓
2. Lambda の基本構造（設定読み込み・ログ検索・除外フィルタリング）
     ↓
3. 状態遷移ロジック & 通知判定
     ↓
4. SNS 通知送信（フォールバック解決 + テンプレート整形）
     ↓
5. PutMetricData（可視化用メトリクス送信）
     ↓
6. EventBridge スケジュール設定
     ↓
7. CloudWatch ダッシュボード作成
     ↓
8. 結合テスト
```

## 11. 未決定事項

- [ ] デプロイ方法（SAM / Terraform / CDK）
- [ ] 現在のプロジェクト数・キーワード数の具体的な規模
- [x] `FilterLogEvents` vs `Logs Insights` の最終選定 **(軽量・高速・低コストな `FilterLogEvents` を採用)**
- [ ] 既存の cloudwatch-logs-handler プロジェクトをベースにするか新規か
- [ ] DynamoDB の初期データ投入方法（スクリプト / コンソール / IaC）
- [ ] Lambda のランタイムバージョン（Python 3.12 推奨）
