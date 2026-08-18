"""
netkeibaからレース結果を収集してSQLiteに保存するスクリプト。

使い方:
    python scrape.py --start 2024-01-01 --end 2024-01-07

設計方針(軽量化):
    1. まず開催日カレンダーを取得(月1回のリクエストで済む)
    2. 開催日ごとにその日のレースID一覧を取得
    3. レースIDごとに結果を取得 (既に保存済みのIDはスキップ)
    ※ 存在しないレースIDを総当たりで叩くようなことはしない

注意:
    netkeibaは2024年11月頃からスクレイピング対策が強化されたとの報告があります。
    このスクリプトが途中で異常終了したり、データが全く取れない場合は、
    ブロックされている可能性があるので、実行を止めて時間を置くか、
    User-Agentの見直しなど別の対策を検討してください。
    まずは1週間程度の小さい範囲でテストしてから範囲を広げることを推奨します。
"""

import argparse
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

import db

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_INTERVAL_SEC = 2.0  # サーバー負荷軽減のための最低待機時間
MAX_CONSECUTIVE_FAILURES = 8  # これ以上連続失敗したらブロック疑いとして停止


def _get(url: str) -> requests.Response:
    """待機付きでGETリクエストする共通関数。"""
    time.sleep(REQUEST_INTERVAL_SEC)
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.encoding = "EUC-JP"
    return res


def get_kaisai_dates(year: int, month: int) -> list[str]:
    """指定した年月の開催日一覧(YYYYMMDD)を取得する。"""
    url = f"https://race.netkeiba.com/top/calendar.html?year={year}&month={month}"
    res = _get(url)
    soup = BeautifulSoup(res.content, "lxml")

    dates = []
    for a_tag in soup.select(".Calendar_Table .Week > td > a"):
        href = a_tag.get("href", "")
        m = re.search(r"kaisai_date=(\d{8})", href)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def get_race_ids_for_date(date_str: str) -> list[str]:
    """指定日(YYYYMMDD)に開催された全レースのrace_idを取得する。"""
    url = f"https://db.netkeiba.com/race/list/{date_str}"
    res = _get(url)
    soup = BeautifulSoup(res.text, "html.parser")

    race_list = soup.find("div", attrs={"class": "race_list fc"})
    if race_list is None:
        return []

    race_ids = set()
    for a_tag in race_list.find_all("a"):
        href = a_tag.get("href", "")
        for race_id in re.findall(r"[0-9]{12}", href):
            race_ids.add(race_id)
    return sorted(race_ids)


def _parse_race_info(soup: BeautifulSoup, race_id: str) -> dict:
    """レースの基本情報(距離・馬場状態など)を抜き出す。"""
    race_name_tag = soup.find("dl", attrs={"class": "racedata fc"})
    race_name = race_name_tag.find("h1").text.strip() if race_name_tag else ""

    intro = soup.find("div", attrs={"class": "data_intro"})
    info_text = intro.text if intro else ""

    def _find(pattern, default=None):
        m = re.search(pattern, info_text)
        return m.group(1) if m else default

    distance_m = _find(r"(\d+)m")
    course_type = "障害" if "障" in info_text else ("ダート" if "ダ" in info_text else "芝")
    direction = "右" if "右" in info_text else ("左" if "左" in info_text else None)
    track_condition = _find(r"馬場[:：]\s*(\S)")
    weather = _find(r"天候[:：]\s*(\S+)")
    race_class = _find(r"(新馬|未勝利|1勝クラス|2勝クラス|3勝クラス|オープン|G1|G2|G3|Ｇ1|Ｇ2|Ｇ3)")

    venue = None
    race_num = None
    m = re.search(r"(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$", race_id) if False else None
    # race_id構造: [年4桁][場2桁][回2桁][日2桁][R2桁]
    venue_codes = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
        "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
    }
    if len(race_id) == 12:
        venue = venue_codes.get(race_id[4:6])
        race_num = int(race_id[10:12])

    return {
        "race_id": race_id,
        "race_date": None,  # 呼び出し側でkaisai_dateをセットする
        "venue": venue,
        "race_num": race_num,
        "race_name": race_name,
        "race_class": race_class,
        "course_type": course_type,
        "distance_m": int(distance_m) if distance_m else None,
        "direction": direction,
        "weather": weather,
        "track_condition": track_condition,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
    }


