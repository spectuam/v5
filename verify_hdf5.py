#!/home/soso/v5/.venv/bin/python3
"""验证 Hikyuu HDF5 → 清洗 → 后复权 → SQLite, 对比 TDX 数据库"""
import sys, os
sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import sqlite3, h5py, hikyuu.interactive as hk
import numpy as np
from datetime import datetime

TEST_DB = '/home/soso/v5/hdf5_test.db'
TDX_DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
TARGET_DATES = ['2026-07-13', '2026-07-14', '2026-07-15']

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ═══ 1. 从 HDF5 导出 3 天数据 → 测试 SQLite ═══
log("Step 1: Exporting HDF5 → test DB...")

# 建SQLite
tdb = sqlite3.connect(TEST_DB)
tdb.execute('DROP TABLE IF EXISTS daily_kline')
tdb.execute('''CREATE TABLE daily_kline (
    code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL
)''')
tdb.commit()

# 深证、上证 HDF5 分别处理
hdf5_files = [
    ('sh', '/home/soso/stock/sh_day.h5'),
    ('sz', '/home/soso/stock/sz_day.h5'),
]

# 先拉 后复权因子 (从 TDX SQLite — 最可靠)
tdx_db = sqlite3.connect(TDX_DB)

total_rows = 0
for mkt, fn in hdf5_files:
    f = h5py.File(fn, 'r')
    codes = list(f['data'].keys())

    for code in codes:
        # 过滤: 只取纯股票代码 (SH600xxx, SZ000xxx 等)
        if not (code[:2] in ('SH','SZ') and code[2:].isdigit() and len(code)==8):
            continue

        ds = f[f'data/{code}']
        dates_raw = ds['datetime'][:]
        close_raw = ds['closePrice'][:]

        # 找目标日期对应的数据
        for i, dt in enumerate(dates_raw):
            date_str = str(dt)[:8]  # 20260713
            date_formatted = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
            if date_formatted not in TARGET_DATES:
                continue

            # TDX 原始数据: 价格 / 1000 = 元 (pytdx encoding)
            price_factor = 1000.0
            open_p  = float(ds['openPrice'][i])  / price_factor
            high_p  = float(ds['highPrice'][i])  / price_factor
            low_p   = float(ds['lowPrice'][i])   / price_factor
            close_p = float(close_raw[i])        / price_factor
            vol_p   = float(ds['transCount'][i]) if 'transCount' in ds.dtype.names else 0

            if close_p <= 0 or open_p <= 0:
                continue

            # 代码格式: SH600000 → sh600000
            qlib_code = code.lower()

            tdb.execute('INSERT OR IGNORE INTO daily_kline VALUES (?,?,?,?,?,?,?,?)',
                       (qlib_code, date_formatted, open_p, high_p, low_p, close_p, vol_p, 0))
            total_rows += 1

    f.close()

tdb.commit()
log(f"  HDF5 exported: {total_rows} rows")

# ═══ 2. 统计 ═══
for dt in TARGET_DATES:
    n = tdb.execute('SELECT COUNT(*) FROM daily_kline WHERE date=?', (dt,)).fetchone()[0]
    log(f"  HDF5 {dt}: {n} stocks")

# ═══ 3. 对比 TDX SQLite ═══
log("\nStep 2: Comparing HDF5 vs TDX SQLite...")

# 统一代码格式: hdf5用了sh600000 (小写无点), tdx用了sh.600000 (带点)
for dt in TARGET_DATES:
    # HDF5侧 (已经是 sh600000 原生格式, 不需要加 dot)
    hdf5_data = {}
    for r in tdb.execute('SELECT code, close FROM daily_kline WHERE date=?', (dt,)):
        hdf5_data[r[0]] = r[1]

    # TDX侧
    tdx_data = {}
    for r in tdx_db.execute('''SELECT d.code, d.close FROM daily_kline d
        JOIN stock_info s ON d.code = s.symbol
        WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND d.code NOT LIKE 'bj%'
        AND d.date=?''', (dt + ' 00:00:00',)):
        tdx_data[r[0]] = r[1]

    common = set(hdf5_data.keys()) & set(tdx_data.keys())
    if not common:
        log(f"  {dt}: NO common stocks!")
        continue

    diffs = []
    for c in common:
        h = hdf5_data[c]; t = tdx_data[c]
        if h > 0 and t > 0:
            diffs.append(abs(h - t) / t * 100)

    diffs = np.array(diffs)
    log(f"  {dt}: {len(common)} common stocks")
    log(f"    Mean diff: {diffs.mean():.4f}%  Median: {np.median(diffs):.4f}%")
    log(f"    Diff < 0.1%: {(diffs<0.1).mean()*100:.0f}%  |  < 1%: {(diffs<1).mean()*100:.0f}%")
    log(f"    HDF5 only: {len(set(hdf5_data)-set(tdx_data))}  |  TDX only: {len(set(tdx_data)-set(hdf5_data))}")

tdb.close()
tdx_db.close()
log(f"\nDone! Test DB at {TEST_DB}")
