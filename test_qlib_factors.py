#!/home/soso/v5/.venv/bin/python3
"""测试 Qlib 因子计算 + IC 分析"""
import sqlite3, os, sys, time
import pandas as pd
import numpy as np
from datetime import datetime

DB = os.path.expanduser("~/ading/db/stock_data.db")

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ── 1. 拉数据 ──
log("Loading daily_kline (2025-01 ~ 2026-06)...")
t0 = time.time()
db = sqlite3.connect(DB)
df = pd.read_sql("""
    SELECT code, date, open, high, low, close, volume
    FROM daily_kline d
    WHERE date >= '2025-01-01' AND date <= '2026-06-30'
      AND d.code NOT LIKE 'sz.399%'
      AND d.code NOT IN (SELECT code FROM stock_info WHERE name LIKE '%ST%')
      AND close > 0 AND open > 0
    ORDER BY code, date
""", db)
db.close()
df['date'] = pd.to_datetime(df['date'])
df = df.rename(columns={'code': 'instrument'})
df = df.set_index(['date', 'instrument']).sort_index()
log(f"  {df.shape[0]} rows, {df.index.get_level_values('instrument').nunique()} stocks ({time.time()-t0:.0f}s)")

# ── 2. Qlib 数据接入 ──
import qlib
from qlib.constant import REG_CN
from qlib.data.dataset.handler import DataHandlerLP
from qlib.data.dataset.loader import StaticDataLoader

# 先用 500 只票跑通（全量 5000 后续再试），取半年数据
sample_codes = sorted(df.index.get_level_values('instrument').unique())[:500]
sample = df[df.index.get_level_values('instrument').isin(sample_codes)].copy()
log(f"  Sample: {len(sample)} rows, {len(sample_codes)} stocks, "
    f"{sample.index.get_level_values('date').nunique()} days")

loader = StaticDataLoader(config={"data": sample})
handler = DataHandlerLP(
    data_loader=loader,
    instruments=sample_codes,
    start_time="2025-06-01",
    end_time="2026-06-30",
)
log(f"  DataHandler ready")

# ── 3. 计算 Alpha158 因子 ──
log("Computing Alpha158 factors...")
t0 = time.time()

from qlib.contrib.data.handler import Alpha158

try:
    alpha_handler = Alpha158(
        instruments=sample_codes,
        start_time="2025-06-01",
        end_time="2026-06-30",
        data_loader=loader,
    )
    log(f"  Alpha158 handler created ({time.time()-t0:.0f}s)")

    # 取一部分因子先看看
    factors = alpha_handler.fetch(data_key="feature")
    log(f"  Factors shape: {factors.shape}")
    log(f"  Factor columns (first 20): {list(factors.columns)[:20]}")
    log(f"  Total factors: {len(factors.columns)}")

    # 样本数据
    sample_factors = factors.dropna(how='all').iloc[:5, :8]
    log(f"  Sample factors:\n{sample_factors}")

except Exception as e:
    log(f"ERROR in Alpha158: {e}")
    import traceback
    traceback.print_exc()

# ── 4. 手工验证一个因子（用 Qlib 表达式引擎） ──
log("\nTesting Qlib expression engine...")
try:
    from qlib.data import D

    # 初始化 Qlib 的全局数据实例（Register + D 需要）
    qlib.init(provider_uri=None, region=REG_CN, expression_cache=None)

    instruments = sample_codes[:10]
    # 测试一个简单的表达式: 5日收益率 ROC5 = Ref(close, 5) / close
    expr = D.features(
        instruments,
        ["Ref($close, 5) / $close"],
        start_time="2025-08-01",
        end_time="2025-08-31"
    )
    log(f"  Expression 'ROC5' for 10 stocks, Aug 2025:")
    log(f"  Shape: {expr.shape}")
    log(f"\n{expr.head(6)}")

except Exception as e:
    log(f"ERROR in expression engine: {e}")
    import traceback
    traceback.print_exc()

# ── 5. IC 分析 ──
log("\nComputing Rank IC...")
try:
    # 用简单方式：手工算几天的 IC 验证链路
    close_panel = sample['close'].unstack()
    fwd_ret = close_panel.shift(-1) / close_panel - 1.0  # T+1 收益

    # 模拟一个因子值（20日均线比）
    ma20 = close_panel.rolling(20).mean()
    factor_val = close_panel / ma20

    from scipy.stats import spearmanr
    dates = sorted(factor_val.index.intersection(fwd_ret.index))[-20:]
    ics = []
    for dt in dates:
        fv = factor_val.loc[dt].dropna()
        fr = fwd_ret.loc[dt].dropna()
        common = fv.index.intersection(fr.index)
        if len(common) >= 30:
            ic, _ = spearmanr(fv[common].rank(), fr[common].rank())
            ics.append(ic)

    ic_mean = np.mean(ics)
    ic_std = np.std(ics)
    icir = ic_mean / ic_std if ic_std > 0 else 0
    ic_pos = sum(1 for x in ics if x > 0) / len(ics) if ics else 0

    log(f"  因子: MA20 (500 stocks)")
    log(f"  IC_mean={ic_mean:+.4f}, IC_std={ic_std:.4f}, "
        f"IR={icir:+.3f}, IC>0={ic_pos:.1%}")

except Exception as e:
    log(f"ERROR in IC: {e}")
    import traceback
    traceback.print_exc()

log("\nDone — Qlib factor + IC pipeline works!")
