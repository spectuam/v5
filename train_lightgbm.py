#!/home/soso/v5/.venv/bin/python3
"""Qlib LightGBM 训练 v2 — 修正版
- 训练集18个月 (2024-01~2025-06)
- RobustZScoreNorm fit_end_time 卡在训练集结束
- 用 Qlib 内置 IC 分析
"""
import qlib, time, os
import pandas as pd
import numpy as np
from qlib.constant import REG_CN
from datetime import datetime

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

log("Init Qlib...")
qlib.init(provider_uri=os.path.expanduser('~/ading/data/qlib/bin'), region=REG_CN)

from qlib.contrib.data.handler import Alpha158
from qlib.contrib.model.gbdt import LGBModel
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

# ── 数据 ──
log("Loading Alpha158...")
t0 = time.time()
h = Alpha158(
    instruments='all',
    start_time='2024-01-02',
    end_time='2026-06-30',
    # 标准化：只用训练集的统计量
    fit_start_time='2024-01-02',
    fit_end_time='2025-06-30',   # ← 关键：卡在训练结束
)
log(f"  {time.time()-t0:.0f}s")

# ── 切分 ──
SEG = {
    'train': ('2024-01-02', '2025-06-30'),
    'valid': ('2025-07-01', '2025-12-31'),
    'test':  ('2026-01-01', '2026-06-30'),
}
log(f"Train: {SEG['train']}, Valid: {SEG['valid']}, Test: {SEG['test']}")

# ── DatasetH ──
log("Building datasets...")
ds = DatasetH(handler=h, segments=SEG, step_len=20)
log(f"  OK")

# ── 训练 LightGBM ──
log("Training...")
t0 = time.time()
model = LGBModel(
    loss='mse',
    n_estimators=500,
    num_leaves=63,
    max_depth=8,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=1.0,
    early_stopping_rounds=50,
    num_threads=4,
    verbosity=-1,
    seed=42,
)
model.fit(ds)
log(f"  Training: {time.time()-t0:.0f}s")

# ── 预测 ──
log("Predicting...")
t0 = time.time()
pred = model.predict(ds, segment='test')
log(f"  {len(pred)} predictions ({time.time()-t0:.0f}s)")

# ── Qlib 内置 IC 分析 ──
log("Computing IC with Qlib built-in...")
from qlib.contrib.eva.alpha import calc_ic

# 获取测试集标签
test_label = h.fetch(col_set='label')

# 对齐预测和标签，转为一维
common = pred.index.intersection(test_label.index)
pred_aligned = pred.loc[common]
if isinstance(pred_aligned, pd.DataFrame):
    pred_aligned = pred_aligned.iloc[:, 0]
label_aligned = test_label.loc[common]
if isinstance(label_aligned, pd.DataFrame):
    label_aligned = label_aligned.iloc[:, 0]

# 用 Qlib 的 calc_ic
ic_series, ric_series = calc_ic(pred_aligned, label_aligned)

ic_mean = ic_series.mean()
ric_mean = ric_series.mean()
ic_std = ic_series.std()
ric_std = ric_series.std()

log(f"\n{'='*55}")
log(f"  LightGBM v2 Results")
log(f"  Train: 2024-01~2025-06 | Test: 2026-01~2026-06")
log(f"  {'Metric':<15} {'IC':>12} {'Rank IC':>12}")
log(f"  {'-'*39}")
log(f"  {'Mean':<15} {ic_mean:>+12.4f} {ric_mean:>+12.4f}")
log(f"  {'Std':<15} {ic_std:>12.4f} {ric_std:>12.4f}")
log(f"  {'IR':<15} {ic_mean/ic_std:>12.3f} {ric_mean/ric_std:>12.3f}")
log(f"  {'IC>0%':<15} {(ic_series>0).mean()*100:>11.1f}% {(ric_series>0).mean()*100:>11.1f}%")
log(f"  {'N_days':<15} {len(ic_series):>12}")
log(f"{'='*55}")
