"""
1レース分のHTMLを取得し、結果テーブルの各セルを
「何番目に何が入っているか」がわかる形で表示するデバッグ用スクリプト。

使い方:
    python debug_table.py <race_id>

race_idが分からない場合は、DBから1件拾って自動で使います。
"""

import sys

import requests
from bs4 import BeautifulSoup

import db

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def get_sample_race_id() -> str:
    conn = db.get_connection()
    row = conn.execute("SELECT race_id FROM races LIMIT 1").fetchone()
    conn.close()
    if row is None:
        raise SystemExit("DBにレースがありません。race_idを引数で指定してください。")
    return row[0]


def main(race_id: str) -> None:
    url = f"https://db.netkeiba.com/race/{race_id}/"
    print(f"[info] 取得URL: {url}")

    res = requests.get(url, headers=HEADERS, timeout=15)
    res.encoding = "EUC-JP"
    soup = BeautifulSoup(res.text, "html.parser")

    # ページ内にある table タグを全部列挙して、class名と列数を見る
    tables = soup.find_all("table")
    print(f"[info] ページ内のtable数: {len(tables)}")
    for i, t in enumerate(tables):
        cls = t.get("class")
        first_data_row = None
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if tds:
                first_data_row = tds
                break
        ncols = len(first_data_row) if first_data_row else 0
        print(f"  table[{i}] class={cls} data列数={ncols}")

    # 一番列数が多いtableを「結果テーブル」の候補として詳しく見る
    best_table = None
    best_cols = 0
    for t in tables:
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) > best_cols:
                best_cols = len(tds)
                best_table = t

    if best_table is None:
        print("[error] td を含むtableが見つかりませんでした")
        return

    print(f"\n[info] 最も列数が多いtable(class={best_table.get('class')})の中身を表示します")

    # ヘッダ行らしきものを表示(th)
    header_row = best_table.find("tr")
    if header_row:
        headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        print("[header]", list(enumerate(headers)))

    # 2行目(1件目のデータ行)を番号付きで表示
    data_rows = best_table.find_all("tr")[1:]
    if data_rows:
        cells = [td.get_text(strip=True) for td in data_rows[0].find_all("td")]
        print("[row0] 各セルの中身(番号: 内容)")
        for idx, val in enumerate(cells):
            print(f"  {idx}: {val!r}")


if __name__ == "__main__":
    race_id = sys.argv[1] if len(sys.argv) > 1 else get_sample_race_id()
    main(race_id)
