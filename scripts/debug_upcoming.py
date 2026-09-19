"""
開催予定レースのレースID一覧と、出馬表の構造を確認するデバッグ用スクリプト。

race.netkeiba.com は2024年11月以降、JavaScriptで動的に描画されるページが
増えたため、Selenium(ブラウザ自動化)を使って取得する。

使い方:
    python debug_upcoming.py <YYYYMMDD>

例:
    python debug_upcoming.py 20260823   # 次の開催日に合わせて指定
"""

import re
import sys
import time

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def get_race_ids(kaisai_date: str) -> list[str]:
    """指定日(YYYYMMDD)に開催予定のレースID一覧を取得する。"""
    url = f"https://race.netkeiba.com/top/race_list.html?kaisai_date={kaisai_date}"
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 30)

    try:
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#RaceTopRace")))
        time.sleep(1)  # 描画の安定を待つ

        soup = BeautifulSoup(driver.page_source, "lxml")
        race_ids = []
        for a_tag in soup.select(".RaceList_DataItem > a:first-of-type"):
            href = a_tag.get("href", "")
            m = re.search(r"race_id=(\d+)", href)
            if m:
                race_ids.append(m.group(1))
        return race_ids
    finally:
        driver.quit()


def show_shutuba(race_id: str) -> None:
    """出馬表ページの構造を確認用に表示する。"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 30)

    try:
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ShutubaTable")))
        time.sleep(1)

        soup = BeautifulSoup(driver.page_source, "lxml")

        # レース情報部分(距離・コース種別・天候予報など)を丸ごと表示

        # ページタイトルを確認(レース名・距離が入っていることが多い)
        print("=== <title>タグ ===")
        print(repr(soup.title.text) if soup.title else "見つかりませんでした")

        # ページ全体のテキストから "距離らしきパターン(◯◯◯m)" を検索
        print("\n=== ページ全体から距離パターン(数字+m)を検索 ===")
        full_text = soup.get_text()
        for m in re.finditer(r".{15}\d{3,4}m.{15}", full_text):
            print(repr(m.group()))

        # 芝・ダート・障害という単語の前後も見る
        print("\n=== 芝/ダート/障害という単語の前後 ===")
        for keyword in ["芝", "ダート", "障害"]:
            for m in re.finditer(f".{{10}}{keyword}.{{10}}", full_text):
                print(repr(m.group()))
                break  # 最初の1件だけ

        # 出馬表テーブルのヘッダーと1行目を表示
        header_tr = soup.select_one(".ShutubaTable > thead > tr:first-of-type")
        if header_tr:
            headers = [th.text.strip().split("\n")[0] for th in header_tr.select("th")]
            print("\n=== 出馬表ヘッダー ===")
            print(list(enumerate(headers)))

        first_row = soup.select_one(".ShutubaTable > tbody > tr")
        if first_row:
            cells = [td.text.strip() for td in first_row.select("td")]
            print("\n=== 1行目のデータ ===")
            for idx, val in enumerate(cells):
                print(f"  {idx}: {val!r}")

        # Item02を直接探す
        item02_all = soup.find_all(class_=re.compile("Item02"))
        print(f"\nItem02を含む要素: {len(item02_all)}件")
        for tag in item02_all:
            print(f"class={tag.get('class')}: {tag.text.strip()!r}")

        # 距離・天候・馬場に関連しそうな語を含む要素をもっと広く探す
        for tag in soup.find_all(["dd", "dl", "span", "p"]):
            text = tag.text.strip()
            if re.search(r"\d{3,4}m|芝|ダート|不良|稍重|天候", text) and len(text) < 100:
                print(f"[{tag.name}] class={tag.get('class')}: {text!r}")
    finally:
        driver.quit()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python debug_upcoming.py <YYYYMMDD>")
        sys.exit(1)

    kaisai_date = sys.argv[1]
    print(f"[info] {kaisai_date} のレースID一覧を取得中...")
    race_ids = get_race_ids(kaisai_date)
    print(f"[info] {len(race_ids)}レース見つかりました: {race_ids[:5]}...")

    if not race_ids:
        print("[error] レースIDが取得できませんでした。日付が正しいか確認してください。")
        sys.exit(1)

    print(f"\n[info] 1レース目({race_ids[0]})の出馬表構造を確認します\n")
    show_shutuba(race_ids[0])
