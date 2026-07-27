#!/home/soso/v5/.venv/bin/python3
"""T5: WR drop 与剔除衰减提升的统计显著性检验

block bootstrap (时间 block=20天), 考虑日度自相关。
复用 t3a 的 build_panel_light + pkl 因子值。
自己写 simulate 收集每日 WR(轻量, 不存 daily_records)。

检验:
  1. equal_38 的 WR drop (VALID 55% -> TEST 51%) 是否显著
  2. equal_29 vs equal_38 TEST 提升 (+0.84%) 是否显著
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

OUT = '/home/soso/v5/t5_significance_result.json'
VALID_START, VALID_END = '2016-01-01', '2020-12-31'
TEST_START, TEST_END = '2021-01-01', '2026-07-14'
BLOCK = 20
N_BOOT = 5000
SEED = 42


def simulate_daily_wr(panel, fdfs, start, end, industry_map, fwd_T1, factor_weights=None):
    """复制 line_bcd simulate 逻辑, 只返回每日 WR 序列 + mean_return 序列"""
    close = panel['close']
    dates = close.index[(close.index >= start) & (close.index <= end)]
    daily_wrs, daily_rets = [], []
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
            w = factor_weights.get(name, 1.0) if factor_weights else 1.0
            composite += vals[pool].rank(pct=True) * w
            total_w += w
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
    return np.array(daily_wrs), np.array(daily_rets)


def block_bootstrap_ci(series, block=BLOCK, n_boot=N_BOOT, seed=SEED):
    """时间 block bootstrap, 返回 mean 的 95% CI"""
    rng = np.random.default_rng(seed)
    n = len(series)
    if n < 2:
        return (float('nan'), float('nan'))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            s = rng.integers(0, max(1, n - block + 1))
            idx.extend(range(s, min(s + block, n)))
        boots[b] = np.mean(series[idx[:n]])
    return (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))


def main():
    log("=" * 60); log("T5: significance test (block bootstrap)"); log("=" * 60)

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

    results = {}
    for label, fids in [('equal_38', all38), ('equal_29', equal29)]:
        fdfs = load_fdfs(fids)
        log(f"{label}: {len(fdfs)} factors simulate...")
        t1 = time.time()
        vw, vr = simulate_daily_wr(panel, fdfs, VALID_START, VALID_END, industry_map, fwd_T1, None)
        tw, tr = simulate_daily_wr(panel, fdfs, TEST_START, TEST_END, industry_map, fwd_T1, None)
        results[label] = {'valid_wr': vw, 'valid_ret': vr, 'test_wr': tw, 'test_ret': tr}
        log(f"  VALID WR={np.mean(vw):.4f} ({len(vw)}d) | TEST WR={np.mean(tw):.4f} ({len(tw)}d) [{time.time()-t1:.0f}s]")
        del fdfs; gc.collect()

    # bootstrap CI
    out = {'run_at': datetime.now().isoformat(), 'block': BLOCK, 'n_boot': N_BOOT}
    for label in ['equal_38', 'equal_29']:
        r = results[label]
        out[label] = {
            'valid_WR': float(np.mean(r['valid_wr'])),
            'valid_CI': block_bootstrap_ci(r['valid_wr']),
            'test_WR': float(np.mean(r['test_wr'])),
            'test_CI': block_bootstrap_ci(r['test_wr']),
            'n_valid_days': len(r['valid_wr']),
            'n_test_days': len(r['test_wr']),
        }

    e38, e29 = out['equal_38'], out['equal_29']
    drop_overlap = (e38['valid_CI'][1] >= e38['test_CI'][0]) and (e38['test_CI'][1] >= e38['valid_CI'][0])  # 双向检查 = CI 重叠
    improve_overlap = e29['test_CI'][1] >= e38['test_CI'][0] and e38['test_CI'][1] >= e29['test_CI'][0]
    out['verdict'] = {
        'equal_38_drop_55to51': {
            'valid_WR': e38['valid_WR'], 'test_WR': e38['test_WR'],
            'drop': e38['valid_WR'] - e38['test_WR'],
            'valid_CI': e38['valid_CI'], 'test_CI': e38['test_CI'],
            'CI_overlap': bool(drop_overlap),
            'significant': not bool(drop_overlap),
        },
        'equal_29_vs_equal_38_TEST': {
            'e29_WR': e29['test_WR'], 'e38_WR': e38['test_WR'],
            'improve': e29['test_WR'] - e38['test_WR'],
            'e29_CI': e29['test_CI'], 'e38_CI': e38['test_CI'],
            'CI_overlap': bool(improve_overlap),
            'significant': not bool(improve_overlap),
        },
    }
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=2, default=float)
    log(f"written: {OUT}")
    log("=" * 60); log("VERDICT"); log("=" * 60)
    v = out['verdict']
    d1 = v['equal_38_drop_55to51']
    d2 = v['equal_29_vs_equal_38_TEST']
    log(f"equal_38 drop {d1['valid_WR']:.4f}->{d1['test_WR']:.4f} (drop {d1['drop']:.4f}): "
        f"VALID CI [{d1['valid_CI'][0]:.4f},{d1['valid_CI'][1]:.4f}] TEST CI [{d1['test_CI'][0]:.4f},{d1['test_CI'][1]:.4f}] "
        f"-> {'CI重叠=不显著(可能是噪声)' if d1['CI_overlap'] else 'CI不重叠=显著'}")
    log(f"equal_29 vs equal_38 TEST (+{d2['improve']:.4f}): "
        f"e29 CI [{d2['e29_CI'][0]:.4f},{d2['e29_CI'][1]:.4f}] e38 CI [{d2['e38_CI'][0]:.4f},{d2['e38_CI'][1]:.4f}] "
        f"-> {'CI重叠=不显著' if d2['CI_overlap'] else 'CI不重叠=显著'}")


if __name__ == '__main__':
    main()
