#!/home/soso/v5/.venv/bin/python3
"""测试 daily_kline → Qlib DataHandler 数据接入"""
import sqlite3, os, sys, time
import pandas as pd
import numpy as np
from datetime import datetime

DB = os.path.expanduser("~/ading/db/stock_data.db")

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ── 1. 从 daily_kline 拉数据 ──
log("Loading daily_kline...")
t0 = time.time()
db = sqlite3.connect(DB)

# 取最近500天，排除ST，只取正常上市的
df = pd.read_sql("""
    SELECT code, date, open, high, low, close, volume
    FROM daily_kline d
    WHERE date >= '2024-01-01'
      AND d.code NOT LIKE 'sz.399%'
      AND d.code NOT IN (SELECT code FROM stock_info WHERE name LIKE '%ST%')
      AND close > 0 AND open > 0
    ORDER BY code, date
""", db)
db.close()

log(f"  {len(df)} rows, {df['code'].nunique()} stocks, "
    f"{df['date'].nunique()} days ({time.time()-t0:.0f}s)")

# ── 2. 转换为 Qlib 格式 ──
# Qlib 需要: MultiIndex (datetime, instrument), columns = features
log("Converting to Qlib format...")

df['date'] = pd.to_datetime(df['date'])
df = df.rename(columns={'code': 'instrument'})
df = df.set_index(['date', 'instrument']).sort_index()

log(f"  MultiIndex shape: {df.shape}")

# ── 3. 初始化 Qlib (不需要 dump_bin，直接用 DataFrame) ──
log("Initializing Qlib with custom data...")

import qlib
from qlib.constant import REG_CN
from qlib.data.dataset.handler import DataHandlerLP
from qlib.data.dataset.loader import StaticDataLoader

# 用 StaticDataLoader 直接从 DataFrame 加载
try:
    loader = StaticDataLoader(config={"data": df})
    log("  StaticDataLoader: created")

    handler = DataHandlerLP(
        data_loader=loader,
        instruments=df.index.get_level_values('instrument').unique().tolist()[:100],  # 先用100只测试
        start_time="2025-01-01",
        end_time="2025-06-30",
    )
    log("  DataHandlerLP: created")

    # 获取数据
    raw_data = handler.fetch(data_key="raw")
    log(f"  fetch('raw'): {raw_data.shape if raw_data is not None else 'None'}")

    if raw_data is not None:
        log(f"    columns: {list(raw_data.columns)}")
        log(f"    sample:\n{raw_data.head(3)}")

    log("SUCCESS: daily_kline → Qlib 数据接入成功!")

except Exception as e:
    log(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
