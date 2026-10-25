# keiba-predictor

JRA(中央競馬)のレースを対象に、**レース単位で着順を予測**し、結果をWebサイトに自動公開するプロジェクトです。
データ収集 → 特徴量作成 → 機械学習モデル → 予測 → サイト公開までを、GitHub Actions上で週次自動実行しています。

就職活動用のポートフォリオ、実際に使えるツール、機械学習の学習を兼ねた個人開発です。

> **注意**: 本サイトの予想は機械学習による参考情報であり、的中や利益を保証するものではありません。馬券の購入は自己責任でお願いします。

---

## 目次

1. [特徴](#特徴)
2. [全体構成](#全体構成)
3. [自動化の流れ(週間スケジュール)](#自動化の流れ週間スケジュール)
4. [モデル](#モデル)
5. [特徴量](#特徴量)
6. [データベース構成](#データベース構成)
7. [ディレクトリ構成](#ディレクトリ構成)
8. [セットアップ(ローカル開発)](#セットアップローカル開発)
9. [スクリプトの使い方](#スクリプトの使い方)
10. [GitHub Actions と Secrets](#github-actions-と-secrets)
11. [フロントエンド](#フロントエンド)
12. [スクレイピングについての方針](#スクレイピングについての方針)
13. [現状の評価と限界](#現状の評価と限界)
14. [ロードマップ](#ロードマップ)
15. [トラブルシューティング](#トラブルシューティング)
16. [免責事項](#免責事項)

---

## 特徴

- **レース起点の予測**: 馬単体の着順ではなく、「そのレース内での相対的な強さ」を学習する順位学習(LambdaRank)を採用
- **完全自動運用**: 結果収集・予測・サイト更新まで、手動操作なしで毎週動作
- **リーク対策**: 騎手・調教師の成績や馬の過去成績は、そのレース時点より前のデータだけで計算
- **軽量・低コスト**: サーバー不要。GitHub Actions(スケジュール実行)と GitHub Pages(静的配信)のみで運用
- **データの扱いに配慮**: 収集した生データ(SQLite)は非公開リポジトリで管理し、公開するのは予測結果のJSONのみ

## 全体構成

```
┌────────────────────────────── GitHub Actions ──────────────────────────────┐
│                                                                            │
│  Weekly Race Data Collection (日曜夜)                                       │
│    scrape.py ──▶ keiba.db ──▶ 非公開リポジトリ keiba-predictor-data へ保存     │
│                                                                            │
│  Weekly Prediction (金・土)                                                  │
│    scrape_upcoming.py ──▶ upcoming_races.json(出馬表)                       │
│    predict.py(keiba.db + model.txt)──▶ data/predictions.json ──▶ commit     │
│                                                                            │
│  Deploy (predictions.json 更新時 / frontend 変更時)                          │
│    Vite build ──▶ GitHub Pages                                              │
└────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ブラウザ: React サイト(今週のレース予想を表示)
```

| 役割 | 場所 |
|---|---|
| コード・予測結果JSON・フロントエンド | 公開リポジトリ `keiba-predictor`(本リポジトリ) |
| レース結果の蓄積DB(`keiba.db`) | 非公開リポジトリ `keiba-predictor-data` |
| モデル学習・検証(ノートブック) | Google Colab(Google Drive 上の `keiba-app/`) |

## 自動化の流れ(週間スケジュール)

| ワークフロー | 実行タイミング | 内容 |
|---|---|---|
| `weekly-scrape.yml` (Weekly Race Data Collection) | 毎週日曜 20:00 UTC | 直近8日分のレース結果を収集し、`keiba.db` を更新して非公開リポジトリへ push |
| `weekly-predict.yml` (Weekly Prediction) | 毎週金曜・土曜 12:00 UTC | 出馬表を取得し、予測を生成して `data/predictions.json` をコミット |
| `deploy.yml` | `frontend/**` の変更時、および Weekly Prediction 成功時 | フロントエンドをビルドして GitHub Pages に公開 |

補足:

- 出馬表は木曜夕方(枠順なし)、金曜午前(枠順確定)に公開されるため、金曜・土曜の2回予測を更新します。
- `GITHUB_TOKEN` による push では `push` トリガーのワークフローが起動しないため、`deploy.yml` は `workflow_run` でも起動します。
- 手動実行(`workflow_dispatch`)では `target_date` を指定して任意の開催日の予測を作成できます。

## モデル

| 項目 | 内容 |
|---|---|
| アルゴリズム | LightGBM `lambdarank` |
| 単位 | 1レース = 1グループ(`group` = 出走頭数) |
| 教師ラベル | 着順を関連度に変換(1着=5, 2着=4, 3着=3, 4着=2, 5着以下=1) |
| 制約 | オッズ・人気に単調制約(`monotone_constraints`) |
| 学習ラウンド数 | 60(固定、`data/model.txt` として保存) |
| 検証 | 時系列分割(過去で学習し、未来で検証)。ランダム分割はリークするため不使用 |
| 評価指標 | NDCG@3 / NDCG@5(モデルと比較用ベースラインに同じ `sklearn.metrics.ndcg_score` を使用) |
| ベースライン | オッズ順(人気順)に並べた予想 |

モデルは各馬に**スコア**を出し、レース内でスコアの高い順に予想順位を付けます。スコアはレース内の相対比較用であり、確率ではありません。

学習データは現在、直近約1年分の中央競馬(約3,700レース・約51,000頭分)です。

## 特徴量

| 分類 | 特徴量 |
|---|---|
| レース条件 | `distance_m`, `course_type`(芝/ダート), `direction`, `track_condition`, `weather`, `race_class` |
| 出走情報 | `waku`, `umaban`, `kinryo`(斤量), `sex`, `age` |
| 馬体重 | `horse_weight_kg`, `horse_weight_diff` |
| 市場情報 | `popularity`, `odds` |
| 騎手・調教師 | `jockey_top3_rate_adj`, `trainer_top3_rate_adj`(ベイズ平滑化した複勝率) |
| 馬の過去成績 | `prev_finish`, `rest_days`, `career_starts`, `career_top3_rate`, `avg_finish_last3` |

### リーク対策

- 騎手・調教師の複勝率は、**時系列で累積(expanding window)** して計算し、少数サンプルによる偏りをベイズ平滑化で抑えています。
- 馬ごとの過去成績は `shift(1)` で「そのレースより前」のみを参照します。
- 学習時と推論時で**同じ除外条件**を適用します(取消・除外・中止、オッズなし、障害レースなど)。ここが食い違うと推論時に不自然な結果になるため、実際に起きた不具合の教訓として維持しています。

## データベース構成

SQLite(`keiba.db`)。

**`races`**: `race_id`(PK), `race_date`, `venue`, `race_num`, `race_name`, `race_class`, `course_type`, `distance_m`, `direction`, `weather`, `track_condition`, `scraped_at`

**`results`**: `race_id`, `waku`, `umaban`, `horse_name`, `sex_age`, `kinryo`, `jockey`, `finish_position`, `time_str`, `margin`, `passage`, `agari_3f`, `popularity`, `odds`, `horse_weight`, `trainer`(主キー: `race_id` + `umaban`)

※ `passage`(通過順)・`agari_3f`(上がり3F)は現状のDBでは十分に取得できていないため、特徴量には使っていません。

## ディレクトリ構成

```
keiba-predictor/
├─ .github/workflows/
│   ├─ weekly-scrape.yml     # 結果収集(日曜)
│   ├─ weekly-predict.yml    # 予測生成(金・土)
│   └─ deploy.yml            # GitHub Pages へデプロイ
├─ scripts/
│   ├─ db.py                 # SQLite スキーマ・保存処理
│   ├─ scrape.py             # 過去レース結果の収集(db.netkeiba.com)
│   ├─ scrape_upcoming.py    # 今週の出馬表の収集(Selenium)
│   ├─ features.py           # 特徴量作成
│   └─ predict.py            # 予測生成
├─ data/
│   ├─ model.txt             # 学習済みモデル
│   └─ predictions.json      # 最新の予測結果(サイトが読み込む)
├─ frontend/                 # React + TypeScript + Vite
├─ requirements.txt
└─ README.md
```

`keiba.db`(`data/*.db`)は `.gitignore` により公開リポジトリには含まれません。

## セットアップ(ローカル開発)

前提: Python 3.11 前後、Node.js 20 以上、Google Chrome(出馬表取得に使用)。

```powershell
git clone https://github.com/<ユーザー名>/keiba-predictor.git
cd keiba-predictor

# Python 環境
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# フロントエンド
cd frontend
npm ci
npm run dev
```

`keiba.db` は非公開リポジトリ `keiba-predictor-data` にあります。ローカルで予測まで試す場合は `data/keiba.db` として配置してください。

## スクリプトの使い方

すべて `scripts/` ディレクトリで実行します(PowerShell で `python -c` の引用符が崩れやすいので、ワンライナーではなくスクリプトファイルを使います)。

```powershell
# 過去のレース結果を収集(期間指定)
python scrape.py --start 2026-09-01 --end 2026-09-30

# 指定開催日の出馬表を取得 → data/upcoming_races.json
python scrape_upcoming.py --date 2026-10-25

# 予測を生成 → data/predictions.json
python predict.py
```

### `predictions.json` の形式

```json
{
  "kaisai_date": "2026-10-25",
  "generated_at": "...",
  "races": [
    {
      "race_id": "...", "race_name": "...", "venue": "...", "race_num": 11,
      "post_time": "15:40", "race_class": "...", "course_type": "芝",
      "distance_m": 2000, "direction": "右", "track_condition": "良", "weather": "晴",
      "predictions": [
        { "rank": 1, "umaban": 5, "horse_name": "...", "predicted_score": 1.23, "odds": 3.4, "popularity": 1 }
      ]
    }
  ]
}
```

## GitHub Actions と Secrets

| 設定 | 内容 |
|---|---|
| Secret `DATA_REPO_TOKEN` | 非公開リポジトリ `keiba-predictor-data` へアクセスするための Personal Access Token(PAT) |
| Workflow permissions | **Read and write**(Settings → Actions → General)。未設定だと予測JSONのコミットが 403 / exit code 128 で失敗 |
| GitHub Pages | Source を **GitHub Actions** に設定 |

PAT には有効期限があります(現在90日)。**期限切れで収集・予測が止まるため、カレンダーに更新日を登録して管理してください。**

## フロントエンド

- React + TypeScript + Vite(`base: '/keiba-predictor/'`)
- `predictions.json` を読み込み、レースごとのアコーディオンに予想順位を表示
- 開催日・レース名・コース条件・発走時刻を表示
- ダーク/ライト切り替え対応(ポートフォリオサイトとデザイントークンを共通化)

## スクレイピングについての方針

- 取得対象は netkeiba の公開ページ(過去結果は db.netkeiba.com、出馬表は race.netkeiba.com)です。
- **負荷をかけない**: リクエスト間隔は 1〜2 秒のランダム待機。取得は週次・必要な範囲のみ。
- **自動停止**: 403 / 429 を受けたら即中断。連続失敗が続いた場合も停止します。
- **再配布しない**: 収集した生データは非公開リポジトリに置き、公開するのは自作モデルの予測結果のみです。
- 利用規約は変更される可能性があります。公開・運用にあたっては、対象サイトの最新の規約を各自で確認してください。

## 現状の評価と限界

正直な現状を記載します。

- **モデルの予測精度は、オッズ順(人気順)のベースラインとほぼ同等**です。特徴量のうちオッズ・人気の寄与が支配的で、モデルが独自に上乗せできている価値はまだ実証できていません。
- **的中率の継続的な計測は未実装**です。予測履歴を保存しておらず(`predictions.json` は毎回上書き)、「1番人気を選んだ場合」との比較ができていません。
- **モデルは自動再学習されません**。日曜に結果が `keiba.db` に追加されても、変わるのは特徴量の入力値(騎手成績・馬の過去成績など)のみで、モデルの重みは固定です。
- 騎手名の照合率は約75%です(出馬表とDBの表記ゆれ)。
- `weather` / `track_condition` の特徴量重要度は現状ほぼ0です。
- 学習データが約1年分と短く、血統・調教などの情報は使っていません。

## ロードマップ

- [ ] **予測履歴の保存と的中率の計測**: ◎の単勝率/複勝率、予想上位3頭と実際の上位3頭の一致数を、1番人気ベースラインと並べて評価。サイトにも表示
- [ ] モデルの定期再学習(新旧モデルを比較してから採用)
- [ ] 競馬場ごとのタブ表示、アコーディオンの改善、スマホ対応の強化
- [ ] 騎手名の照合精度の改善
- [ ] 特徴量の追加(血統、コース適性、脚質など)
- [ ] 空レース時の `predict.py` ガード(開催のない日に手動実行しても落ちないように)
- [ ] PAT の期限管理の改善

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| Weekly Prediction が exit code 128 / 403 | Workflow permissions が Read only。**Read and write** に変更 |
| 予測後にサイトが更新されない | `deploy.yml` に `workflow_run` トリガーがあるか確認。Pages の Source が GitHub Actions か確認 |
| `git push` が rejected (fetch first) | Actions がコミットしている。`git pull` してから `git push` |
| `predictions.json` が 404(ローカル開発) | `vite.config.ts` 変更後はdevサーバーを再起動。`frontend` ディレクトリで `npm run dev` を実行 |
| JSON の `NaN` で読み込みエラー | `NaN` は JSON として不正。`None` に変換して出力(実装済み) |
| 開催のない日に手動実行すると失敗 | 対象レースが0件。実際の開催日を `target_date` に指定 |
| PowerShell で `python -c` が動かない | 引用符のネストが崩れる。スクリプトファイルにして実行 |

## 免責事項

- 本プロジェクトは個人の学習・ポートフォリオ目的で、JRAおよび netkeiba とは無関係です。
- 予想結果の正確性は保証されません。本ツールの利用により生じた損害について、作者は責任を負いません。
- 馬券の購入は20歳以上の方が、自己責任で行ってください。
