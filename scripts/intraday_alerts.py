"""盤中價格提醒：交易時段內每 N 分鐘用即時報價檢查「價格規則」，到價就推播。

規則在網頁「預警」頁新增（跌破 / 突破某價格）；推播管道在 config.yaml 的 notify 設定
（discord / telegram / ntfy）。同一條規則觸發後 24 小時內不重複推。

用法：
    python -m scripts.intraday_alerts              # 盤中持續監控，收盤（13:30）後自動結束
    python -m scripts.intraday_alerts --interval 3 # 每 3 分鐘檢查一次（預設 5）
    python -m scripts.intraday_alerts --once       # 只檢查一次（測試用，不管時段）
    python -m scripts.intraday_alerts --once --dry-run  # 只印結果，不推播、不佔冷卻時間
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.alerts import check_alerts  # noqa: E402
from app.config import Config  # noqa: E402
from app.data.clock import taipei_now  # noqa: E402
from app.data.db import Database  # noqa: E402
from app.data.trading_calendar import is_trading_day  # noqa: E402

log = logging.getLogger("intraday_alerts")

MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(13, 35)  # 13:30 收盤撮合，多留 5 分鐘抓最後成交


def in_session(now: datetime, db: Database) -> bool:
    return is_trading_day(now.date(), db) and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def run_once(db: Database, *, push: bool) -> int:
    hits = check_alerts(db, push=push, intraday=True)
    stamp = taipei_now().strftime("%H:%M:%S")
    if hits:
        for h in hits:
            print(f"[{stamp}] 🔔 [{h.stock_id}] {h.stock_name}：{h.message}")
    else:
        print(f"[{stamp}] 檢查完成，沒有規則到價")
    return len(hits)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="盤中價格提醒")
    p.add_argument("--interval", type=float, default=5.0, help="檢查間隔（分鐘），最少 1")
    p.add_argument("--once", action="store_true", help="只檢查一次就結束")
    p.add_argument("--dry-run", action="store_true", help="不推播、不寫入觸發紀錄")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load()
    db = Database(cfg.database.path)
    push = not args.dry_run

    if args.once:
        run_once(db, push=push)
        return 0

    interval_sec = max(1.0, args.interval) * 60
    now = taipei_now()
    if not is_trading_day(now.date(), db):
        print("今天不是交易日，不需要盤中監控。")
        return 0
    print(f"盤中價格提醒啟動：每 {interval_sec / 60:g} 分鐘檢查一次，13:30 收盤後自動結束。")
    while True:
        now = taipei_now()
        if now.time() > MARKET_CLOSE:
            print("已收盤，盤中監控結束。")
            return 0
        if now.time() < MARKET_OPEN:
            wait = (datetime.combine(now.date(), MARKET_OPEN, now.tzinfo) - now).total_seconds()
            print(f"尚未開盤，{int(wait // 60)} 分鐘後開始。")
            time.sleep(min(max(wait, 1), interval_sec))
            continue
        try:
            run_once(db, push=push)
        except Exception as e:  # 單輪失敗（網路等）不中斷整天的監控
            log.warning("本輪檢查失敗：%s", e)
        time.sleep(interval_sec)


if __name__ == "__main__":
    raise SystemExit(main())
