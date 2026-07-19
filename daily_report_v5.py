#!/home/soso/v5/.venv/bin/python3
"""v5 每日数据报告 — 15:15 运行，飞书推送

检查:
  - Sina 日更 (sina_daily_sync.log)
  - IC 更新 (factor_ic_daily 最新覆盖)
  - daily_pick 推送 (daily_pick_v5.log)
  - daily_kline 覆盖 (各日期股票数)
"""
import sys, os, sqlite3
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.expanduser("~"))
from feishu import send_text, MONITOR_CHAT_ID

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
LOG_SINA = os.path.expanduser("~/ading/logs/sina_daily_sync.log")
LOG_PICK = os.path.expanduser("~/ading/logs/daily_pick_v5.log")


def log(msg):
    print(msg, flush=True)


def check_sina():
    """读 Sina 日更日志最后几行"""
    if not os.path.exists(LOG_SINA):
        return "⚠ Sina 日志不存在"
    with open(LOG_SINA) as f:
        lines = f.readlines()
    # 找最近一次运行
    last_run = None
    for line in reversed(lines):
        if "Sina daily sync" in line:
            last_run = line
            break
    if not last_run:
        return "⚠ Sina 未找到运行记录"

    # 找结果
    result = ""
    for line in reversed(lines):
        if "Done:" in line:
            result = line.strip()
            break
        if "ERROR" in line:
            result = line.strip()
            break
    return f"{last_run.strip()[:50]}...\n  → {result}" if result else last_run.strip()[:80]


def check_ic():
    """查 IC 表最新覆盖"""
    db = sqlite3.connect(DB)
    today = date.today().strftime("%Y-%m-%d")
    row = db.execute(
        "SELECT MAX(date), COUNT(*) FROM factor_ic_daily WHERE date >= ?",
        ((date.today() - timedelta(days=7)).strftime("%Y-%m-%d"),)
    ).fetchone()
    db.close()
    if row[0]:
        return f"IC 最新: {row[0]} ({row[1]} rows, 最近7天)"
    return "⚠ IC 表无数据"


def check_kline():
    """查 daily_kline 最近覆盖"""
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT date, COUNT(DISTINCT code) FROM daily_kline "
        "WHERE date >= ? GROUP BY date ORDER BY date DESC LIMIT 5",
        ((date.today() - timedelta(days=10)).strftime("%Y-%m-%d"),)
    ).fetchall()
    db.close()
    if not rows:
        return "⚠ daily_kline 无数据"
    lines = []
    for d, cnt in rows:
        d_clean = d[:10]
        lines.append(f"  {d_clean}: {cnt} stocks")
    return "\n".join(lines)


def check_pick():
    """读 daily_pick 日志"""
    if not os.path.exists(LOG_PICK):
        return "⚠ Pick 日志不存在"
    with open(LOG_PICK) as f:
        lines = f.readlines()
    for line in reversed(lines):
        if "Done:" in line:
            return f"Pick OK ({line.strip()})"
        if "Feishu sent" in line:
            return f"Pick OK ({line.strip()})"
    return "⚠ Pick 未找到完成记录"


def main():
    today_str = date.today().strftime("%Y-%m-%d")

    sina = check_sina()
    ic = check_ic()
    kline = check_kline()
    pick = check_pick()

    report = f"""📊 v5 每日数据报告 — {today_str}

━━ 日更通道 ━━
{sina}

━━ IC 数据库 ━━
{ic}

━━ 日K 覆盖 ━━
{kline}

━━ 选股推送 ━━
{pick}

━━ 定时器 ━━
  14:50 daily-pick-v5  选股推送
  15:05 sina-daily-sync 日K日更
  15:10 build-ic-daily  IC更新
"""

    print(report)

    # 飞书推送
    try:
        send_text(report, chat_id=MONITOR_CHAT_ID)
        log("Feishu sent")
    except Exception as e:
        log(f"Feishu failed: {e}")

    # 存 workspace
    path = os.path.expanduser(f"~/ading/data/reports/DAILY_REPORT_v5_{today_str}.md")
    with open(path, "w") as f:
        f.write(report)


if __name__ == "__main__":
    main()
