"""
特徴量エンジニアリングの共通ロジック。

学習(Colabノートブック)と推論(本番のpredict.py)の両方から
build_features()を呼び出すことで、特徴量の計算方法がズレないようにする。

重要: すべての「実績系」特徴量(騎手/調教師の複勝率、馬の過去成績)は、
「そのレースより前のデータだけ」を使って計算している(未来の結果が
混ざるデータリークを防ぐため)。
"""

import re

import numpy as np
import pandas as pd

FEATURE_COLS = [
    "distance_m", "course_type", "direction", "track_condition", "weather", "race_class",
    "waku", "umaban", "kinryo", "sex", "age", "horse_weight_kg", "horse_weight_diff",
    "popularity", "odds",
    "jockey_top3_rate_adj", "trainer_top3_rate_adj",
    "prev_finish", "rest_days", "career_starts", "career_top3_rate", "avg_finish_last3",
]

CATEGORY_COLS = ["course_type", "direction", "track_condition", "weather", "race_class", "sex"]

EXCLUDED_FINISH_POSITIONS = ["取", "除", "中"]  # 取消・除外・競走中止

PRIOR_COUNT = 20  # ベイズ平均で「仮想的な平均選手」を何回分混ぜ込むか


def _parse_weight(s):
    """'446(-2)' のような文字列を (446, -2) に分解する。パースできなければ(NaN, NaN)。"""
    if pd.isna(s):
        return np.nan, np.nan
    m = re.match(r"(\d+)\(([+-]?\d+)\)", str(s))
    if not m:
        return np.nan, np.nan
    return int(m.group(1)), int(m.group(2))


def _finish_to_relevance(pos):
    """着順をLambdaRank用の関連度スコア(0〜5)に変換する。"""
    if pd.isna(pos):
        return 0
    pos = int(pos)
    if pos == 1:
        return 5
    elif pos == 2:
        return 4
    elif pos == 3:
        return 3
    elif pos <= 5:
        return 2
    else:
        return 1


def _expanding_bayesian_rate(df: pd.DataFrame, key_col: str, target_col: str,
                              prior_count: float, overall_mean: float) -> pd.Series:
    """
    key_col(騎手/調教師など)ごとに、「このレースより前の実績だけ」を使った
    ベイズ平均複勝率を計算する。dfはrace_date_dtで昇順ソート済みである前提。
    """
    g = df.groupby(key_col)[target_col]
    cum_sum = g.transform(lambda s: s.shift(1).expanding().sum())
    cum_count = g.transform(lambda s: s.shift(1).expanding().count())
    return (cum_sum + prior_count * overall_mean) / (cum_count + prior_count)


def build_features(races_df: pd.DataFrame, results_df: pd.DataFrame) -> pd.DataFrame:
    """
    races/resultsテーブルの生データから、モデル学習・推論にそのまま使える
    特徴量テーブルを作る。

    戻り値には FEATURE_COLS に加えて、
    race_id, horse_name, race_date_dt, finish_position_num, is_top3, relevance
    も含まれる。
    """
    df = results_df.merge(races_df, on="race_id", how="left")

    # 障害レースは平地レースと性質が違うため除外
    df = df[df["course_type"] != "障害"].copy()

    # 性齢を分解
    df["sex"] = df["sex_age"].str[0]
    df["age"] = df["sex_age"].str[1:].astype(int)

    # 馬体重を分解
    weight_parsed = df["horse_weight"].apply(_parse_weight)
    df["horse_weight_kg"] = weight_parsed.apply(lambda t: t[0])
    df["horse_weight_diff"] = weight_parsed.apply(lambda t: t[1])

    # 着順を数値化し、関連度スコアを作成
    df["finish_position_num"] = pd.to_numeric(df["finish_position"], errors="coerce")
    df["relevance"] = df["finish_position_num"].apply(_finish_to_relevance)

    # 取消・除外・競走中止は学習対象から外す
    df = df[~df["finish_position"].isin(EXCLUDED_FINISH_POSITIONS)].copy()

    df["is_top3"] = (df["finish_position_num"] <= 3).astype(int)
    df["race_date_dt"] = pd.to_datetime(df["race_date"], format="%Y%m%d")

    overall_mean = df["is_top3"].mean()

    # --- 騎手・調教師の実力(このレースより前の実績のみでベイズ平均) ---
    df = df.sort_values("race_date_dt").reset_index(drop=True)
    df["jockey_top3_rate_adj"] = _expanding_bayesian_rate(
        df, "jockey", "is_top3", PRIOR_COUNT, overall_mean
    )
    df["trainer_top3_rate_adj"] = _expanding_bayesian_rate(
        df, "trainer", "is_top3", PRIOR_COUNT, overall_mean
    )

    # --- 馬自身の過去成績(このレースより前の実績のみ) ---
    df = df.sort_values(["horse_name", "race_date_dt"]).reset_index(drop=True)
    g = df.groupby("horse_name")

    df["prev_finish"] = g["finish_position_num"].shift(1)
    prev_race_date = g["race_date_dt"].shift(1)
    df["rest_days"] = (df["race_date_dt"] - prev_race_date).dt.days
    df["career_starts"] = g.cumcount()
    df["career_top3_rate"] = g["is_top3"].transform(lambda s: s.shift(1).expanding().mean())
    df["avg_finish_last3"] = g["finish_position_num"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean()
    )

    # カテゴリ変数をLightGBM用に変換
    for col in CATEGORY_COLS:
        df[col] = df[col].astype("category")

    keep_cols = (
        ["race_id", "horse_name", "race_date_dt"]
        + FEATURE_COLS
        + ["finish_position_num", "is_top3", "relevance"]
    )
    return df[keep_cols].sort_values(["race_date_dt", "race_id"]).reset_index(drop=True)
