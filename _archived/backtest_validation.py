#!/home/soso/v5/.venv/bin/python3
"""v5 回测验证 — 三段式 (A: 训练 / B: 验证 / C: 测试)

Phase A (Training):    2024-01-02 ~ 2025-06-30
  - 构建日线面板 → 460因子IC扫描 + 贪婪正交去重 + 衰减拟合 + 随机对照
  - 累积叠加定 N → 选出 Top N 因子
  - 预计算 Top N 因子值 (date×code DataFrames, ≤30MB)

Phase B (Validation):  2025-07-01 ~ 2025-12-31
  - 每日取因子值 → 过滤涨停 → 百分位排名 → 等权复合 → 选 Top 5
  - T+1: 个股收益 vs 申万二级行业中枢 → beat=1/0
  - Output: WR%, mean return%, mean return percentile

Phase C (Test):        2026-01-02 ~ 2026-07-13
  - 同 Phase B
  - 目标: return percentile > Top 30% (跑赢80%的人)

用量: <500MB peak (panel ~300MB + TopN factors ~30MB + 临时因子值逐次释放)
用法: ~/v5/.venv/bin/python3 ~/v5/backtest_validation.py
"""

import sys, os, time, json, gc, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime, date

from factor_decay_utils import (
    build_daily_panel, compute_forward_returns,
    compute_ic_series, compute_ic_summary,
    compute_random_ic_series, alpha_series_paired,
    t_stat, fit_decay_curve, categorize_factor,
)
from factor_zoo_adapter import list_alpha_factors, compute_alpha


# ═══════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════

DB = os.path.expanduser("~/ading/db/stock_data.db")
TRAIN_END = '2025-06-30'
VALID_START = '2025-07-01'
VALID_END   = '2025-12-31'
TEST_START  = '2026-01-02'
TEST_END    = '2026-07-13'
DAILY_PICK_K = 5
TOP_N_MAX = 10
LIMIT_UP_THRESH = 9.8
CORR_THRESHOLD = 0.7
RANDOM_SEEDS = 5
HORIZONS = [1, 3, 5, 10, 20]
THRESHOLDS = {
    'ic_min': 0.02, 'alpha_t_min': 2.0,
    'half_life_min': 2.0, 'r2_min': 0.3, 'ir_min': 0.3,
}
MIN_QUALIFIED = 5


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ═══════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════

def _load_industry_map() -> dict:
    """加载 stock → 申万二级行业代码 映射"""
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT code, sw2_code FROM stock_sw2", conn)
    conn.close()
    return dict(zip(df['code'], df['sw2_code']))


def _load_close_for_validation(panel, fwd_T1):
    """为模拟返回足够的数据切片 — 保留 close + fwd_T1 到完整周期"""
    return panel['close']


# ═══════════════════════════════════════════════════════
# Phase A — 训练 + 因子选择
# ═══════════════════════════════════════════════════════

