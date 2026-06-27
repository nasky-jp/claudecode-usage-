"""Setup Claude Code cron jobs for market analysis flow."""

import subprocess
import sys


def setup():
    project_dir = "/home/user/claudecode-usage-"

    night_cmd = f"cd {project_dir} && python3 -m market_flow.analyze_night"
    morning_cmd = f"cd {project_dir} && python3 -m market_flow.morning_check"

    # Night: 22:00 JST = 13:00 UTC
    # Morning: 08:00 JST = 23:00 UTC (previous day → 23:00 UTC)
    crons = [
        {
            "name": "market-night-analysis",
            "schedule": "0 13 * * 1-5",  # 月〜金 22:00 JST
            "command": night_cmd,
            "description": "夜間マーケット分析（NASDAQ/ドル円/日経先物/GOLD → 翌日セクター予測）",
        },
        {
            "name": "market-morning-check",
            "schedule": "0 23 * * 0-4",  # 日〜木 08:00 JST翌朝 (= UTC前日23時)
            "command": morning_cmd,
            "description": "朝の確認作業（前夜予測との比較・本日注目ポイント）",
        },
    ]

    for cron in crons:
        print(f"設定: {cron['name']}")
        print(f"  スケジュール: {cron['schedule']} (UTC)")
        print(f"  内容: {cron['description']}")
        print()

    print("claude cron コマンドでスケジュール登録するには:")
    print()
    for cron in crons:
        print(f"  claude cron add --name '{cron['name']}' \\")
        print(f"    --schedule '{cron['schedule']}' \\")
        print(f"    --command '{cron['command']}'")
        print()

    print("または手動で crontab に追加:")
    print("  crontab -e")
    print()
    print("  # 夜間分析 (月〜金 22:00 JST)")
    print(f"  0 13 * * 1-5 ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY {night_cmd}")
    print()
    print("  # 朝の確認 (月〜土 08:00 JST)")
    print(f"  0 23 * * 0-4 ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY {morning_cmd}")


if __name__ == "__main__":
    setup()
