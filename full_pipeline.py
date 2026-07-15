#!/home/soso/v5/.venv/bin/python3
"""Qlib 完整流程: 训练 → 预测 → 排序选股 → 回测"""
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
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.utils import init_instance_by_config

# ── 1. 数据 ──
log("Loading data...")
h = Alpha158(
    instruments='all',
    start_time='2025-01-02',
    end_time='2026-06-30',
    fit_start_time='2025-01-02',
    fit_end_time='2025-12-31',
)
SEG = {
    'train': ('2025-01-02', '2025-12-31'),
    'valid': ('2026-01-01', '2026-03-31'),
    'test':  ('2026-04-01', '2026-06-30'),
}
ds = DatasetH(handler=h, segments=SEG, step_len=20)

# ── 2. 训练 ──
log("Training...")
t0 = time.time()
model = LGBModel(
    loss='mse', n_estimators=300, num_leaves=63, max_depth=8,
    learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
    reg_alpha=0.1, reg_lambda=1.0, early_stopping_rounds=50,
    num_threads=4, verbosity=-1, seed=42,
)
model.fit(ds)
log(f"  {time.time()-t0:.0f}s")

# ── 3. 预测 ──
log("Predicting...")
pred = model.predict(ds, segment='test')
pred_score = pred.to_frame('score')
log(f"  {len(pred_score)} predictions")

# ── 4. 选股策略 ──
log("Running backtest...")
t0 = time.time()

# TopkDropoutStrategy: 每天按预测分数选 top K 只，没有基本面 dropout
strategy_config = {
    "class": "TopkDropoutStrategy",
    "module_path": "qlib.contrib.strategy",
    "kwargs": {
        "signal": pred_score,
        "topk": 5,
        "n_drop": 0,
    },
}
strategy = init_instance_by_config(strategy_config)

log("  Simulating daily picks...")

# 取测试集每天的预测
pred_df = pred_score.copy()
pred_df.index.names = ['datetime', 'instrument']
test_dates = sorted(pred_df.index.get_level_values('datetime').unique())
log(f"  {len(test_dates)} trading days in test set")

# 预加载测试集实际收益（用 daily_kline 后复权）
import sqlite3
db = sqlite3.connect(os.path.expanduser("~/ading/db/stock_data.db"))

results = []
for dt in test_dates:
    dt_str = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)[:10]

    # 当天预测
    day_pred = pred_df.loc[dt] if dt in pred_df.index.get_level_values(0) else None
    if day_pred is None or day_pred.empty:
        continue

    # 选 Top 5（过滤涨停：当天涨幅 >= 9.8% 的票买不到）
    if isinstance(day_pred, pd.DataFrame):
        day_pred = day_pred['score']

    # 查当天涨幅，排除涨停票
    valid_codes = []
    for qc in day_pred.index:
        dc = qc[:2] + '.' + qc[2:]
        row = db.execute("""
            SELECT d1.close, d2.prev_close FROM
            (SELECT close FROM daily_kline WHERE code=? AND date=?) d1,
            (SELECT close as prev_close FROM daily_kline WHERE code=? AND date < ? ORDER BY date DESC LIMIT 1) d2
        """, (dc, dt_str, dc, dt_str)).fetchone()
        if row and row[0] and row[1] and row[1] > 0:
            if (row[0] - row[1]) / row[1] * 100 < 9.8:
                valid_codes.append(qc)
    day_pred = day_pred[day_pred.index.isin(valid_codes)]

    if len(day_pred) < 5:
        continue
    top5 = day_pred.nlargest(5)

    # 查 T+1 实际收益
    pick_codes = [c.upper().replace('SH', 'sh.').replace('SZ', 'sz.') for c in top5.index]

    for code, score in zip(pick_codes, top5.values):
        # 查买入日收盘和次日收盘（后复权）
        row = db.execute("""
            SELECT d1.close as buy_close, d2.close as sell_close
            FROM daily_kline d1
            JOIN daily_kline d2 ON d1.code = d2.code
            WHERE d1.code = ? AND d1.date = ?
              AND d2.date = (SELECT MIN(date) FROM daily_kline
                             WHERE code = d1.code AND date > d1.date)
        """, (code, dt_str)).fetchone()

        if row and row[0] and row[0] > 0:
            ret = (row[1] - row[0]) / row[0] * 100

            # 涨停过滤：T+1 涨停的收益算不了实际能成交的（买一价封死），标记但不排除
            is_limit_up = 1 if ret >= 9.8 else 0

            # 行业中位数（申万二级）
            sw2_code = db.execute(
                "SELECT sw2_code FROM stock_sw2 WHERE code = ?", (code,)
            ).fetchone()

            sector_ret = None
            beat = 0
            if sw2_code:
                sector_stocks = [r[0] for r in db.execute(
                    "SELECT code FROM stock_sw2 WHERE sw2_code = ? AND code != ?",
                    (sw2_code[0], code)
                ).fetchall()]
                sector_rets = []
                for sc in sector_stocks[:50]:
                    sr = db.execute("""
                        SELECT d1.close, d2.close
                        FROM daily_kline d1
                        JOIN daily_kline d2 ON d1.code = d2.code
                        WHERE d1.code = ? AND d1.date = ?
                          AND d2.date = (SELECT MIN(date) FROM daily_kline
                                         WHERE code = d1.code AND date > d1.date)
                    """, (sc, dt_str)).fetchone()
                    if sr and sr[0] and sr[0] > 0:
                        sector_rets.append((sr[1] - sr[0]) / sr[0] * 100)
                if sector_rets:
                    sector_ret = np.median(sector_rets)
                    beat = 1 if ret > sector_ret else 0

            results.append({
                'date': dt_str, 'code': code, 'score': float(score),
                'return': round(ret, 2), 'sector_med': round(sector_ret, 2) if sector_ret else None,
                'beat': beat,
            })

db.close()

# ── 5. 报告 ──
df_r = pd.DataFrame(results)
if not df_r.empty:
    n_picks = len(df_r)
    n_days = df_r['date'].nunique()
    wr = df_r['beat'].mean() * 100
    avg_ret = df_r['return'].mean()

    # 去掉异常值看T+1
    rets = df_r['return']
    rets_clean = rets[(rets > -15) & (rets < 15)]

    log(f"\n{'='*55}")
    log(f"  Qlib Full Pipeline Results")
    log(f"  Test: 2026-04-01 ~ 2026-06-30")
    log(f"  {'Metric':<20} {'Value':>12}")
    log(f"  {'-'*32}")
    log(f"  {'Picks':<20} {n_picks:>12}")
    log(f"  {'Trading days':<20} {n_days:>12}")
    log(f"  {'Win Rate (beat 行业)':<20} {wr:>11.1f}%")
    log(f"  {'Avg T+1 return':<20} {avg_ret:>+11.2f}%")
    log(f"  {'Best pick':<20} {rets.max():>+11.2f}%")
    log(f"  {'Worst pick':<20} {rets.min():>+11.2f}%")
    log(f"  {'Return std':<20} {rets.std():>11.2f}%")
    log(f"  {'Positive return %':<20} {(rets>0).mean()*100:>10.1f}%")
    log(f"{'='*55}")

    # 每日胜率
    daily_wr = df_r.groupby('date')['beat'].mean() * 100
    log(f"\n  Daily WR — mean={daily_wr.mean():.1f}%, min={daily_wr.min():.0f}%, max={daily_wr.max():.0f}%")
else:
    log("  No results!")

log("Done!")
