"""
scrape_upcoming.pyが作ったupcoming_races.jsonと、保存済みモデル(model.txt)を使って
各レースの予測順位を計算し、predictions.jsonとして出力する。

使い方:
    python predict.py
"""

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

import db
import features

UPCOMING_PATH = Path(__file__).resolve().parent.parent / "data" / "upcoming_races.json"
MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "model.txt"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "predictions.json"

# race.netkeiba.com(出馬表)の所属表記 -> db.netkeiba.com(過去データ)の[東]/[西]表記 対応
LOCATION_TO_BRACKET = {"美浦": "東", "栗東": "西"}
PRIOR_COUNT = 20


def _resolve_jockey(abbrev: str, full_names: list[str]):
    """出馬表の略式騎手名(例:'津村')から、過去データのフルネームを一意に特定する。"""
    candidates = [n for n in full_names if isinstance(n, str) and n.startswith(abbrev)]
    return candidates[0] if len(candidates) == 1 else None


def _resolve_trainer(abbrev_with_location: str, full_names: list[str]):
    """出馬表の'美浦鈴木伸'のような表記から、過去データの'[東]鈴木伸...'を一意に特定する。"""
    for loc, bracket in LOCATION_TO_BRACKET.items():
        if abbrev_with_location.startswith(loc):
            name_part = abbrev_with_location[len(loc):]
            candidates = [
                n for n in full_names
                if isinstance(n, str) and n.startswith(f"[{bracket}]") and n[3:].startswith(name_part)
            ]
            return candidates[0] if len(candidates) == 1 else None
    return None


def _bayesian_rate_table(history_df: pd.DataFrame, key_col: str):
    """
    全期間の実績を使って、現時点でのベイズ平均複勝率を計算する。
    (学習時と違い、予測時点は「今」より後の未来を予測するだけなので、
     過去の全データを使っても未来の情報が混ざるリークにはならない)
    """
    overall_mean = history_df["is_top3"].mean()
    stats = history_df.groupby(key_col)["is_top3"].agg(["count", "mean"]).reset_index()
    stats["rate_adj"] = (stats["count"] * stats["mean"] + PRIOR_COUNT * overall_mean) / (
        stats["count"] + PRIOR_COUNT
    )
    return stats.set_index(key_col)["rate_adj"].to_dict(), overall_mean


def _horse_career_snapshot(history_df: pd.DataFrame, horse_name: str, target_date: pd.Timestamp) -> dict:
    """ある馬について、target_dateより前の実績から「現時点のスナップショット」を作る。"""
    past = history_df[
        (history_df["horse_name"] == horse_name) & (history_df["race_date_dt"] < target_date)
    ].sort_values("race_date_dt")

    if past.empty:
        return {
            "prev_finish": np.nan, "rest_days": np.nan, "career_starts": 0,
            "career_top3_rate": np.nan, "avg_finish_last3": np.nan,
        }

    last = past.iloc[-1]
    return {
        "prev_finish": last["finish_position_num"],
        "rest_days": (target_date - last["race_date_dt"]).days,
        "career_starts": len(past),
        "career_top3_rate": past["is_top3"].mean(),
        "avg_finish_last3": past["finish_position_num"].tail(3).mean(),
    }


def load_history() -> pd.DataFrame:
    """keiba.dbから、特徴量計算に使う形に整えた過去実績を読み込む。"""
    con = db.get_connection()
    races_df = pd.read_sql("SELECT * FROM races", con)
    results_df = pd.read_sql("SELECT * FROM results", con)
    con.close()

    df = results_df.merge(races_df, on="race_id", how="left")
    df = df[df["course_type"] != "障害"].copy()
    df = df[~df["finish_position"].isin(features.EXCLUDED_FINISH_POSITIONS)].copy()
    df["finish_position_num"] = pd.to_numeric(df["finish_position"], errors="coerce")
    df["is_top3"] = (df["finish_position_num"] <= 3).astype(int)
    df["race_date_dt"] = pd.to_datetime(df["race_date"], format="%Y%m%d")
    return df


def build_prediction_rows(upcoming: dict, history_df: pd.DataFrame) -> pd.DataFrame:
    jockey_rate, overall_mean_j = _bayesian_rate_table(history_df, "jockey")
    trainer_rate, overall_mean_t = _bayesian_rate_table(history_df, "trainer")
    known_jockeys = history_df["jockey"].dropna().unique().tolist()
    known_trainers = history_df["trainer"].dropna().unique().tolist()

    target_date = pd.to_datetime(upcoming["kaisai_date"], format="%Y%m%d")
    unresolved_jockey = 0
    unresolved_trainer = 0

    rows = []
    for race in upcoming["races"]:
        for horse in race["horses"]:
            weight_kg, weight_diff = features._parse_weight(horse["horse_weight"])
            sex = horse["sex_age"][0]
            age = int(horse["sex_age"][1:])

            resolved_jockey = _resolve_jockey(horse["jockey"], known_jockeys)
            resolved_trainer = _resolve_trainer(horse["trainer"], known_trainers)
            if resolved_jockey is None:
                unresolved_jockey += 1
            if resolved_trainer is None:
                unresolved_trainer += 1

            snapshot = _horse_career_snapshot(history_df, horse["horse_name"], target_date)

            rows.append({
                "race_id": race["race_id"],
                "horse_name": horse["horse_name"],
                "umaban": horse["umaban"],
                "waku": horse["waku"],
                "distance_m": race["distance_m"],
                "course_type": race["course_type"],
                "direction": race["direction"],
                "track_condition": race["track_condition"],
                "weather": race["weather"],
                "race_class": race["race_class"],
                "kinryo": horse["kinryo"],
                "sex": sex,
                "age": age,
                "horse_weight_kg": weight_kg,
                "horse_weight_diff": weight_diff,
                "popularity": horse["popularity"],
                "odds": horse["odds"],
                "jockey_top3_rate_adj": jockey_rate.get(resolved_jockey, overall_mean_j),
                "trainer_top3_rate_adj": trainer_rate.get(resolved_trainer, overall_mean_t),
                **snapshot,
            })

    total = len(rows)
    print(f"[info] 騎手の名寄せ: {total - unresolved_jockey}/{total} 件成功")
    print(f"[info] 調教師の名寄せ: {total - unresolved_trainer}/{total} 件成功")

    return pd.DataFrame(rows)


def main() -> None:
    with open(UPCOMING_PATH, encoding="utf-8") as f:
        upcoming = json.load(f)

    history_df = load_history()
    pred_df = build_prediction_rows(upcoming, history_df)

    for col in features.CATEGORY_COLS:
        pred_df[col] = pred_df[col].astype("category")

    model = lgb.Booster(model_file=str(MODEL_PATH))
    pred_df["predicted_score"] = model.predict(pred_df[features.FEATURE_COLS])

    output_races = []
    for race_id, group in pred_df.groupby("race_id"):
        group_sorted = group.sort_values("predicted_score", ascending=False)
        output_races.append({
            "race_id": race_id,
            "predictions": [
                {
                    "rank": i + 1,
                    "umaban": int(r.umaban),
                    "horse_name": r.horse_name,
                    "predicted_score": float(r.predicted_score),
                    "odds": r.odds,
                    "popularity": int(r.popularity) if pd.notna(r.popularity) else None,
                }
                for i, r in enumerate(group_sorted.itertuples())
            ],
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"races": output_races}, f, ensure_ascii=False, indent=2)

    print(f"[info] {len(output_races)}レース分の予測を {OUTPUT_PATH} に保存しました")


if __name__ == "__main__":
    main()
