#!/home/soso/v5/.venv/bin/python3
"""Line F — 综合评审 + Test 最终评估

1. 读取 B/C/D/E 四份报告
2. 对比 → 选出最优方案
3. 用最优方案在 Test (2021-2026) 上跑一次
4. 输出最终结果

用法: ~/v5/.venv/bin/python3 ~/v5/line_f_synthesis.py
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

TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
FACTOR_JSON = os.path.expanduser("~/ading/data/reports/factor_decay_results_tdx.json")
REPORT_DIR = os.path.expanduser("~/ading/data/reports")
OUT_PATH = os.path.expanduser("~/ading/data/reports/v5_final_synthesis.json")

TEST_START = '2021-01-01'
TEST_END   = '2026-07-14'
DAILY_PICK_K = 5
LIMIT_UP_THRESH = 9.8


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_industry_map():
    db = sqlite3.connect(TDX_DB)
    df = pd.read_sql("SELECT code, sw2_code FROM stock_sw2", db)
    db.close()
    return dict(zip(df['code'], df['sw2_code']))


def simulate_daily_picks(panel, factor_dfs, start, end, industry_map, fwd_T1):
    """同 line_bcd_backtest.py 的回测逻辑"""
    close = panel['close']
    dates = close.index[(close.index >= start) & (close.index <= end)]
    daily_records = []

    for day in dates:
        factors_today = []
        for name, fdf in factor_dfs:
            if day not in fdf.index:
                continue
            vals = fdf.loc[day].dropna()
            if len(vals) > DAILY_PICK_K + 5:
                factors_today.append((name, vals))
        if len(factors_today) < 1:
            continue

        day_idx = close.index.get_loc(day)
        if day_idx == 0:
            continue
        prev_day = close.index[day_idx - 1]
        gain = (close.loc[day] / close.loc[prev_day] - 1) * 100
        limit_up_codes = set(gain[gain >= LIMIT_UP_THRESH].index)

        candidate_sets = []
        for _name, vals in factors_today:
            tradeable = vals.index.difference(limit_up_codes, sort=False)
            if len(tradeable) >= DAILY_PICK_K + 10:
                candidate_sets.append(set(tradeable))
        if len(candidate_sets) < 1:
            continue
        pool = candidate_sets[0]
        for s in candidate_sets[1:]:
            pool = pool.intersection(s)
        if len(pool) < DAILY_PICK_K:
            continue
        pool = list(pool)

        composite = pd.Series(0.0, index=pool)
        for _name, vals in factors_today:
            composite += vals[pool].rank(pct=True)
        composite /= len(factors_today)
        top = composite.nlargest(DAILY_PICK_K)

        if day not in fwd_T1.index:
            continue
        fwd_day = fwd_T1.loc[day].dropna()
        ind_s = pd.Series(industry_map)
        ret_df = pd.DataFrame({'ret': fwd_day, 'sw2': ind_s}).dropna(subset=['sw2'])
        ind_med = ret_df.groupby('sw2')['ret'].median()
        ret_pct = fwd_day.rank(pct=True)

        for code in top.index:
            if code not in fwd_day.index or code not in industry_map:
                continue
            sw2 = industry_map[code]
            if sw2 not in ind_med.index:
                continue
            stock_ret = fwd_day[code]
            beat = 1 if stock_ret > ind_med[sw2] else 0
            rp = ret_pct.get(code)
            daily_records.append({
                'date': str(day.date()), 'code': code,
                'return_pct': round(float(stock_ret), 4),
                'beat': beat,
                'return_percentile': round(float(rp), 4) if rp is not None else None,
            })

    if not daily_records:
        return {'n_trades': 0, 'n_days': len(dates), 'WR': 0.0, 'mean_return': 0.0, 'mean_return_pct': 0.0}

    df = pd.DataFrame(daily_records)
    return {
        'n_trades': len(df), 'n_days': len(dates),
        'WR': round(float(df['beat'].mean()), 4),
        'mean_return': round(float(df['return_pct'].mean()), 4),
        'mean_return_pct': round(float(df['return_percentile'].mean()), 4),
    }


# ═══════════════════════════════════════════
# 读取各线结果
# ═══════════════════════════════════════════
def load_results():
    results = {}
    for line in ['cycle', 'ridge', 'equal', 'e']:
        path = os.path.join(REPORT_DIR, f'line_{line}_results.json')
        if os.path.exists(path):
            with open(path) as f:
                results[line] = json.load(f)
                log(f"  Loaded {path}")
        else:
            log(f"  MISSING: {path}")
    return results


# ═══════════════════════════════════════════
# 对比 + 选最优
# ═══════════════════════════════════════════
def select_best(results):
    log("\n--- 方案对比 ---")

    summary = {}
    # Line B: 取 stability_score
    if 'cycle' in results:
        b = results['cycle']
        summary['B_cycle'] = {
            'stability_score': b.get('stability_score', 0),
            'cycles': {k: {'WR': v['WR']} for k, v in b.get('cycles', {}).items()},
        }
        log(f"  Line B: stability={b.get('stability_score', 0):.3f}")

    # Line C: 取 ridge WR vs equal WR
    if 'ridge' in results:
        c = results['ridge']
        rw = c.get('ridge', {}).get('WR', 0)
        ew = c.get('equal_weight', {}).get('WR', 0)
        summary['C_ridge'] = {
            'ridge_WR': rw, 'equal_WR': ew,
            'diff': c.get('ridge_vs_equal_wr_diff', 0),
            'breakthrough_53': c.get('breakthrough_53', False),
        }
        log(f"  Line C: Ridge WR={rw:.2%} vs Equal WR={ew:.2%} "
            f"(diff={c.get('ridge_vs_equal_wr_diff', 0):.4f})")

    # Line D: 取 best config
    if 'equal' in results:
        d = results['equal']
        best = d.get('best_config', '?')
        best_wr = d.get('best_wr', 0)
        for k, v in d.get('results', {}).items():
            summary[f'D_{k}'] = {'WR': v['WR'], 'trades': v['n_trades'],
                                 'mean_return_pct': v['mean_return_pct']}
        log(f"  Line D: Best={best}, WR={best_wr:.2%}")

    # Line E: ML
    if 'e' in results:
        e = results['e']
        summary['E_ml'] = {
            'ic': e.get('valid_ic', 0),
            'wr': e.get('top5_wr', 0),
            'mean_return': e.get('top5_mean_return', 0),
        }
        log(f"  Line E: IC={e.get('valid_ic', 0):.4f}, WR={e.get('top5_wr', 0):.2%}")

    # 决策: 选 WR 最高的方案
    candidates = []
    if 'D_All' in summary:
        candidates.append(('D_All_equal', summary['D_All']['WR']))
    if 'D_Top3' in summary:
        candidates.append(('D_Top3_equal', summary['D_Top3']['WR']))
    if 'C_ridge' in summary:
        candidates.append(('C_Ridge', summary['C_ridge']['ridge_WR']))
    if 'E_ml' in summary:
        candidates.append(('E_ML', summary['E_ml']['wr']))

    if candidates:
        best_scheme, best_wr = max(candidates, key=lambda x: x[1])
        log(f"\n  → 最优方案: {best_scheme} (WR={best_wr:.2%})")
    else:
        best_scheme, best_wr = 'D_All_equal', 0.0
        log(f"\n  → 无数据, fallback to D_All_equal")

    return {
        'summary': summary,
        'best_scheme': best_scheme,
        'best_valid_wr': best_wr,
    }


# ═══════════════════════════════════════════
# 最终 Test 评估
# ═══════════════════════════════════════════
def final_test(selection):
    log(f"\n{'='*60}")
    log(f"FINAL TEST — {selection['best_scheme']} — {TEST_START} ~ {TEST_END}")
    log(f"{'='*60}")

    # 加载因子
    with open(FACTOR_JSON) as f:
        factor_data = json.load(f)
    ortho = factor_data.get('all_orthogonal', [])
    qualified = [o for o in ortho if o.get('status') in ('confirmed', 'degraded', 'unstable')]
    qualified.sort(key=lambda x: x.get('ic_mean', 0), reverse=True)

    # 根据方案选因子
    scheme = selection['best_scheme']
    if 'Top3' in scheme:
        factor_ids = [q['id'] for q in qualified[:3]]
    elif 'Top5' in scheme:
        factor_ids = [q['id'] for q in qualified[:5]]
    else:
        factor_ids = [q['id'] for q in qualified]  # All

    log(f"  Using {len(factor_ids)} factors: {factor_ids}")

    # 构建全量面板 (到 Test 结束)
    log("Building panel (full data to Test end)...")
    t0 = time.time()
    panel = build_daily_panel(lookback_days=4200, db_path='tdx', date_end=TEST_END)
    dates = panel['close'].index
    log(f"  Panel: {len(dates)}d × {len(panel['close'].columns)}c "
        f"({dates[0].date()} ~ {dates[-1].date()}) [{time.time()-t0:.0f}s]")

    industry_map = load_industry_map()
    fwd_all = compute_forward_returns(panel, horizons=[1])
    fwd_T1 = fwd_all[1]
    del fwd_all
    gc.collect()

    # 计算因子值
    factor_dfs = []
    for aid in factor_ids:
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty:
                factor_dfs.append((aid, vals))
                log(f"  {aid}: {vals.shape}")
        except Exception as e:
            log(f"  {aid}: ERROR {e}")
        gc.collect()

    # 回测
    result = simulate_daily_picks(panel, factor_dfs, TEST_START, TEST_END, industry_map, fwd_T1)
    log(f"\n  FINAL Test Result:")
    log(f"    Trades: {result['n_trades']}")
    log(f"    WR: {result['WR']:.2%}")
    log(f"    Mean Return: {result['mean_return']:.4f}")
    log(f"    Return Percentile: {result['mean_return_pct']:.2%}")

    # 评价
    rp = result['mean_return_pct']
    if rp > 0.70:
        verdict = 'PASS — 跑赢 Top 30%'
    elif rp > 0.50:
        verdict = 'NEUTRAL — 跑赢中位数但未达 Top 30%'
    else:
        verdict = 'FAIL — 需要优化'

    log(f"    Verdict: {verdict}")

    final = {
        'run_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'best_scheme': selection['best_scheme'],
        'best_valid_wr': selection['best_valid_wr'],
        'factors_used': factor_ids,
        'test_period': f'{TEST_START} ~ {TEST_END}',
        'test_result': result,
        'verdict': verdict,
        'comparison': selection['summary'],
    }

    with open(OUT_PATH, 'w') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    log(f"\n  Final synthesis saved to {OUT_PATH}")

    return final


if __name__ == '__main__':
    log("=" * 60)
    log("Line F — Synthesis & Final Test")
    log("=" * 60)

    results = load_results()
    if not results:
        log("FATAL: No line results found. Run Lines B/C/D/E first.")
        sys.exit(1)

    selection = select_best(results)
    final = final_test(selection)
    log("\nDone.")
