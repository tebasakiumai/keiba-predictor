"""Gitの履歴から過去の data/predictions.json を取り出し、
data/history/predictions_YYYYMMDD.json として保存する。

- 同じ kaisai_date が複数回コミットされている場合は、最後(最新)のコミットを採用する
- 古い版に含まれる NaN は null に直して保存する(JSONとして正しい形にする)

使い方(リポジトリのルートで実行):
    python scripts\\backfill_history.py
"""
import json
import math
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = "data/predictions.json"
HISTORY_DIR = REPO_ROOT / "data" / "history"


def run_git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return result.stdout


def sanitize(obj):
    """NaN / inf を None に置き換える(再帰)。"""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def main() -> None:
    # 古い順にコミットIDを並べる(--reverse)
    log = run_git("log", "--reverse", "--format=%H", "--", TARGET)
    commits = [line.strip() for line in log.decode().splitlines() if line.strip()]
    print(f"対象コミット数: {len(commits)}")

    # kaisai_date -> (commit, data)。新しいコミットで上書きしていく
    latest_by_date: dict[str, tuple[str, dict]] = {}
    skipped = 0

    for commit in commits:
        try:
            raw = run_git("show", f"{commit}:{TARGET}")
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  skip {commit[:7]}: {e}")
            skipped += 1
            continue

        kaisai_date = data.get("kaisai_date")
        races = data.get("races") or []
        if not kaisai_date or not races:
            print(f"  skip {commit[:7]}: kaisai_date なし or レース0件")
            skipped += 1
            continue

        latest_by_date[kaisai_date] = (commit, sanitize(data))

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    print()
    for kaisai_date in sorted(latest_by_date):
        commit, data = latest_by_date[kaisai_date]
        data["_source_commit"] = commit
        out = HISTORY_DIR / f"predictions_{kaisai_date.replace('-', '')}.json"
        out.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        n_races = len(data["races"])
        print(f"保存: {out.name}  レース数={n_races}  commit={commit[:7]}")

    print()
    print(f"保存した開催日: {len(latest_by_date)} / スキップ: {skipped}")


if __name__ == "__main__":
    main()
