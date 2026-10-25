"""予測履歴(data/history/)と確定結果(data/keiba.db)を突き合わせて的中率を計算する。

比較対象(ベースライン): 予測時点のオッズが最小の馬(= 1番人気)を◎にした場合。
モデルとベースラインは「同じレース」だけで比べる。

指標:
  ◎単勝率   予想1位の馬が1着
  ◎複勝率   予想1位の馬が3着以内
  上位3頭一致  予想1〜3位のうち、実際に3着以内に入った頭数の平均(0〜3)
  三連複率   予想1〜3位が実際の1〜3着と完全に一致

使い方(リポジトリのルートで実行):
    python scripts\\evaluate.py
    python scripts\\evaluate.py --out data\\accuracy.json   # JSONも書き出す
"""
import argparse
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "keiba.db"
HISTORY_DIR = REPO_ROOT / "data" / "history"


# ---------------------------------------------------------------- 読み込み
def load_history() -> pd.DataFrame:
    rows = []
    for f in sorted(HISTORY_DIR.glob("predictions_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for race in data["races"]:
            for p in race["predictions"]:
                rows.append(
                    {
                        "kaisai_date": data["kaisai_date"],
                        "race_id": race["race_id"],
                        "venue": race.get("venue"),
                        "race_num": race.get("race_num"),
                        "umaban": int(p["umaban"]),
                        "rank": int(p["rank"]),
                        "odds": p.get("odds"),
                        "popularity": p.get("popularity"),
                    }
                )
    return pd.DataFrame(rows)


def _to_finish(value) -> float:
    """finish_position から先頭の数字を取り出す。取/除/中などは NaN。"""
    if value is None:
        return np.nan
    m = re.match(r"\s*(\d+)", str(value))
    return float(m.group(1)) if m else np.nan


def load_results(race_ids: list[str]) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    frames = []
    for i in range(0, len(race_ids), 500):
        chunk = race_ids[i : i + 500]
        qs = ",".join("?" * len(chunk))
        frames.append(
            pd.read_sql_query(
                f"SELECT race_id, umaban, finish_position FROM results WHERE race_id IN ({qs})",
                conn,
                params=chunk,
            )
        )
    conn.close()
    res = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    res["umaban"] = res["umaban"].astype(int)
    res["finish"] = res["finish_position"].map(_to_finish)
    return res[["race_id", "umaban", "finish"]]


# ---------------------------------------------------------------- 1レースの評価
def eval_race(g: pd.DataFrame) -> dict | None:
    if g["finish"].notna().sum() < 3:
        return None

    by_model = g.sort_values("rank")
    by_fav = g.sort_values(["odds", "popularity"], kind="stable")
    m1, f1 = by_model.iloc[0], by_fav.iloc[0]
    # ◎が取消・除外・中止などで着順なしのレースは、比較から外す
    if pd.isna(m1["finish"]) or pd.isna(f1["finish"]):
        return None

    m3, f3 = by_model.head(3), by_fav.head(3)
    return {
        "kaisai_date": g["kaisai_date"].iloc[0],
        "race_id": g["race_id"].iloc[0],
        "n_runners": len(g),
        "model_win": bool(m1["finish"] == 1),
        "model_place": bool(m1["finish"] <= 3),
        "model_overlap": int((m3["finish"] <= 3).sum()),
        "fav_win": bool(f1["finish"] == 1),
        "fav_place": bool(f1["finish"] <= 3),
        "fav_overlap": int((f3["finish"] <= 3).sum()),
    }


# ---------------------------------------------------------------- 集計
def sign_test_p(b: int, c: int) -> float:
    """b: モデルだけ当たり, c: 1番人気だけ当たり。両側の符号検定(厳密)。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * p)


def summarize(df: pd.DataFrame) -> dict:
    n = len(df)
    paired = {}
    for key in ("win", "place"):
        m, f = df[f"model_{key}"], df[f"fav_{key}"]
        b, c = int((m & ~f).sum()), int((~m & f).sum())
        paired[key] = {"only_model": b, "only_favorite": c, "p_value": sign_test_p(b, c)}
    return {
        "n_races": n,
        "model": {
            "win": float(df["model_win"].mean()),
            "place": float(df["model_place"].mean()),
            "overlap": float(df["model_overlap"].mean()),
            "trio": float((df["model_overlap"] == 3).mean()),
        },
        "favorite": {
            "win": float(df["fav_win"].mean()),
            "place": float(df["fav_place"].mean()),
            "overlap": float(df["fav_overlap"].mean()),
            "trio": float((df["fav_overlap"] == 3).mean()),
        },
        "random": {
            "win": float((1 / df["n_runners"]).mean()),
            "place": float((np.minimum(3, df["n_runners"]) / df["n_runners"]).mean()),
        },
        "paired": paired,
    }


def pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def print_summary(title: str, s: dict) -> None:
    m, f, r, p = s["model"], s["favorite"], s["random"], s["paired"]
    print(f"\n=== {title}  (n={s['n_races']}レース) ===")
    print(f"{'指標':<14}{'モデル':>9}{'1番人気':>9}{'ランダム':>9}")
    print(f"{'◎単勝率':<12}{pct(m['win']):>10}{pct(f['win']):>10}{pct(r['win']):>10}")
    print(f"{'◎複勝率':<12}{pct(m['place']):>10}{pct(f['place']):>10}{pct(r['place']):>10}")
    print(f"{'上位3頭一致':<10}{m['overlap']:>10.2f}{f['overlap']:>10.2f}")
    print(f"{'三連複率':<12}{pct(m['trio']):>10}{pct(f['trio']):>10}")
    print(
        f"  単勝: モデルだけ当たり={p['win']['only_model']} / 1番人気だけ当たり={p['win']['only_favorite']}"
        f"  (符号検定 p={p['win']['p_value']:.2f})"
    )
    print(
        f"  複勝: モデルだけ当たり={p['place']['only_model']} / 1番人気だけ当たり={p['place']['only_favorite']}"
        f"  (符号検定 p={p['place']['p_value']:.2f})"
    )


# ---------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="集計結果を書き出すJSONのパス(省略可)")
    args = parser.parse_args()

    hist = load_history()
    if hist.empty:
        print("data/history/ が空です")
        return

    race_ids = sorted(hist["race_id"].unique())
    res = load_results(race_ids)

    merged = hist.merge(res, on=["race_id", "umaban"], how="left")
    has_result = merged.groupby("race_id")["finish"].transform(lambda s: s.notna().any())
    pending = merged.loc[~has_result, "race_id"].nunique()

    per_race = []
    for _, g in merged[has_result].groupby("race_id"):
        r = eval_race(g)
        if r is not None:
            per_race.append(r)
    df = pd.DataFrame(per_race)

    total = len(race_ids)
    print(f"履歴のレース数: {total}  結果未確定: {pending}  評価対象: {len(df)}  "
          f"(◎が着順なし等で除外: {total - pending - len(df)})")
    if df.empty:
        return

    overall = summarize(df)
    print_summary("全期間", overall)

    print("\n=== 開催日別 ===")
    print(f"{'開催日':<12}{'n':>4}  {'◎単勝 モデル/人気':>20}  {'◎複勝 モデル/人気':>20}  {'上位3頭一致 モデル/人気':>24}")
    by_date = []
    for d, g in df.groupby("kaisai_date"):
        s = summarize(g)
        by_date.append({"kaisai_date": d, **s})
        m, f = s["model"], s["favorite"]
        print(
            f"{d:<12}{s['n_races']:>4}  "
            f"{pct(m['win'])} /{pct(f['win'])}      "
            f"{pct(m['place'])} /{pct(f['place'])}      "
            f"{m['overlap']:>6.2f} /{f['overlap']:>5.2f}"
        )

    print("\n注意: 母数が少ないため、数%の差は偶然でも起こります。符号検定 p が 0.05 を下回らない限り、")
    print("      「モデルが1番人気より良い/悪い」とは言えません。")

    if args.out:
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "date_from": df["kaisai_date"].min(),
            "date_to": df["kaisai_date"].max(),
            "overall": overall,
            "by_date": by_date,
        }
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n書き出し: {args.out}")


if __name__ == "__main__":
    main()