def phase_a_factor_selection(panel, fwd_all):
    """训练期因子选择流水线。

    Returns:
        list[str]: 选中的 Top N 因子 ID 列表 (e.g. ['alpha101/alpha_001', ...])
    """
    t0 = time.time()
    cutoff = pd.Timestamp(TRAIN_END)

    fwd_all_train = {
        H: fwd_all[H][fwd_all[H].index <= cutoff]
        for H in HORIZONS
    }
    fwd_T1_train = fwd_all_train[1]

    all_factors = list_alpha_factors()
    log(f"  {len(all_factors)} total factors in zoo")

    # ── A-1: 逐个计算因子 → T+1 IC + IR 预筛 ──
    factor_ic = {}            # {aid: IC_mean}
    TMP = os.path.expanduser("~/ading/cache/bt_stacked")
    os.makedirs(TMP, exist_ok=True)
    factor_files = {}          # {aid: pkl_path}
    n_ok = n_skip = 0

    for i, fac in enumerate(all_factors):
        zoo, fid = fac['zoo'], fac['id']
        aid = f'{zoo}/{fid}'

        try:
            result = compute_alpha(zoo, fid + '.py', panel)
            if result is None or result.empty:
                n_skip += 1; del result; continue

            train_slice = result[result.index <= cutoff]
            ic_series = compute_ic_series(train_slice, fwd_T1_train)
            summary = compute_ic_summary(ic_series)
            if np.isnan(summary['IC_mean']):
                n_skip += 1; del result, train_slice; continue

            ic_mean = summary['IC_mean']
            ir_val = summary['IR']
            factor_ic[aid] = ic_mean

            if ic_mean >= THRESHOLDS['ic_min'] and ir_val >= THRESHOLDS['ir_min']:
                s = result.stack().dropna()
                if len(s) > 1000:
                    fpath = os.path.join(TMP, aid.replace('/', '_') + '.pkl')
                    s.to_pickle(fpath)
                    factor_files[aid] = fpath
                del s

            del result, train_slice
            n_ok += 1
        except Exception:
            n_skip += 1

        if (i + 1) % 100 == 0:
            log(f"    [{i+1}/{len(all_factors)}] ok={n_ok} skip={n_skip} qual={len(factor_files)}")
            gc.collect()

    gc.collect()
    log(f"  {n_ok} computed, {n_skip} skipped, {len(factor_files)} passed IC+IR sieve"
        f" ({time.time()-t0:.0f}s)")

    if len(factor_files) < MIN_QUALIFIED:
        log(f"  EARLY EXIT: only {len(factor_files)} qualified factors (need >= {MIN_QUALIFIED})")
        return []

    # ── A-2: 贪婪正交去重 (流式从磁盘读，不囤全部) ──
    t1 = time.time()
    sorted_ids = sorted(factor_files.keys(), key=lambda x: factor_ic[x], reverse=True)
    ortho_ids = []
    ortho_series = []      # (aid, Series) — 只保留已入选的

    for aid in sorted_ids:
        fpath = factor_files.get(aid)
        if not fpath or not os.path.exists(fpath):
            continue
        cur = pd.read_pickle(fpath)
        conflict = False
        for _prev_aid, prev_s in ortho_series:
            common = cur.index.intersection(prev_s.index)
            if len(common) >= 100:
                c = cur.loc[common].corr(prev_s.loc[common])
                if not np.isnan(c) and c > CORR_THRESHOLD:
                    conflict = True
                    break
        if conflict:
            del cur
        else:
            ortho_ids.append(aid)
            ortho_series.append((aid, cur))

    # 清理临时文件
    for fpath in factor_files.values():
        try:
            os.remove(fpath)
        except OSError:
            pass
    del factor_files, ortho_series
    gc.collect()

    log(f"  {len(ortho_ids)} orthogonal factors after greedy ({time.time()-t1:.0f}s)")
    if len(ortho_ids) < 2:
        log("  EARLY EXIT: <2 orthogonal factors")
        return []

    # ── A-3: 正交池 × 多周期衰减 + 随机对照 ──
    t2 = time.time()
    fit_results = {}
    random_results = {}

    for idx, aid in enumerate(ortho_ids):
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is None or vals.empty:
                continue
        except Exception:
            continue

        train_vals = vals[vals.index <= cutoff]

        # 多周期 IC
        h_data = {}
        for H in HORIZONS:
            ic_s = compute_ic_series(train_vals, fwd_all_train[H])
            h_data[H] = compute_ic_summary(ic_s)

        ic_vals = [h_data[H].get('IC_mean', np.nan) for H in HORIZONS]
        hl, r2, detail = fit_decay_curve(HORIZONS, ic_vals)
        fit_results[aid] = {
            'half_life': hl, 'r2': r2,
            'ic_by_horizon': {f'T+{H}': h_data[H]['IC_mean'] for H in HORIZONS},
        }

        # 随机对照
        ic_signal = compute_ic_series(train_vals, fwd_T1_train)
        ic_random = compute_random_ic_series(train_vals, fwd_T1_train,
                                              n_seeds=RANDOM_SEEDS)
        alpha_s = alpha_series_paired(ic_signal, ic_random)
        at = t_stat(alpha_s)
        random_results[aid] = {
            'alpha_t': round(at, 2),
            'signal_ic_mean': round(ic_signal.mean(), 6) if len(ic_signal) > 0 else 0,
            'random_ic_mean': round(ic_random.mean(), 6) if len(ic_random) > 0 else 0,
            'n_paired_days': len(alpha_s),
        }

        del vals, train_vals
        gc.collect()

        if (idx + 1) % 20 == 0:
            log(f"    decay [{idx+1}/{len(ortho_ids)}]")

    del fwd_all_train
    gc.collect()
    log(f"  Decay + random control done ({time.time()-t2:.0f}s)")

    # ── A-4: 分类 + 累积叠加定 N ──
    t3 = time.time()
    qualified = []
    for aid in ortho_ids:
        ic = factor_ic.get(aid, 0)
        fit = fit_results.get(aid, {})
        rand = random_results.get(aid, {})
        cat = categorize_factor(
            ic_mean=ic, ic_positive=0,
            half_life=fit.get('half_life'),
            alpha_t=rand.get('alpha_t', 0),
            r2=fit.get('r2', 0),
            thresholds=THRESHOLDS,
            ic_by_horizon=fit.get('ic_by_horizon', {}),
        )
        if cat['status'] in ('confirmed', 'degraded', 'unstable'):
            qualified.append((aid, ic, cat))

    qualified.sort(key=lambda x: x[1], reverse=True)
    log(f"  {len(qualified)} qualified (confirmed/degraded/unstable)")

    if not qualified:
        log("  No qualified factors")
        return []

    # 累积叠加定 N
    comp_acc = None
    count_acc = 0
    cum_ic = []
    n_test = min(len(qualified), TOP_N_MAX)

    for k in range(n_test):
        aid = qualified[k][0]
        zoo, fid = aid.split('/')
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is not None and not vals.empty:
                p = vals.rank(pct=True)
                comp_acc = p if comp_acc is None else comp_acc + p
                count_acc += 1
            del vals
        except Exception:
            continue

        gc.collect()

        if comp_acc is not None and count_acc > 0:
            avg = comp_acc[comp_acc.index <= cutoff] / count_acc
            c_ic = compute_ic_series(avg, fwd_T1_train)
            c_mean = float(c_ic.mean()) if len(c_ic) > 0 else 0.0
            cum_ic.append((k + 1, c_mean))
            log(f"    Top {k+1}: cum IC = {c_mean:+.4f}")
        else:
            cum_ic.append((k + 1, 0.0))

    # 找拐点
    if cum_ic:
        icv = [x[1] for x in cum_ic]
        best_k, best_ic = 1, icv[0]
        for i in range(1, len(icv)):
            if icv[i] > best_ic + 0.001:
                best_k, best_ic = i + 1, icv[i]
            elif icv[i] < best_ic - 0.002:
                break
        N = min(best_k, n_test)
    else:
        N = min(3, len(qualified))

    selected = [qualified[i][0] for i in range(N)]
    log(f"  Top {N}: {', '.join(selected)} ({time.time()-t3:.0f}s)")
    return selected


