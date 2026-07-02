"""Shared paths. MARKET_FLOW_REPORTS_DIR で保存先を差し替え可能(テスト用)。"""

import os
from pathlib import Path


def reports_dir() -> Path:
    override = os.environ.get("MARKET_FLOW_REPORTS_DIR")
    d = Path(override) if override else Path(__file__).parent / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d
