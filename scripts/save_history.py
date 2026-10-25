"""data/predictions.json を data/history/predictions_YYYYMMDD.json にも保存する。

- 同じ開催日(kaisai_date)のファイルがすでにあれば上書きする(最後の予測が残る)
- kaisai_date が無い、またはレースが0件の場合は何も保存しない

使い方(リポジトリのルートで実行。weekly-predict.yml の predict.py の直後に呼ぶ):
    python scripts/save_history.py
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "data" / "predictions.json"
HISTORY_DIR = REPO_ROOT / "data" / "history"


def main() -> None:
    if not SRC.exists():
        print(f"[skip] {SRC} がありません")
        return

    data = json.loads(SRC.read_text(encoding="utf-8"))
    kaisai_date = data.get("kaisai_date")
    n_races = len(data.get("races") or [])

    if not kaisai_date or n_races == 0:
        print("[skip] kaisai_date なし or レース0件のため保存しません")
        return

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    out = HISTORY_DIR / f"predictions_{kaisai_date.replace('-', '')}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 保存: {out.name}  レース数={n_races}")


if __name__ == "__main__":
    main()
