#!/home/soso/v5/.venv/bin/python3
"""找翻倍股: 锚定 t, 前 20 日均价 X, 后 20 日最高价 >= 2X (涨100%+)
扫描全历史, 输出翻倍股列表 + 数量 + 年份/行业分布。
按股票流式, 内存低。
"""
import sys, os, sqlite3, time
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
LOOKBACK = 20
FORWARD = 20
OUT_TABLE = 'doublers'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def find_one(df):
    """df: 单只 date/code/close/high, 返回 [(code, date)] 翻倍锚定点"""
    n = len(df)
    if n < LOOKBACK + FORWARD:
        return []
    close = df['close'].values
    high = df['high'].values
    dates = df['date'].values
    code = df['code'].iloc[0]
    out = []
    for i in range(LOOKBACK, n - FORWARD):
        X = np.mean(close[i - LOOKBACK:i])  # 前20日均价
        if X <= 0:
            continue
        future_max = np.max(high[i + 1:i + 1 + FORWARD])  # 后20日最高
        if future_max >= 2 * X:
            out.append((code, str(dates[i])[:10]))
    return out


def main():
    log("=" * 60)
    log(f"找翻倍股: 前{LOOKBACK}日均价X, 后{FORWARD}日 high>=2X")
    log("=" * 60)
    db = sqlite3.connect(DB)
    db.execute(f"CREATE TABLE IF NOT EXISTS {OUT_TABLE} (code TEXT, date TEXT, PRIMARY KEY(code,date))")
    db.commit()
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' "
        "AND s.symbol NOT LIKE 'bj%' ORDER BY s.symbol").fetchall()]
    log(f"{len(codes)} stocks")

    t0 = time.time()
    n = 0
    for i, code in enumerate(codes):
        df = pd.read_sql(
            "SELECT date,code,close,high FROM daily_kline WHERE code=? AND close>0 ORDER BY date",
            db, params=(code,))
        if len(df) < LOOKBACK + FORWARD:
            continue
        rows = find_one(df)
        if rows:
            db.executemany(f"INSERT OR REPLACE INTO {OUT_TABLE} VALUES (?,?)", rows)
            n += len(rows)
        if (i + 1) % 500 == 0:
            db.commit()
            log(f"  {i+1}/{len(codes)} doublers={n} [{time.time()-t0:.0f}s]")
    db.commit()
    log(f"done: {n} doublers [{time.time()-t0:.0f}s]")

    log("=" * 60)
    log("年份分布:")
    for y, c in db.execute(f"SELECT substr(date,1,4) y, COUNT(*) FROM {OUT_TABLE} GROUP BY y ORDER BY y").fetchall():
        log(f"  {y}: {c}")
    log("行业分布 (top10):")
    for sw2, c in db.execute(
        f"SELECT s.sw2_code, COUNT(*) FROM {OUT_TABLE} d JOIN stock_sw2 s ON d.code=s.code "
        f"GROUP BY s.sw2_code ORDER BY COUNT(*) DESC LIMIT 10").fetchall():
        log(f"  {sw2}: {c}")
    db.close()


if __name__ == '__main__':
    main()
