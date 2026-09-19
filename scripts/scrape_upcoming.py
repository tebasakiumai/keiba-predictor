"""
開催予定レースの出馬表(出走馬・オッズ・レース情報)を取得し、
JSONファイルとして出力するスクリプト。

過去結果を集めるscrape.pyとは違い、race.netkeiba.comはJavaScriptで
動的に描画されるため、Seleniumを使う。

使い方:
    python scrape_upcoming.py --date 2026-09-19
"""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "upcoming_races.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

VENUE_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


def get_kaisai_dates(year: int, month: int) -> list[str]:
    """指定した年月の開催日一覧(YYYYMMDD)を取得する(静的ページ、requestsでOK)。"""
    url = f"https://race.netkeiba.com/top/calendar.html?year={year}&month={month}"
    res = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.content, "lxml")

    dates = []
    for a_tag in soup.select(".Calendar_Table .Week > td > a"):
        href = a_tag.get("href", "")
        m = re.search(r"kaisai_date=(\d{8})", href)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def get_race_ids(driver, kaisai_date: str) -> list[str]:
    """指定日(YYYYMMDD)に開催予定のレースID一覧を取得する(動的ページ、Selenium使用)。"""
    url = f"https://race.netkeiba.com/top/race_list.html?kaisai_date={kaisai_date}"
    wait = WebDriverWait(driver, 30)

    driver.get(url)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#RaceTopRace")))
    time.sleep(1)

    soup = BeautifulSoup(driver.page_source, "lxml")
    race_ids = []
    for a_tag in soup.select(".RaceList_DataItem > a:first-of-type"):
        href = a_tag.get("href", "")
        m = re.search(r"race_id=(\d+)", href)
        if m:
            race_ids.append(m.group(1))
    return race_ids


def _parse_race_info(info_text: str, race_id: str) -> dict:
    """RaceList_Item02のテキストからレース情報を抜き出す。"""

    def _find(pattern, default=None):
        m = re.search(pattern, info_text)
        return m.group(1) if m else default

    distance_m = _find(r"(\d+)m")
    course_type = "障害" if "障" in info_text else ("ダート" if "ダ" in info_text else "芝")
    direction = "右" if "右" in info_text else ("左" if "左" in info_text else None)
    # race.netkeiba.comは"馬場:良"の形式(db.netkeiba.comの"芝:良"形式とは異なるので注意)
    track_condition = _find(r"馬場\s*[:：]\s*(\S+)")
    weather = _find(r"天候\s*[:：]\s*(\S+)")
    post_time = _find(r"(\d{1,2}:\d{2})発走")
    race_class = _find(r"(新馬|未勝利|1勝クラス|2勝クラス|3勝クラス|オープン|GIII|GII|GI)")

    venue = VENUE_CODES.get(race_id[4:6]) if len(race_id) == 12 else None
    race_num = int(race_id[10:12]) if len(race_id) == 12 else None

    return {
        "race_id": race_id,
        "venue": venue,
        "race_num": race_num,
        "race_class": race_class,
        "course_type": course_type,
        "distance_m": int(distance_m) if distance_m else None,
        "direction": direction,
        "weather": weather,
        "track_condition": track_condition,
        "post_time": post_time,
    }


def _parse_shutuba_table(soup: BeautifulSoup) -> list[dict]:
    """出馬表テーブルから出走馬情報を抜き出す。"""
    rows = []
    for tr in soup.select(".ShutubaTable > tbody > tr"):
        cells = [td.text.strip() for td in tr.select("td")]
        if len(cells) < 11:
            continue

        def _to_int(s):
            try:
                return int(s)
            except (ValueError, TypeError):
                return None

        def _to_float(s):
            try:
                return float(s)
            except (ValueError, TypeError):
                return None

        rows.append(
            {
                "waku": _to_int(cells[0]),
                "umaban": _to_int(cells[1]),
                "horse_name": cells[3],
                "sex_age": cells[4],
                "kinryo": _to_float(cells[5]),
                "jockey": cells[6],
                "trainer": cells[7],
                "horse_weight": cells[8],
                "odds": _to_float(cells[9]),
                "popularity": _to_int(cells[10]),
            }
        )
    return rows


def get_shutuba(driver, race_id: str):
    """1レース分の出馬表(レース情報+出走馬一覧)を取得する。"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    wait = WebDriverWait(driver, 30)

    driver.get(url)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ShutubaTable")))
    except Exception:
        print(f"  [warn] race_id={race_id} 出馬表が見つかりません(未発表の可能性)")
        return None
    time.sleep(1)

    soup = BeautifulSoup(driver.page_source, "lxml")

    info_tag = soup.select_one(".RaceList_Item02")
    if info_tag is None:
        print(f"  [warn] race_id={race_id} レース情報が見つかりません")
        return None

    race_info = _parse_race_info(info_tag.text, race_id)
    horses = _parse_shutuba_table(soup)

    if not horses:
        print(f"  [warn] race_id={race_id} 出走馬が見つかりません(未確定の可能性)")
        return None

    race_info["horses"] = horses
    return race_info


def main(kaisai_date: str) -> None:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")  # 画面を表示せず裏で実行する
    options.add_argument("--no-sandbox")  # GitHub Actions環境で必要
    options.add_argument("--disable-dev-shm-usage")  # GitHub Actions環境で必要
    driver = webdriver.Chrome(options=options)
    
    try:
        print(f"[info] {kaisai_date} のレースID一覧を取得中...")
        race_ids = get_race_ids(driver, kaisai_date)
        print(f"[info] {len(race_ids)}レース見つかりました")

        races = []
        for race_id in race_ids:
            print(f"[info] race_id={race_id} を取得中...")
            race = get_shutuba(driver, race_id)
            if race:
                races.append(race)
                print(
                    f"  [ok] {race['venue']}{race['race_num']}R "
                    f"{race['race_class']} {race['course_type']}{race['distance_m']}m "
                    f"出走{len(race['horses'])}頭"
                )
    finally:
        driver.quit()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "kaisai_date": kaisai_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "races": races,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[info] 完了。{len(races)}レース分を {OUTPUT_PATH} に保存しました")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="開催予定レースの出馬表を取得")
    parser.add_argument("--date", required=True, help="開催日 YYYY-MM-DD")
    args = parser.parse_args()
    main(args.date.replace("-", ""))
