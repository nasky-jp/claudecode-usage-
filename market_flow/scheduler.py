"""Built-in scheduler: Webアプリを起動しておくだけで定型作業が全自動で回る。

信頼性のための設計(cron運用のベストプラクティスを反映):
- キャッチアップ実行: 予定時刻にアプリが落ちていても、起動後 catchup_hours 以内なら実行する
  (systemd timer の Persistent=true 相当)
- ハートビート: 全ジョブの最終実行時刻・結果を状態ファイルに記録し、ダッシュボードに表示
  ("動いているつもりで止まっていた" を毎朝の画面で検知できる)
- 課金ガード: Anthropic APIを使うジョブは ANTHROPIC_API_KEY が無ければスキップとして記録

状態: reports/.scheduler_state.json / ログ: reports/scheduler.log
"""

import contextlib
import io
import json
import os
import threading
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

from market_flow.paths import reports_dir

JST = timezone(timedelta(hours=9))

DEFAULT_CONFIG = {
    "port": 8035,
    "catchup_hours": 4,
    "jobs": {
        "night":     {"enabled": True, "days": [0, 1, 2, 3, 4], "time": "22:00"},
        "morning":   {"enabled": True, "days": [0, 1, 2, 3, 4], "time": "08:00"},
        "scorecard": {"enabled": True, "days": [0, 1, 2, 3, 4], "time": "16:30"},
        "weekly":    {"enabled": True, "days": [5],             "time": "10:00"},
    },
}

JOB_LABELS = {
    "night": "🌙 夜間分析(API課金あり)",
    "morning": "☀️ 朝の確認(API課金あり)",
    "scorecard": "🎯 予測の答え合わせ(課金なし)",
    "weekly": "📝 週次レビュー(API課金あり)",
}

NEEDS_API_KEY = {"night", "morning", "weekly"}

_lock = threading.Lock()


def load_config() -> dict:
    path = os.environ.get("MARKET_FLOW_CONFIG",
                          str(Path(__file__).parent / "config.json"))
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    p = Path(path)
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            config.update({k: v for k, v in user.items() if k != "jobs"})
            for name, job in (user.get("jobs") or {}).items():
                config["jobs"].setdefault(name, {}).update(job)
        except (json.JSONDecodeError, OSError) as e:
            _log(f"config読込失敗({e})。デフォルト設定で続行します")
    return config


def _state_path() -> Path:
    return reports_dir() / ".scheduler_state.json"


def load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _log(message: str) -> None:
    line = f"[{datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(f"(scheduler) {line}")
    try:
        with open(reports_dir() / "scheduler.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _job_func(name: str):
    if name == "night":
        from market_flow.analyze_night import run_night_analysis
        return run_night_analysis
    if name == "morning":
        from market_flow.morning_check import run_morning_check
        return run_morning_check
    if name == "scorecard":
        from market_flow.scorecard import score_pending
        return score_pending
    if name == "weekly":
        from market_flow.weekly_review import run_weekly_review
        return run_weekly_review
    raise ValueError(f"unknown job: {name}")


def run_job(name: str, trigger: str = "scheduled") -> dict:
    """ジョブを実行し、結果を状態ファイルへ記録して返す。"""
    now = datetime.now(JST)
    record = {
        "last_run_date": now.strftime("%Y-%m-%d"),
        "last_run_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "trigger": trigger,
    }

    if name in NEEDS_API_KEY and not os.environ.get("ANTHROPIC_API_KEY"):
        record["status"] = "skipped"
        record["detail"] = "ANTHROPIC_API_KEY未設定のためスキップ"
        _log(f"{name}: skipped (APIキー未設定)")
    else:
        _log(f"{name}: 開始 ({trigger})")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                _job_func(name)()
            record["status"] = "ok"
            record["detail"] = ""
            _log(f"{name}: 完了")
        except Exception as e:
            record["status"] = "error"
            record["detail"] = f"{type(e).__name__}: {e}"
            _log(f"{name}: 失敗 — {record['detail']}\n"
                 + traceback.format_exc(limit=3))
        output = buf.getvalue().strip()
        if output:
            try:
                with open(reports_dir() / "scheduler.log", "a", encoding="utf-8") as f:
                    f.write("  | " + output.replace("\n", "\n  | ") + "\n")
            except OSError:
                pass

    # ジョブ後にダッシュボードを更新(ハートビートを画面に反映)
    if name != "morning":  # morning は自前で更新する
        try:
            from market_flow.dashboard import generate_dashboard
            generate_dashboard()
        except Exception:
            pass

    with _lock:
        state = load_state()
        state[name] = record
        _save_state(state)
    return record


def _is_due(name: str, job_cfg: dict, state: dict, now: datetime,
            catchup_hours: float) -> bool:
    if not job_cfg.get("enabled", True):
        return False
    if now.weekday() not in job_cfg.get("days", []):
        return False
    hh, mm = map(int, job_cfg.get("time", "00:00").split(":"))
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < scheduled:
        return False
    if now > scheduled + timedelta(hours=catchup_hours):
        return False  # キャッチアップ期限切れ(古いデータで走らせない)
    last = state.get(name, {}).get("last_run_date")
    return last != now.strftime("%Y-%m-%d")


def scheduler_loop(stop_event: threading.Event, interval_sec: int = 30) -> None:
    config = load_config()
    _log("スケジューラ起動: "
         + ", ".join(f"{n}={j.get('time')}({'有効' if j.get('enabled', True) else '無効'})"
                     for n, j in config["jobs"].items()))
    while not stop_event.is_set():
        now = datetime.now(JST)
        state = load_state()
        for name, job_cfg in config["jobs"].items():
            try:
                if _is_due(name, job_cfg, state, now, config.get("catchup_hours", 4)):
                    run_job(name, trigger="scheduled")
                    state = load_state()
            except Exception as e:
                _log(f"{name}: スケジューラ内部エラー — {e}")
        stop_event.wait(interval_sec)


def start_scheduler() -> threading.Event:
    """バックグラウンドスレッドでスケジューラを開始。返り値のEventで停止できる。"""
    stop_event = threading.Event()
    thread = threading.Thread(target=scheduler_loop, args=(stop_event,),
                              daemon=True, name="market-flow-scheduler")
    thread.start()
    return stop_event


def status_snapshot() -> list[dict]:
    """ダッシュボード表示用: 各ジョブの設定と最終実行状況。"""
    config = load_config()
    state = load_state()
    rows = []
    for name, job_cfg in config["jobs"].items():
        rec = state.get(name, {})
        days = job_cfg.get("days", [])
        day_str = "平日" if days == [0, 1, 2, 3, 4] else \
            ",".join("月火水木金土日"[d] for d in days)
        rows.append({
            "name": name,
            "label": JOB_LABELS.get(name, name),
            "schedule": f"{day_str} {job_cfg.get('time')}",
            "enabled": job_cfg.get("enabled", True),
            "last_run_at": rec.get("last_run_at", "未実行"),
            "status": rec.get("status", "-"),
            "detail": rec.get("detail", ""),
        })
    return rows
