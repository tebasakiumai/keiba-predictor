# keiba-predictor: データ収集フェーズ

netkeibaからレース結果を収集し、SQLiteに貯めるスクリプトです。
（プロジェクト全体のフェーズ②「データ収集スクリプトの構築」にあたる部分）

## セットアップ

```bash
cd keiba-predictor
python -m venv venv
venv\Scripts\activate        # Windowsの場合(PowerShell)
pip install -r requirements.txt
```

## 使い方(まずは小さく試す)

いきなり大量に取得せず、**まず1週間程度**でテストしてください。

```bash
cd scripts
python scrape.py --start 2024-06-01 --end 2024-06-07
```

- 実行すると `keiba-predictor/data/keiba.db` にSQLiteデータベースが作られます
- 既に取得済みのレースはスキップされるので、同じコマンドを再実行しても安全です
- 途中で止まっても、再実行すれば続きから取得されます

## 動作確認の方法

```bash
python -c "import sqlite3; con = sqlite3.connect('../data/keiba.db'); print(con.execute('SELECT COUNT(*) FROM races').fetchone())"
```

race件数が0のままなら、以下を疑ってください。

1. **netkeiba側のブロック**：ブラウザで https://db.netkeiba.com/race_search_detail/ などにアクセスできるか確認。アクセスできない/表示が変なら制限中の可能性大。しばらく時間を置いてから再実行する。
2. **HTML構造の変化**：`[warn] 結果テーブルが取得できませんでした` と出る場合、netkeiba側のページ構造(クラス名など)が変わっている可能性があります。その場合は該当ページのHTMLを直接確認し、`scrape.py` の `_parse_race_info` / `_parse_results_table` を調整する必要があります。

## 注意点

- リクエスト間隔は2秒に設定しています(サーバー負荷への配慮)。短くしすぎないでください。
- netkeibaは2024年11月頃からスクレイピング対策が強化されたとの報告があり、今後さらに対策が変わる可能性があります。動かなくなった場合は都度対応を検討してください。
- 収集したデータはモデル学習・分析用途にとどめ、サイトの文章や画像をそのまま転載しないでください。

## 次のステップ

データが正常に貯まり始めたら、フェーズ③「特徴量エンジニアリング」に進みます。