# ═══════════════════════════════════════════════════════
# Phase B/C — 每日选股模拟
# ═══════════════════════════════════════════════════════

def simulate_daily_picks(panel, factor_dfs, start, end, industry_map, fwd_T1):
    """每日选股 + T+1 验证

    Args:
        panel: 完整面板 dict
        factor_dfs: [(name, DataFrame(date×code))] — 预计算因子值
        start, end: YYYY-MM-DD 字符串
        industry_map: {code: sw2_code}
        fwd_T1: T+1 收益 DataFrame(date×code)

    Returns:
        dict {n_trades, n_days, WR, mean_return, mean_return_pct, daily_records}
    """
    close = panel['close']
    dates = close.index[(close.index >= start) & (close.index <= end)]
    log(f"  {len(dates)} trading days in range {start} ~ {end}")

    daily_records = []

    for day in dates:
        day_str = str(day.date())

        # a. 取当日各因子值
        factors_today = []
        for name, fdf in factor_dfs:
            if day not in fdf.index:
                continue
            vals = fdf.loc[day].dropna()
            if len(vals) > DAILY_PICK_K + 5:
                factors_today.append((name, vals))

        if len(factors_today) < 1:
            continue

        # b. 过滤涨停 (今日涨幅 >= 9.8%)
        day_idx = close.index.get_loc(day)
        if day_idx == 0:
            continue
        prev_day = close.index[day_idx - 1]
        gain = (close.loc[day] / close.loc[prev_day] - 1) * 100
        limit_up_codes = set(gain[gain >= LIMIT_UP_THRESH].index)

        # 取各因子 intersect 的交集 = 可选股票池
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

        # c. 百分位排名 → 等权 → 复合分
        composite = pd.Series(0.0, index=pool)
        for _name, vals in factors_today:
            composite += vals[pool].rank(pct=True)
        composite /= len(factors_today)

        # d. 选 Top K
        top = composite.nlargest(DAILY_PICK_K)

        # e. T+1 收益 & 行业中枢 & 收益百分位
        if day not in fwd_T1.index:
            continue
        fwd_day = fwd_T1.loc[day]
        fwd_day = fwd_day[fwd_day.notna()]

        # 按申万二级行业算中枢
        ind_map_s = pd.Series(industry_map)
        ret_df = pd.DataFrame({'ret': fwd_day, 'sw2': ind_map_s})
        ret_df = ret_df[ret_df['sw2'].notna()]
        ind_med = ret_df.groupby('sw2')['ret'].median()

        # 全市场收益百分位
        ret_pct = fwd_day.rank(pct=True)

        for code in top.index:
            if code not in fwd_day.index or code not in industry_map:
                continue
            sw2 = industry_map[code]
            if sw2 not in ind_med.index:
                continue

            stock_ret = fwd_day[code]
            med = ind_med[sw2]
            beat = 1 if stock_ret > med else 0
            rp = ret_pct.get(code)

            daily_records.append({
                'date': day_str,
                'code': code,
                'composite': round(float(composite[code]), 4),
                'return_pct': round(float(stock_ret), 4),
                'industry_median': round(float(med), 4),
                'beat': beat,
                'return_percentile': round(float(rp), 4) if rp is not None else None,
            })

        if len(daily_records) % 100 == 0:
            log(f"    ... {len(daily_records)} trades")

    # 汇总
    if not daily_records:
        return {
            'n_trades': 0, 'n_days': len(dates),
            'WR': 0.0, 'mean_return': 0.0, 'mean_return_pct': 0.0,
        }

    df = pd.DataFrame(daily_records)
    wr = float(df['beat'].mean())
    mean_ret = float(df['return_pct'].mean())
    mean_rp = float(df['return_percentile'].mean())

    # 按天聚合
    daily_agg = df.groupby('date').agg(
        picks=('code', 'count'),
        wr_day=('beat', 'mean'),
        ret_avg=('return_pct', 'mean'),
        rp_avg=('return_percentile', 'mean'),
    ).reset_index()

    log(f"  {len(df)} trades, WR={wr:.2%}, mean_ret={mean_ret:.2f}%, "
        f"mean_rp={mean_rp:.2%}")

    return {
        'n_trades': len(df),
        'n_days': len(dates),
        'WR': round(wr, 4),
        'mean_return': round(mean_ret, 4),
        'mean_return_pct': round(mean_rp, 4),
        'daily_records': daily_records,
        'daily_agg': daily_agg.to_dict(orient='records'),
    }


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