def _parse_results_table(soup: BeautifulSoup) -> list[dict]:
    """出走馬ごとの成績テーブルをパースする。"""
    table = soup.find("table", attrs={"class": re.compile("RaceTable01|race_table")})
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr")[1:]:  # 1行目はヘッダなのでスキップ
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 10:
            continue

        # 列の並びはnetkeibaの標準的な着順テーブルを想定(変更されている場合は要調整)
        def _to_float(s):
            try:
                return float(s)
            except (ValueError, TypeError):
                return None

        def _to_int(s):
            try:
                return int(s)
            except (ValueError, TypeError):
                return None

        rows.append(
            {
                "finish_position": cells[0] if len(cells) > 0 else None,
                "waku": _to_int(cells[1]) if len(cells) > 1 else None,
                "umaban": _to_int(cells[2]) if len(cells) > 2 else None,
                "horse_name": cells[3] if len(cells) > 3 else None,
                "sex_age": cells[4] if len(cells) > 4 else None,
                "kinryo": _to_float(cells[5]) if len(cells) > 5 else None,
                "jockey": cells[6] if len(cells) > 6 else None,
                "time_str": cells[7] if len(cells) > 7 else None,
                "margin": cells[8] if len(cells) > 8 else None,
                "odds": _to_float(cells[16]) if len(cells) > 16 else None,
                "popularity": _to_int(cells[17]) if len(cells) > 17 else None,
                "horse_weight": cells[18] if len(cells) > 18 else None,
                "trainer": cells[22] if len(cells) > 22 else None,
            }
        )
    return rows


def scrape_race(race_id: str, kaisai_date: str) -> bool:
    """1レース分を取得してDBに保存する。成功したらTrueを返す。"""
    url = f"https://db.netkeiba.com/race/{race_id}/"
    res = _get(url)
    if res.status_code != 200:
        print(f"  [warn] race_id={race_id} status={res.status_code}")
        return False

    soup = BeautifulSoup(res.text, "html.parser")
    race_row = _parse_race_info(soup, race_id)
    race_row["race_date"] = kaisai_date
    result_rows = _parse_results_table(soup)

    if not result_rows:
        print(f"  [warn] race_id={race_id} 結果テーブルが取得できませんでした（ページ構造が変わった可能性）")
        return False

    db.save_race(race_row, result_rows)
    return True


def main(start_date: str, end_date: str) -> None:
    db.init_db()

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # 対象期間にまたがる年月を重複なく列挙し、開催日を取得
    months = set()
    cur = start.replace(day=1)
    while cur <= end:
        months.add((cur.year, cur.month))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

    kaisai_dates = []
    for year, month in sorted(months):
        print(f"[info] {year}年{month}月の開催日を取得中...")
        dates = get_kaisai_dates(year, month)
        kaisai_dates.extend(d for d in dates if start_date.replace("-", "") <= d <= end_date.replace("-", ""))

    print(f"[info] 対象開催日: {len(kaisai_dates)}日")

    total_scraped = 0
    consecutive_failures = 0

    for date_str in kaisai_dates:
        print(f"[info] {date_str} のレースID一覧を取得中...")
        race_ids = get_race_ids_for_date(date_str)
        print(f"  -> {len(race_ids)}レース見つかりました")

        for race_id in race_ids:
            if db.race_already_scraped(race_id):
                continue

            ok = scrape_race(race_id, date_str)
            if ok:
                total_scraped += 1
                consecutive_failures = 0
                print(f"  [ok] race_id={race_id} 保存完了 (累計{total_scraped}件)")
            else:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(
                        "[error] 連続で取得失敗が続いています。"
                        "netkeiba側にブロックされている可能性があるため処理を中断します。"
                    )
                    return

    print(f"[info] 完了。合計{total_scraped}レースを新規保存しました。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="netkeibaレースデータ収集")
    parser.add_argument("--start", required=True, help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="終了日 YYYY-MM-DD")
    args = parser.parse_args()
    main(args.start, args.end)
