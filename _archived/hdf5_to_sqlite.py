#!/home/soso/v5/.venv/bin/python3
"""Hikyuu HDF5 → SQLite 日更桥脚本

用法:
  python3 hdf5_to_sqlite.py --days 7        # 同步最近7天
  python3 hdf5_to_sqlite.py --dates 2026-07-15,2026-07-16  # 指定日期
  python3 hdf5_to_sqlite.py --since 2026-07-10  # 从某天起

源: Hikyuu HDF5 (不复权, pytdx直连通达信服务器)
目标: tdx_stock_data.db → daily_kline (后复权)
过滤: class='stock' + 排ST + 排bj
"""
import sys, os, sqlite3, h5py, numpy as np, argparse
from datetime import datetime, timedelta

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
HDF5_FILES = {'sh': '/home/soso/stock/sh_day.h5', 'sz': '/home/soso/stock/sz_day.h5'}
PRICE_SCALE = 1000.0  # HDF5 价格编码

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ═══ 取复权因子缓存 ═══
def load_factors(db):
    return {r[0]: r[1] for r in db.execute('SELECT code, hfq_factor FROM adjustment_factor')}

# ═══ 主逻辑 ═══
def sync(dates, db, factors):
    written = 0
    for date_str in dates:
        log(f"  {date_str}...")
        rows = []

        for mkt, h5_path in HDF5_FILES.items():
            if not os.path.exists(h5_path):
                log(f"    {h5_path} not found, skipping")
                continue

            f = h5py.File(h5_path, 'r')
            for code in f['data'].keys():
                # 只取纯股票 (SH600xxx, SZ000xxx 等 8位码)
                if not (code[:2] in ('SH','SZ') and code[2:].isdigit() and len(code)==8):
                    continue

                ds = f[f'data/{code}']
                dates_raw = ds['datetime'][:]
                found = False
                for i, dt in enumerate(dates_raw):
                    dt_str = str(dt)
                    dt_fmt = f'{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}'
                    if dt_fmt != date_str:
                        continue

                    open_p  = float(ds['openPrice'][i])  / PRICE_SCALE
                    high_p  = float(ds['highPrice'][i])  / PRICE_SCALE
                    low_p   = float(ds['lowPrice'][i])   / PRICE_SCALE
                    close_p = float(ds['closePrice'][i]) / PRICE_SCALE
                    amt     = float(ds['transAmount'][i]) if 'transAmount' in ds.dtype.names else 0
                    vol     = float(ds['transCount'][i])  if 'transCount' in ds.dtype.names else 0

                    if close_p <= 0 or open_p <= 0:
                        break

                    # 后复权处理: 不复权 × 复权因子
                    qlib_code = code.lower()  # SH600000 → sh600000
                    factor = factors.get(qlib_code, 1.0)
                    rows.append((
                        qlib_code, dt_fmt + ' 00:00:00',
                        round(open_p  * factor, 4),
                        round(high_p  * factor, 4),
                        round(low_p   * factor, 4),
                        round(close_p * factor, 4),
                        round(vol / factor, 0),    # 成交量反向调整
                        round(amt * factor, 0),    # 成交额同向调整
                    ))
                    found = True
                    break
            f.close()

        if rows:
            # 过滤: JOIN stock_info
            db.executemany('''
                INSERT OR IGNORE INTO daily_kline (code, date, open, high, low, close, volume, amount)
                SELECT ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM stock_info s
                    WHERE s.symbol = ? AND s.class='stock'
                      AND s.name NOT LIKE '%ST%'
                      AND ? NOT LIKE 'bj%'
                )
            ''', [(r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7], r[0], r[0]) for r in rows])
            db.commit()
            inserted = len(rows)
            written += inserted
            log(f"    {inserted} rows")
        else:
            log(f"    0 rows (no new data)")

    return written

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, help='同步最近 N 天')
    parser.add_argument('--dates', type=str, help='指定日期 (逗号分隔)')
    parser.add_argument('--since', type=str, help='从某天起 (含) 到今天')
    args = parser.parse_args()

    db = sqlite3.connect(DB)

    # 确定日期列表
    if args.dates:
        dates = [d.strip() for d in args.dates.split(',')]
    elif args.since:
        since = datetime.strptime(args.since, '%Y-%m-%d')
        today = datetime.now()
        dates = [(since + timedelta(days=i)).strftime('%Y-%m-%d')
                 for i in range((today - since).days + 1)]
    elif args.days:
        dates = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                 for i in range(args.days)]
    else:
        log("Usage: hdf5_to_sqlite.py --days 7 | --dates xxx | --since xxx")
        sys.exit(1)

    log(f"Syncing {len(dates)} dates: {dates[0]} ~ {dates[-1]}")

    factors = load_factors(db)
    log(f"  {len(factors)} adjustment factors loaded")

    n = sync(dates, db, factors)
    log(f"Total: {n} rows written")

    # 验证
    latest = db.execute('SELECT MAX(date) FROM daily_kline').fetchone()[0]
    count = db.execute('SELECT COUNT(*) FROM daily_kline WHERE date=?', (latest,)).fetchone()[0]
    log(f"Latest date: {latest}, {count} stocks")
    db.close()

if __name__ == '__main__':
    main()