def main():
    print('', flush=True)
    log("=" * 65)
    log("v5 回测验证 (A/B/C 三段式)")
    log("=" * 65)

    # ── Step 0: 数据 ──
    log("Building daily panel (all available data)...")
    t_panel = time.time()
    panel = build_daily_panel(lookback_days=9999)
    dates = panel['close'].index
    log(f"  Panel: {len(dates)}d × {len(panel['close'].columns)}c"
        f"  ({dates[0].date()} ~ {dates[-1].date()}) [{time.time()-t_panel:.0f}s]")

    log("Loading industry map (申万二级)...")
    industry_map = _load_industry_map()
    log(f"  {len(industry_map)} stocks mapped to industries")

    # 多周期前向收益 (一次算好, 后面反复用)
    log("Computing forward returns...")
    fwd_all = compute_forward_returns(panel, horizons=HORIZONS)
    fwd_T1 = fwd_all[1]
    log(f"  Forward returns: {list(fwd_all.keys())}")

    # ── Phase A ──
    log("=" * 65)
    log(f"Phase A — Training (thru {TRAIN_END})")
    log("=" * 65)
    selected = phase_a_factor_selection(panel, fwd_all)

    # 释放非 T+1 的前向收益 (省内存)
    for h in HORIZONS:
        if h != 1:
            del fwd_all[h]
    gc.collect()

    if not selected:
        log("FATAL: No factors survived Phase A! Exiting.")
        sys.exit(1)

    # 预计算 Top N 因子全量 DataFrame
    log("Pre-computing selected factor values across all dates...")
    factor_dfs = []
    for aid in selected:
        zoo, fid = aid.split('/')
        fdf = compute_alpha(zoo, fid + '.py', panel)
        if fdf is not None and not fdf.empty:
            factor_dfs.append((aid, fdf))
            log(f"  {aid}: {fdf.shape}")
        del fdf
        gc.collect()
    log(f"  {len(factor_dfs)} factor DataFrames cached")

    # ── Phase B ──
    log("=" * 65)
    log(f"Phase B — Validation ({VALID_START} ~ {VALID_END})")
    log("=" * 65)
    t_val = time.time()
    val_result = simulate_daily_picks(
        panel, factor_dfs, VALID_START, VALID_END,
        industry_map, fwd_T1,
    )
    log(f"  [{time.time()-t_val:.0f}s]")

    # ── Phase C ──
    log("=" * 65)
    log(f"Phase C — Test ({TEST_START} ~ {TEST_END})")
    log("=" * 65)
    t_test = time.time()
    test_result = simulate_daily_picks(
        panel, factor_dfs, TEST_START, TEST_END,
        industry_map, fwd_T1,
    )
    log(f"  [{time.time()-t_test:.0f}s]")

    # ── 输出 ──
    verdict = None
    if test_result['n_trades'] > 0:
        rp = test_result['mean_return_pct']
        if rp > 0.70:
            verdict = 'PASS'
        elif rp > 0.50:
            verdict = 'NEUTRAL'
        else:
            verdict = 'FAIL'

    output = {
        'run_date': date.today().strftime('%Y-%m-%d'),
        'run_time': datetime.now().strftime('%H:%M:%S'),
        'panel_range': [str(dates[0].date()), str(dates[-1].date())],
        'n_codes': len(panel['close'].columns),
        'config': {
            'train_end': TRAIN_END,
            'valid': f'{VALID_START}~{VALID_END}',
            'test': f'{TEST_START}~{TEST_END}',
            'daily_pick_k': DAILY_PICK_K,
            'n_factors_selected': len(selected),
            'limit_up_threshold': LIMIT_UP_THRESH,
        },
        'selected_factors': selected,
        'validation': {
            'n_trades': val_result['n_trades'],
            'n_days': val_result['n_days'],
            'WR': val_result['WR'],
            'mean_return': val_result['mean_return'],
            'mean_return_pct': val_result['mean_return_pct'],
        },
        'test': {
            'n_trades': test_result['n_trades'],
            'n_days': test_result['n_days'],
            'WR': test_result['WR'],
            'mean_return': test_result['mean_return'],
            'mean_return_pct': test_result['mean_return_pct'],
            'target': 'return_percentile > 0.70 (Top 30%)',
            'verdict': verdict,
        },
    }

    # 完整日级记录 (只对 test 做简短)
    if val_result['n_trades'] > 0:
        output['validation']['daily_agg'] = val_result.get('daily_agg', [])
    if test_result['n_trades'] > 0:
        output['test']['daily_agg'] = test_result.get('daily_agg', [])

    print('', flush=True)
    log("=" * 65)
    log("RESULTS")
    log("=" * 65)
    print(json.dumps(output, ensure_ascii=False, indent=2))

    log(f"\n=== Verdict: {verdict} ===")
    if verdict == 'PASS':
        log(f"  Test return_percentile {test_result['mean_return_pct']:.2%} > 70% -- 跑赢目标!")
    elif verdict == 'NEUTRAL':
        log(f"  Test return_percentile {test_result['mean_return_pct']:.2%} -- 跑赢中位数但未达Top 30%")
    else:
        log(f"  Test return_percentile {test_result['mean_return_pct']:.2%} -- 跑输需优化")


if __name__ == '__main__':
    main()
