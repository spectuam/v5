#!/home/soso/v5/.venv/bin/python3
"""净收益分析：扣换手成本后策略是否赚钱

复用 t5 simulate 逻辑, 收集 daily Top5, 算换手率 × 成本扫描。
对比 equal_38 vs equal_29。
内存: build panel 3.7G + 读pkl, 峰值 3.7G (同 t5, 安全)。
"""
import sys, os, json, gc, time, resource
from datetime import datetime

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np, pandas as pd
from line_bcd_backtest import load_industry_map, FACTOR_JSON, DAILY_PICK_K, LIMIT_UP_THRESH
from factor_decay_utils import compute_forward_returns
from t3a_weight_compare import build_panel_light, pkl_path, DECAYED, log, rss_mb

OUT = '/home/soso/v5/t6_net_return_result.json'
VALID_START, VALID_END = '2016-01-01', '2020-12-31'
TEST_START, TEST_END = '2021-01-01', '2026-07-14'
COSTS = [0.001, 0.002, 0.003, 0.005]  # 单边 0.1/0.2/0.3/0.5%


def simulate_daily_top5(panel, fdfs, start, end, industry_map, fwd_T1):
    """同 t5 simulate (等权), 额外返回 daily top5 code sets"""
    close = panel['close']
    dates = close.index[(close.index >= start) & (close.index <= end)]
    daily_wrs, daily_rets, daily_tops = [], [], []
    for day in dates:
        factors_today = []
        for name, fdf in fdfs:
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
        limit_up = set(gain[gain >= LIMIT_UP_THRESH].index)
        candidate_sets = []
        for _n, vals in factors_today:
            tradeable = vals.index.difference(limit_up, sort=False)
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
        total_w = 0.0
        for name, vals in factors_today:
            composite += vals[pool].rank(pct=True)
            total_w += 1.0
        composite /= total_w if total_w > 0 else 1
        top = composite.nlargest(DAILY_PICK_K)
        if day not in fwd_T1.index:
            continue
        fwd_day = fwd_T1.loc[day].dropna()
        ind_s = pd.Series(industry_map)
        ret_df = pd.DataFrame({'ret': fwd_day, 'sw2': ind_s}).dropna(subset=['sw2'])
        ind_med = ret_df.groupby('sw2')['ret'].median()
        beats, rets = [], []
        for code in top.index:
            if code not in fwd_day.index or code not in industry_map:
                continue
            sw2 = industry_map[code]
            if sw2 not in ind_med.index:
                continue
            sr = fwd_day[code]
            beats.append(1 if sr > ind_med[sw2] else 0)
            rets.append(sr)
        if beats:
            daily_wrs.append(float(np.mean(beats)))
            daily_rets.append(float(np.mean(rets)))
            daily_tops.append(set(top.index))
    return np.array(daily_wrs), np.array(daily_rets), daily_tops


def turnover_stats(daily_tops):
    """返回 (平均日换手率, 天数)"""
    if len(daily_tops) < 2:
        return 0.0, 0
    turns = []
    for i in range(1, len(daily_tops)):
        prev, cur = daily_tops[i - 1], daily_tops[i]
        if not prev or not cur:
            continue
        overlap = len(prev & cur)
        turnover = (len(cur) - overlap) / len(cur)
        turns.append(turnover)
    return (float(np.mean(turns)) if turns else 0.0), len(turns)


def main():
    log("=" * 60); log("净收益分析: 扣换手成本后是否赚钱"); log("=" * 60)

    d = json.load(open(FACTOR_JSON))
    ortho = [o for o in d['all_orthogonal'] if o.get('status') in ('confirmed', 'degraded', 'unstable')]
    ortho.sort(key=lambda x: x.get('ic_mean', 0), reverse=True)
    all38 = [o['id'] for o in ortho]
    equal29 = [f for f in all38 if f not in DECAYED]
    log(f"groups: equal_38={len(all38)}, equal_29={len(equal29)}")

    log("Building panel...")
    panel = build_panel_light(lookback_days=4200, date_end=TEST_END)
    industry_map = load_industry_map()
    fwd_T1 = compute_forward_returns(panel, horizons=[1])[1]
    for k in ['open', 'high', 'low', 'volume', 'vwap', 'amount']:
        if k in panel:
            del panel[k]
    gc.collect()
    log(f"panel ready RSS={rss_mb()}MB")

    def load_fdfs(fids):
        return [(aid, pd.read_pickle(pkl_path(aid))) for aid in fids if os.path.exists(pkl_path(aid))]

    out = {'run_at': datetime.now().isoformat(), 'costs_single_bps': [c * 1000 for c in COSTS], 'schemes': {}}
    for label, fids in [('equal_38', all38), ('equal_29', equal29)]:
        fdfs = load_fdfs(fids)
        log(f"{label}: {len(fdfs)} factors simulate...")
        t1 = time.time()
        vw, vr, vtops = simulate_daily_top5(panel, fdfs, VALID_START, VALID_END, industry_map, fwd_T1)
        tw, tr, ttops = simulate_daily_top5(panel, fdfs, TEST_START, TEST_END, industry_map, fwd_T1)
        gross_v = float(np.mean(vr)) * 250
        gross_t = float(np.mean(tr)) * 250
        avg_turn_v, n_v = turnover_stats(vtops)
        avg_turn_t, n_t = turnover_stats(ttops)
        scheme = {
            'gross_annual_valid': round(gross_v, 4), 'gross_annual_test': round(gross_t, 4),
            'avg_turnover_valid': round(avg_turn_v, 4), 'avg_turnover_test': round(avg_turn_t, 4),
            'n_turns_valid': n_v, 'n_turns_test': n_t,
            'by_cost': {},
        }
        for cost in COSTS:
            cpd_v = avg_turn_v * cost * 2  # 买+卖
            cpd_t = avg_turn_t * cost * 2
            net_v = gross_v - cpd_v * 250
            net_t = gross_t - cpd_t * 250
            key = f'{cost * 1000:.1f}bps'
            scheme['by_cost'][key] = {
                'cost_annual_valid': round(cpd_v * 250, 4),
                'cost_annual_test': round(cpd_t * 250, 4),
                'net_annual_valid': round(net_v, 4),
                'net_annual_test': round(net_t, 4),
            }
        out['schemes'][label] = scheme
        log(f"  gross V={gross_v:.4f} T={gross_t:.4f} | turnover V={avg_turn_v:.2%} T={avg_turn_t:.2%} [{time.time()-t1:.0f}s]")
        for cost in COSTS:
            c = scheme['by_cost'][f'{cost * 1000:.1f}bps']
            log(f"    cost {cost*1000:.1f}bps: net V={c['net_annual_valid']:.4f} T={c['net_annual_test']:.4f}")
        del fdfs; gc.collect()

    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=2)
    log(f"written: {OUT}")
    log("=" * 60); log("SUMMARY (net annual return)"); log("=" * 60)
    log(f"{'scheme':<12} {'gross_T':>8} {'turn_T':>7} | " + " ".join(f"{c*1000:.0f}bps" for c in COSTS))
    for label in ['equal_38', 'equal_29']:
        s = out['schemes'][label]
        nets = [f"{s['by_cost'][f'{c*1000:.1f}bps']['net_annual_test']:.3f}" for c in COSTS]
        log(f"{label:<12} {s['gross_annual_test']:>8.4f} {s['avg_turnover_test']:>7.2%} | " + " ".join(nets))


if __name__ == '__main__':
    main()
