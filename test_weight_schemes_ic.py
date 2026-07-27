#!/home/soso/v5/.venv/bin/python3
"""测试三套权重方案: equal / IC / IR
在 Valid 和 Test 期分别回测，对比 WR

用法:
  ~/v5/.venv/bin/python3 ~/v5/test_weight_schemes_ic.py
"""
import sys, os, time, json, gc, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime

from factor_decay_utils import build_daily_panel, compute_forward_returns
from factor_zoo_adapter import compute_alpha
from line_bcd_backtest import (
    compute_factor_weights, load_industry_map, simulate_daily_picks
)

TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
FACTOR_JSON = os.path.expanduser("~/ading/data/reports/factor_decay_results_tdx.json")

VALID_START = '2016-01-01'
VALID_END = '2020-12-31'
TEST_START = '2021-01-01'
TEST_END = '2026-07-14'

DAILY_PICK_K = 5
LIMIT_UP_THRESH = 9.8

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def main():
    log("=" * 60)
    log("IC/IR 加权 vs 等权 对比测试")

    # ── 加载因子 ──
    with open(FACTOR_JSON) as f:
        factor_data = json.load(f)
    ortho = factor_data.get('all_orthogonal', [])
    qualified = [o for o in ortho if o.get('status') in ('confirmed', 'degraded', 'unstable')]
    qualified.sort(key=lambda x: x.get('ic_mean', 0), reverse=True)
    factor_ids = [q['id'] for q in qualified]
    log(f"Loaded {len(factor_ids)} factors")

    # ── 三套权重 ──
    all_weights = compute_factor_weights(factor_ids)
    for scheme in ['equal', 'ic', 'ir']:
        w = all_weights[scheme]
        vals = list(w.values())
        log(f"  {scheme}: mean={np.mean(vals):.2f}, std={np.std(vals):.2f}, "
            f"min={np.min(vals):.3f}, max={np.max(vals):.3f}")

    # ── 构建面板 (Train=2006-2015, 因子权重来源) ──
    log("Building panel for full range...")
    t0 = time.time()
    panel = build_daily_panel(lookback_days=5000, db_path='tdx', date_end=TEST_END)
    dates = panel['close'].index
    log(f"  Panel: {len(dates)}d × {len(panel['close'].columns)}c "
        f"({dates[0].date()} ~ {dates[-1].date()}) [{time.time()-t0:.0f}s]")

    # ── 行业映射 ──
    industry_map = load_industry_map()
    log(f"  {len(industry_map)} stocks mapped")

    # ── 前向收益 ──
    log("Computing forward returns...")
    fwd_all = compute_forward_returns(panel, horizons=[1])
    fwd_T1 = fwd_all[1]
    del fwd_all; gc.collect()

    # ── 预计算因子值 ──
    log("Computing all factor values...")
    t0 = time.time()
    all_fdfs = []
    for aid in factor_ids:
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty:
                all_fdfs.append((aid, vals))
        except Exception as e:
            log(f"  {aid}: ERROR {e}")
        gc.collect()
    log(f"  {len(all_fdfs)}/{len(factor_ids)} factors computed ({time.time()-t0:.0f}s)")

    # ── 跑 ──
    results = {}
    for period_name, ps, pe in [('Valid', VALID_START, VALID_END),
                                 ('Test', TEST_START, TEST_END)]:
        log(f"\n{'='*40}")
        log(f"Period: {period_name} ({ps} ~ {pe})")
        results[period_name] = {}
        for scheme in ['equal', 'ic', 'ir']:
            w = all_weights[scheme]
            t0 = time.time()
            r = simulate_daily_picks(panel, all_fdfs, ps, pe, industry_map, fwd_T1,
                                      factor_weights=w)
            elapsed = time.time() - t0
            results[period_name][scheme] = r
            log(f"  {scheme:6s}: WR={r['WR']:.2%}, ret={r['mean_return']:+.4f}, "
                f"rp={r['mean_return_pct']:.2%}, trades={r['n_trades']} "
                f"[{elapsed:.0f}s]")

    # ── 汇总 ──
    log(f"\n{'='*60}")
    log("SUMMARY")
    print()
    header = f"{'':>8} {'WR':>10} {'mean_ret':>10} {'ret_pct':>10} {'trades':>8}"
    print(header)
    print("-" * len(header))
    for period_name in ['Valid', 'Test']:
        for scheme in ['equal', 'ic', 'ir']:
            r = results[period_name][scheme]
            label = f"{period_name}/{scheme}"
            print(f"{label:>8} {r['WR']:>9.2%} {r['mean_return']:>+9.4f} "
                  f"{r['mean_return_pct']:>9.2%} {r['n_trades']:>8}")
    print()

    # 最佳方案
    for period_name in ['Valid', 'Test']:
        best = max(results[period_name], key=lambda k: results[period_name][k]['WR'])
        log(f"  {period_name} best: {best} (WR={results[period_name][best]['WR']:.2%})")

    # 存盘
    out_path = os.path.expanduser("~/ading/data/reports/weight_scheme_comparison.json")
    with open(out_path, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log(f"\nSaved to {out_path}")

if __name__ == '__main__':
    main()
