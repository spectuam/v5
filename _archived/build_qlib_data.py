#!/home/soso/v5/.venv/bin/python3
"""daily_kline → Qlib 二进制数据格式"""
import sqlite3, os, sys, time, glob
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

DB = os.path.expanduser("~/ading/db/stock_data.db")
QLIB_DATA = os.path.expanduser("~/ading/data/qlib")
CSV_DIR = os.path.join(QLIB_DATA, "csv")
BIN_DIR = os.path.join(QLIB_DATA, "bin")

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ── 判断是否执行全流程 ──
DO_DUMP = "--dump" in sys.argv

# ── 1. 从 daily_kline 导出 CSV ──
log("Exporting daily_kline → CSV...")
t0 = time.time()

db = sqlite3.connect(DB)
codes = [r[0] for r in db.execute("""
    SELECT DISTINCT code FROM daily_kline
    WHERE date >= '2024-01-01' AND close > 0 AND open > 0
    AND code NOT LIKE 'sz.399%'
    AND code NOT IN (SELECT code FROM stock_info WHERE name LIKE '%ST%')
    ORDER BY code
""").fetchall()]
log(f"  {len(codes)} stocks")

os.makedirs(CSV_DIR, exist_ok=True)

exported = 0
skipped = 0

for code in codes:
    out_path = os.path.join(CSV_DIR, f"{code.replace('.','').upper()}.csv")

    # 增量：已有且今天的跳过
    if os.path.exists(out_path):
        skipped += 1
        continue

    df = pd.read_sql("""
        SELECT date, open, high, low, close, volume
        FROM daily_kline
        WHERE code = ? AND date >= '2024-01-01' AND close > 0 AND open > 0
        ORDER BY date
    """, db, params=(code,))

    if df.empty:
        continue

    # Qlib 要求列名小写
    df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
    df.to_csv(out_path, index=False)
    exported += 1

    if exported % 1000 == 0:
        now = time.time()
        log(f"  [{exported}/{len(codes)}] {now-t0:.0f}s")

db.close()
log(f"  Exported {exported} new, {skipped} existing ({time.time()-t0:.0f}s)")

# ── 2. 验证 CSV 格式 ──
log("Verifying CSV format...")
sample_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))[:3]
for f in sample_files:
    df = pd.read_csv(f, nrows=3)
    log(f"  {os.path.basename(f)}: {list(df.columns)}, {len(pd.read_csv(f))} rows")

# ── 3. dump_bin 转换 ──
if DO_DUMP:
    log("Running dump_bin...")
    t0 = time.time()

    # Qlib dump_bin 命令
    os.makedirs(BIN_DIR, exist_ok=True)

    from qlib.data.dump import DumpDataAll
    from qlib.constant import REG_CN

    dumper = DumpDataAll(
        csv_path=CSV_DIR,
        qlib_dir=BIN_DIR,
        include_fields=["open", "close", "high", "low", "volume"],
        freq="day",
        region=REG_CN,
    )
    dumper.dump()
    log(f"  dump_bin done ({time.time()-t0:.0f}s)")

    # 检查输出
    bin_size = sum(
        os.path.getsize(os.path.join(dirpath, f))
        for dirpath, _, filenames in os.walk(BIN_DIR)
        for f in filenames
    )
    log(f"  Binary size: {bin_size/1024/1024:.0f} MB")
else:
    log("  (skipping dump_bin, run with --dump to convert)")
    # 检查是否已有 bin 数据
    if os.path.exists(BIN_DIR):
        bin_files = len(glob.glob(os.path.join(BIN_DIR, "**", "*"), recursive=True))
        if bin_files > 10:
            log(f"  Existing bin data found: {bin_files} files")

log(f"\nCSV data ready: {CSV_DIR}")
log(f"  To convert: python build_qlib_data.py --dump")
