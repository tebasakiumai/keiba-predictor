"""
SQLiteデータベースのスキーマ定義とヘルパー関数。

テーブル構成:
- races   : レース単位の情報(1行=1レース)
- results : 出走馬単位の成績(1行=1頭)
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "keiba.db"


def get_connection() -> sqlite3.Connection:
    """DB接続を返す。dataフォルダが無ければ作成する。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")  # 書き込み中でも読み取りしやすくする
    return conn


def init_db() -> None:
    """テーブルが無ければ作成する(既にあれば何もしない)。"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS races (
            race_id         TEXT PRIMARY KEY,
            race_date       TEXT NOT NULL,
            venue           TEXT,
            race_num        INTEGER,
            race_name       TEXT,
            race_class      TEXT,
            course_type     TEXT,
            distance_m      INTEGER,
            direction       TEXT,
            weather         TEXT,
            track_condition TEXT,
            scraped_at      TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            race_id         TEXT NOT NULL,
            waku            INTEGER,
            umaban          INTEGER,
            horse_name      TEXT,
            sex_age         TEXT,
            kinryo          REAL,
            jockey          TEXT,
            finish_position TEXT,
            time_str        TEXT,
            margin          TEXT,
            popularity      INTEGER,
            odds            REAL,
            horse_weight    TEXT,
            trainer         TEXT,
            PRIMARY KEY (race_id, umaban),
            FOREIGN KEY (race_id) REFERENCES races (race_id)
        )
        """
    )

    conn.commit()
    conn.close()


def race_already_scraped(race_id: str) -> bool:
    """このrace_idが既にDBに保存済みかどうかを返す(再取得を防ぐ)。"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM races WHERE race_id = ?", (race_id,))
    found = cur.fetchone() is not None
    conn.close()
    return found


def save_race(race_row: dict, result_rows: list[dict]) -> None:
    """1レース分のレース情報と出走馬結果をまとめて保存する。"""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR REPLACE INTO races
        (race_id, race_date, venue, race_num, race_name, race_class,
         course_type, distance_m, direction, weather, track_condition, scraped_at)
        VALUES (:race_id, :race_date, :venue, :race_num, :race_name, :race_class,
                :course_type, :distance_m, :direction, :weather, :track_condition, :scraped_at)
        """,
        race_row,
    )

    cur.execute("DELETE FROM results WHERE race_id = ?", (race_row["race_id"],))
    for r in result_rows:
        r["race_id"] = race_row["race_id"]
        cur.execute(
            """
            INSERT OR REPLACE INTO results
            (race_id, waku, umaban, horse_name, sex_age, kinryo, jockey,
             finish_position, time_str, margin, popularity, odds, horse_weight, trainer)
            VALUES (:race_id, :waku, :umaban, :horse_name, :sex_age, :kinryo, :jockey,
                    :finish_position, :time_str, :margin, :popularity, :odds, :horse_weight, :trainer)
            """,
            r,
        )

    conn.commit()
    conn.close()
