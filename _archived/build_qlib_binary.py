#!/home/soso/v5/.venv/bin/python3
"""直接用 Qlib FileStorage API 构建二进制数据，不需要 dump_bin"""
import sqlite3, os, sys, time, struct
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

DB = os.path.expanduser("~/ading/db/stock_data.db")
QLIB_DATA = os.path.expanduser("~/ading/data/qlib/bin")

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ── 1. 构建目录结构 ──
os.makedirs(os.path.join(QLIB_DATA, "calendars"), exist_ok=True)
os.makedirs(os.path.join(QLIB_DATA, "instruments"), exist_ok=True)
os.makedirs(os.path.join(QLIB_DATA, "features"), exist_ok=True)

# ── 2. 从 daily_kline 读取数据 ──
log("Loading daily_kline...")
t0 = time.time()
db = sqlite3.connect(DB)

df = pd.read_sql("""
    SELECT code, date, open, high, low, close, volume, amount
    FROM daily_kline d
    WHERE date >= '2024-01-01' AND d.close > 0 AND d.open > 0
      AND d.code NOT LIKE 'sz.399%'
      AND d.code NOT IN (SELECT code FROM stock_info WHERE name LIKE '%ST%')
    ORDER BY date, code
""", db)
db.close()
log(f"  {len(df)} rows in {time.time()-t0:.0f}s")

# ── 3. 统一日期索引 ──
df['date'] = pd.to_datetime(df['date'])
dates = sorted(df['date'].unique())
log(f"  {len(dates)} trading days: {dates[0].date()} ~ {dates[-1].date()}")

# 写 calendar 文件
with open(os.path.join(QLIB_DATA, "calendars", "day.txt"), "w") as f:
    for d in dates:
        f.write(d.strftime("%Y-%m-%d") + "\n")
log(f"  Calendar written")

# ── 4. 写 instruments ──
codes = sorted(df['code'].unique())
log(f"  {len(codes)} instruments")

with open(os.path.join(QLIB_DATA, "instruments", "all.txt"), "w") as f:
    for code in codes:
        code_dates = df[df['code'] == code]['date']
        start_d = code_dates.min().strftime("%Y-%m-%d")
        end_d = code_dates.max().strftime("%Y-%m-%d")
        qlib_code = code.replace('.', '').lower()  # sh.600000 → sh600000
        f.write(f"{qlib_code}\t{start_d}\t{end_d}\n")
log(f"  Instruments written")

# ── 5. 按 code 写 feature 二进制文件 ──
FIELDS = ['open', 'high', 'low', 'close', 'volume', 'vwap']
date_to_idx = {d: i for i, d in enumerate(dates)}

# 计算 VWAP = amount / volume
df['vwap'] = df['amount'] / df['volume']
df['vwap'] = df['vwap'].replace([np.inf, -np.inf], np.nan)

log(f"Writing {len(codes)} feature files ({len(FIELDS)} fields each)...")
written = 0
for code in codes:
    qlib_code = code.replace('.', '').lower()
    code_dir = os.path.join(QLIB_DATA, "features", qlib_code)
    os.makedirs(code_dir, exist_ok=True)

    stock_data = df[df['code'] == code].set_index('date')

    for field in FIELDS:
        # 创建长度=交易日的数组，缺失日期填 NaN
        arr = np.full(len(dates), np.nan, dtype=np.float32)
        for d in stock_data.index:
            if d in date_to_idx:
                arr[date_to_idx[d]] = stock_data.loc[d, field]

        file_path = os.path.join(code_dir, f"{field}.day.bin")
        with open(file_path, "wb") as f:
            # Qlib format: [index(float32)] [data(float32 array)]
            np.hstack([0, arr]).astype(np.float32).tofile(f)

    written += 1
    if written % 1000 == 0:
        log(f"  [{written}/{len(codes)}]")

# ── 6. 验证 ──
import struct
test_file = os.path.join(QLIB_DATA, "features", "sh600000", "close.day.bin")
test_arr = np.frombuffer(open(test_file, "rb").read(), dtype=np.float32)
vwap_file = os.path.join(QLIB_DATA, "features", "sh600000", "vwap.day.bin")
vwap_arr = np.frombuffer(open(vwap_file, "rb").read(), dtype=np.float32)
log(f"\nVerification: sh600000")
log(f"  close: {test_arr.shape}, valid: {(~np.isnan(test_arr)).sum()}")
log(f"  vwap: {vwap_arr.shape}, valid: {(~np.isnan(vwap_arr)).sum()}")

# 文件大小
total_size = sum(
    os.path.getsize(os.path.join(dirpath, f))
    for dirpath, _, filenames in os.walk(QLIB_DATA)
    for f in filenames
)
log(f"\nTotal binary size: {total_size/1024/1024:.0f} MB")
log(f"Data directory: {QLIB_DATA}")
log("Done!")
