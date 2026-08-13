#!/home/soso/v5/.venv/bin/python3
"""v5 验证/测试阶段快速运行 — 跳过Phase A，使用预选Top 3因子"""
import sys, os, time, json, gc, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime, date

from factor_decay_utils import build_daily_panel, compute_forward_returns
from factor_zoo_adapter import list_alpha_factors, compute_alpha

DB = os.path.expanduser("~/ading/db/stock_data.db")
LIMIT_UP_THRESH = 9.8
DAILY_PICK_K = 5
VALID_START = '2025-07-01'
VALID_END   = '2025-12-31'
TEST_START  = '2026-01-02'
TEST_END    = '2026-07-13'

SELECTED = ['qlib158/vma60', 'qlib158/qtld30', 'alpha101/alpha_040']

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def load_industry_map():
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, sw2_code FROM stock_sw2", conn)
    conn.close()
    return dict(zip(df['code'], df['sw2_code']))

def simulate(panel, factor_dfs, start, end, industry_map, fwd_T1):
    close = panel['close']
    dates = close.index[(close.index >= start) & (close.index <= end)]
    log(f"  {len(dates)} trading days in {start} ~ {end}")
    daily_records = []

    for day in dates:
        day_str = str(day.date())
        factors_today = []
        for name, fdf in factor_dfs:
            if day not in fdf.index: continue
            vals = fdf.loc[day].dropna()
            if len(vals) > DAILY_PICK_K + 5:
                factors_today.append((name, vals))
        if len(factors_today) < 1: continue

        # 涨停过滤
        day_idx = close.index.get_loc(day)
        if day_idx == 0: continue
        prev_day = close.index[day_idx - 1]
        gain = (close.loc[day] / close.loc[prev_day] - 1) * 100
        limit_up_codes = set(gain[gain >= LIMIT_UP_THRESH].index)

        candidate_sets = []
        for _name, vals in factors_today:
            tradeable = vals.index.difference(limit_up_codes, sort=False)
            if len(tradeable) >= DAILY_PICK_K + 10:
                candidate_sets.append(set(tradeable))
        if len(candidate_sets) < 1: continue
        pool = candidate_sets[0]
        for s in candidate_sets[1:]:
            pool = pool.intersection(s)
        if len(pool) < DAILY_PICK_K: continue
        pool = list(pool)

        # 等权复合
        composite = pd.Series(0.0, index=pool)
        for _name, vals in factors_today:
            composite += vals[pool].rank(pct=True)
        composite /= len(factors_today)
        top = composite.nlargest(DAILY_PICK_K)

        if day not in fwd_T1.index: continue
        fwd_day = fwd_T1.loc[day].dropna()

        ind_map_s = pd.Series(industry_map)
        ret_df = pd.DataFrame({'ret': fwd_day, 'sw2': ind_map_s}).dropna(subset=['sw2'])
        ind_med = ret_df.groupby('sw2')['ret'].median()
        ret_pct = fwd_day.rank(pct=True)

        for code in top.index:
            if code not in fwd_day.index or code not in industry_map: continue
            sw2 = industry_map.get(code)
            if sw2 not in ind_med.index: continue
            stock_ret = fwd_day[code]
            med = ind_med[sw2]
            beat = 1 if stock_ret > med else 0
            rp = ret_pct.get(code)
            daily_records.append({
                'date': day_str, 'code': code,
                'composite': round(float(composite[code]), 4),
                'return_pct': round(float(stock_ret), 4),
                'industry_median': round(float(med), 4),
                'beat': beat,
                'return_percentile': round(float(rp), 4) if rp is not None else None,
            })

    if not daily_records:
        return {'n_trades': 0, 'n_days': len(dates), 'WR': 0.0, 'mean_return': 0.0, 'mean_return_pct': 0.0}
    df = pd.DataFrame(daily_records)
    wr = float(df['beat'].mean())
    mean_ret = float(df['return_pct'].mean())
    mean_rp = float(df['return_percentile'].mean())
    log(f"  {len(df)} trades, WR={wr:.2%}, mean_ret={mean_ret:.2f}%, mean_rp={mean_rp:.2%}")
    return {'n_trades': len(df), 'n_days': len(dates), 'WR': round(wr, 4),
            'mean_return': round(mean_ret, 4), 'mean_return_pct': round(mean_rp, 4)}

def main():
    log("="*65)
    log("v5 Phase B+C — Quick Run (using pre-selected factors)")
    log("="*65)

    # 面板
    log("Building daily panel...")
    panel = build_daily_panel(lookback_days=9999)
    log(f"  Panel: {len(panel['close'])}d × {len(panel['close'].columns)}c")

    # 行业映射
    log("Loading industry map...")
    industry_map = load_industry_map()
    log(f"  {len(industry_map)} stocks")

    # 前向收益
    log("Computing forward returns (T+1)...")
    fwd_all = compute_forward_returns(panel, horizons=[1, 3, 5, 10, 20])
    fwd_T1 = fwd_all[1]
    for h in [3, 5, 10, 20]:
        del fwd_all[h]
    gc.collect()

    # 预计算因子
    log("Pre-computing selected factors...")
    factor_dfs = []
    for aid in SELECTED:
        zoo, fid = aid.split('/')
        fdf = compute_alpha(zoo, fid + '.py', panel)
        if fdf is not None and not fdf.empty:
            factor_dfs.append((aid, fdf))
            log(f"  {aid}: {fdf.shape}")
        del fdf
        gc.collect()
    log(f"  {len(factor_dfs)} factor DataFrames")

    # Phase B - 验证
    log("="*65)
    log(f"Phase B — Validation ({VALID_START} ~ {VALID_END})")
    log("="*65)
    t0 = time.time()
    val = simulate(panel, factor_dfs, VALID_START, VALID_END, industry_map, fwd_T1)
    log(f"  [{time.time()-t0:.0f}s]")

    # Phase C - 测试
    log("="*65)
    log(f"Phase C — Test ({TEST_START} ~ {TEST_END})")
    log("="*65)
    t0 = time.time()
    test = simulate(panel, factor_dfs, TEST_START, TEST_END, industry_map, fwd_T1)
    log(f"  [{time.time()-t0:.0f}s]")

    # 结果
    print("\n" + "="*65)
    print("RESULTS")
    print("="*65)
    print(f"\nPhase B (Validation {VALID_START}~{VALID_END}):")
    print(f"  n_days: {val['n_days']}")
    print(f"  n_trades: {val['n_trades']}")
    print(f"  WR (beat industry median): {val['WR']:.2%}")
    print(f"  Mean return: {val['mean_return']*100:.2f}%")
    print(f"  Mean return percentile: {val['mean_return_pct']:.2%}")

    print(f"\nPhase C (Test {TEST_START}~{TEST_END}):")
    print(f"  n_days: {test['n_days']}")
    print(f"  n_trades: {test['n_trades']}")
    print(f"  WR (beat industry median): {test['WR']:.2%}")
    print(f"  Mean return: {test['mean_return']*100:.2f}%")
    print(f"  Mean return percentile: {test['mean_return_pct']:.2%}")

    verdict = 'PASS' if test['mean_return_pct'] > 0.70 else ('NEUTRAL' if test['mean_return_pct'] > 0.50 else 'FAIL')
    print(f"\nVerdict: {verdict}")

if __name__ == '__main__':
    main()
