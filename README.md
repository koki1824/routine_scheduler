# 個人用スケジュール自動最適化アプリ

Google Calendar APIを使い、Googleカレンダー、Bar Lemonadeカレンダー、手動入力、祝日、睡眠、移動、準備時間、ルーティンを統合して、破綻しにくい予定を自動生成します。

## ファイル構成

```text
routine_scheduler/
├─ main.py
├─ app.py
├─ routines.json
├─ manual_blocks.json
├─ config.json
├─ requirements.txt
├─ README.md
└─ .gitignore
```

## Google Calendar API設定

1. Google Cloud Consoleでプロジェクトを作成します。
2. Google Calendar APIを有効化します。
3. OAuth同意画面を設定します。
4. OAuthクライアントIDを作成します。種類は「デスクトップアプリ」です。
5. JSONをダウンロードし、`routine_scheduler/credentials.json` として保存します。
6. `config.json` の `calendars.output` と `calendars.bar_lemonade` を自分のカレンダーIDに変更します。

`output` は最終出力先です。通常は `"primary"` で動きます。Bar LemonadeカレンダーはGoogleカレンダー設定画面の「カレンダーID」を入れてください。

## インストール

```bash
cd routine_scheduler
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 手動入力UI

```bash
streamlit run app.py
```

入力できる項目:

- 日付
- 開始時間
- 時間
- 場所
- 内容
- タイトル
- 外出準備の有無

保存先は `manual_blocks.json` です。

## Bar Lemonade予定の選択

Streamlit UIの `Bar予定選択` タブで、Bar Lemonadeカレンダーの任意予定を自分のスケジュールに反映するか選べます。

自動で反映される予定:

- `須藤滉生` を含む予定
- `事業進捗ミーティング定例`
- `レモネード週次ミーティング`
- `経営会議`

それ以外のBar Lemonade予定は、初期状態では参照のみです。必要な予定だけチェックして保存すると、`bar_event_selections.json` に保存され、次回 `main.py` 実行時に自分のカレンダーへ同期されます。

## Google Sheets保存に切り替える場合

`config.json` の `storage.backend` を `google_sheets` にし、`spreadsheet_id` にGoogle SheetsのIDを入れます。

```json
"storage": {
  "backend": "google_sheets",
  "spreadsheet_id": "your-spreadsheet-id",
  "manual_sheet": "manual_blocks",
  "selection_sheet": "bar_event_selections"
}
```

スプレッドシートには `manual_blocks` と `bar_event_selections` という2つのシートを作り、どちらも `A1` を空のままにしておけば、初回保存時にJSONが書き込まれます。

Sheets APIのスコープを追加した後は、古い `token.json` を削除して再認証してください。

## 自動生成の実行

```bash
python main.py --days 14
```

試しにGoogleカレンダーへ書き込まず確認する場合:

```bash
python main.py --days 14 --dry-run
```

開始日を指定する場合:

```bash
python main.py --start 2026-05-10 --days 14
```

## 再実行ルール

再実行時に削除するのはAUTO系タグの予定だけです。

- `[AUTO_INTERN]`
- `[AUTO_TRAVEL]`
- `[AUTO_PREP]`
- `[AUTO_SLEEP]`
- `[AUTO_SLEEP_EXTRA]`
- `[AUTO_ROUTINE]`
- `[AUTO_REST]`
- `[SYNC_BAR_LEMONADE]`

手動予定や通常のGoogleカレンダー予定は削除しません。

## 実装済みルール

- Google Calendar OAuth
- FreeBusy APIで空き時間取得
- Events APIで予定取得、追加、AUTO系削除
- Asia/Tokyo固定
- 26:00のような深夜時刻対応
- Bar Lemonadeカレンダー同期
- インターン週3回配置
- 祝日のインターン禁止
- 外出前の準備1時間
- 移動時間
- 終了が深夜の場合の5:00帰宅
- 最低3時間、基本6時間、週42時間目標の睡眠
- 飲み会翌日午前NG
- 4時間連続後の30分休憩
- ターミナルに追加、スキップ、警告、睡眠合計を表示

## 注意

祝日は `config.json` の `holidays` に `YYYY-MM-DD` 形式で入れてください。必要なら `holidays.json` を作成して同じ形式の配列でも管理できます。

この実装は「毎朝実行できる実用的な初期版」です。予定最適化は安全側に倒しており、空き時間に入らない場合はスキップと警告を出します。
