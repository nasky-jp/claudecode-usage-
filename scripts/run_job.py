"""GitHub Actions からスケジューラのジョブを1つ実行するエントリポイント。

Usage: python scripts/run_job.py <night|morning|scorecard|weekly>
run_job が APIキー未設定時のスキップ・エラー記録・ハートビート更新まで面倒を見る。
exit code: ok/skipped=0, error=1 (Actionsの成否に反映される)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from market_flow.scheduler import run_job


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    record = run_job(sys.argv[1], trigger="github-actions")
    print(f"result: {record['status']} {record.get('detail', '')}")
    return 0 if record["status"] in ("ok", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
