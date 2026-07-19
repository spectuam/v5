#!/home/soso/v5/.venv/bin/python3
"""Sina 日K日更 — 主通道

交易日 15:05 运行:
  1. 从 TDX stock_info 取有效股票列表 (去ST/北交所)
  2. Sina HTTP API 批量拉全市场不复权日K
  3. × 后复权因子 → 写入 tdx_stock_data.db daily_kline

用法:
  python3 sina_daily_sync.py              # 最近交易日
  python3 sina_daily_sync.py --date 2026-07-17  # 指定日期
"""

import sys, os, time, re, json
import sqlite3
import requests
from datetime import datetime, date, timedelta

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
SINA_BATCH = 100     # 每批股票数
LOG_FILE = os.path.expanduser("~/ading/logs/sina_daily_sync.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── 1. 获取 TDX 有效股票列表 ──
def get_stocks():
    db = sqlite3.connect(DB)
    rows = db.execute("""
        SELECT symbol FROM stock_info
        WHERE class='stock'
        ORDER BY symbol
    """).fetchall()
    db.close()
    return [r[0] for r in rows]  # sh600000 格式


# ── 2. 加载后复权因子 ──
def load_factors():
    db = sqlite3.connect(DB)
    factors = {}
    for code, factor in db.execute("SELECT code, hfq_factor FROM adjustment_factor"):
        factors[code] = factor
    db.close()
    return factors


# ── 3. Sina API 批量拉取 ──
def pull_sina_batch(codes):
    results = []
    n_batches = (len(codes) + SINA_BATCH - 1) // SINA_BATCH
    for bi in range(0, len(codes), SINA_BATCH):
        batch = codes[bi:bi + SINA_BATCH]
        url = "http://hq.sinajs.cn/list=" + ",".join(batch)
        try:
            resp = requests.get(
                url,
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=30
            )
            for raw in resp.text.strip().split("\n"):
                parsed = _parse_sina_line(raw)
                if parsed:
                    results.append(parsed)
        except Exception as e:
            log(f"  Batch error at {bi}: {e}")
        time.sleep(0.1)  # 礼貌间隔
        if (bi // SINA_BATCH + 1) % 10 == 0:
            log(f"  [{bi // SINA_BATCH + 1}/{n_batches}] {len(results)} rows so far")
    return results


def _parse_sina_line(line):
    m = re.search(r'hq_str_(s[hz]\d{6})="(.+?)"', line)
    if not m:
        return None
    code = m.group(1)   # sh600000 (TDX 格式, 不去加点)
    data = m.group(2).split(",")
    if len(data) < 32:
        return None

    try:
        name = data[0]
        open_p  = float(data[1]) if data[1] else None
        close_p = float(data[3]) if data[3] else None
        high_p  = float(data[4]) if data[4] else None
        low_p   = float(data[5]) if data[5] else None
        volume  = float(data[8]) if data[8] else None
        amount  = float(data[9]) if data[9] else None
        trade_date = data[30] + " 00:00:00" if len(data) > 30 else None
    except (ValueError, IndexError):
        return None

    if not trade_date or not open_p or not close_p:
        return None

    return {
        "code": code,
        "name": name,
        "date": trade_date,
        "open": open_p, "high": high_p, "low": low_p,
        "close": close_p, "volume": volume, "amount": amount
    }


# ── 4. 后复权 + 写入 TDX DB ──
def write_to_tdx(rows):
    db = sqlite3.connect(DB)
    factors = load_factors()

    # 统计目标日期
    dates_seen = set(r["date"] for r in rows)
    if len(dates_seen) > 1:
        log(f"  Warning: multiple dates in response: {dates_seen}")

    written, skipped, no_factor = 0, 0, 0
    for r in rows:
        code, d = r["code"], r["date"]

        # 已有完整数据则跳过
        existing = db.execute(
            "SELECT open, close FROM daily_kline WHERE code=? AND date=?",
            (code, d)
        ).fetchone()
        if existing and existing[0] is not None and existing[0] > 0:
            skipped += 1
            continue

        # 后复权
        f = factors.get(code)
        if f is None:
            no_factor += 1
            continue

        adj_open  = r["open"]  * f
        adj_high  = r["high"]  * f
        adj_low   = r["low"]   * f
        adj_close = r["close"] * f
        vol = r["volume"] if r["volume"] else 0
        amt = r["amount"] if r["amount"] else 0

        db.execute("""
            INSERT OR REPLACE INTO daily_kline (code, date, open, high, low, close, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, d, adj_open, adj_high, adj_low, adj_close, vol, amt))
        written += 1

    db.commit()
    db.close()

    log(f"  Written: {written} | Skipped (already): {skipped} | No factor: {no_factor}")
    return written


# ── Main ──
def main():
    target_date = None
    for i, a in enumerate(sys.argv):
        if a == '--date' and i + 1 < len(sys.argv):
            target_date = sys.argv[i + 1]

    log("=" * 50)
    log(f"Sina daily sync — {'date=' + target_date if target_date else 'latest trading day'}")
    log("=" * 50)

    codes = get_stocks()
    log(f"Target stocks: {len(codes)} (TDX stock_info, filtered)")

    t0 = time.time()
    rows = pull_sina_batch(codes)
    elapsed = time.time() - t0
    log(f"Pulled {len(rows)} rows in {elapsed:.1f}s")

    if rows:
        # 按日期筛选
        dates_found = sorted(set(r["date"] for r in rows))
        log(f"Dates in response: {dates_found}")

        if target_date:
            rows = [r for r in rows if r["date"].startswith(target_date)]
            if not rows:
                log(f"ERROR: target date {target_date} not found in response")
                sys.exit(1)
            log(f"Filtered to {target_date}: {len(rows)} rows")

        n = write_to_tdx(rows)
        log(f"Done: {n} rows written to TDX daily_kline")
    else:
        log("ERROR: No data pulled from Sina")
        sys.exit(1)

    log(f"Total time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
