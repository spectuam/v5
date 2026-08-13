#!/home/soso/v5/.venv/bin/python3
"""Line B/C/D — 统一回测脚本

Line B: 牛熊周期稳定性 — 按市场阶段拆分 Valid, 测各段 WR
Line C: BayesianRidge walk-forward — 滚动训练权重, 对比等权
Line D: 全量等权 — Top3 vs Top5 vs All 对比

用法:
  ~/v5/.venv/bin/python3 ~/v5/line_bcd_backtest.py --mode cycle   # Line B
  ~/v5/.venv/bin/python3 ~/v5/line_bcd_backtest.py --mode ridge   # Line C
  ~/v5/.venv/bin/python3 ~/v5/line_bcd_backtest.py --mode equal   # Line D
  ~/v5/.venv/bin/python3 ~/v5/line_bcd_backtest.py --mode all     # B+C+D 串行, 共用面板

前置: Line A 的 factor_decay_results_tdx.json 必须已存在
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

# ─── 配置 ───
TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
FACTOR_JSON = os.path.expanduser("~/ading/data/reports/factor_decay_results_tdx.json")
OUT_DIR = os.path.expanduser("~/ading/data/reports")

VALID_START = '2016-01-01'
VALID_END   = '2020-12-31'
TEST_START  = '2021-01-01'
TEST_END    = '2026-07-14'
DAILY_PICK_K = 5
LIMIT_UP_THRESH = 9.8
MODE = None
C_SPLIT = None  # e.g. (1, 3) for split 1 of 3
for a in sys.argv:
    if a.startswith('--mode='):
        MODE = a.split('=')[1]
    elif a == '--mode' and len(sys.argv) > sys.argv.index(a) + 1:
        MODE = sys.argv[sys.argv.index(a) + 1]
    elif a.startswith('--c-split='):
        parts = a.split('=')[1].split('/')
        C_SPLIT = (int(parts[0]), int(parts[1]))
    elif a == '--c-split' and len(sys.argv) > sys.argv.index(a) + 1:
        parts = sys.argv[sys.argv.index(a) + 1].split('/')
        C_SPLIT = (int(parts[0]), int(parts[1]))

# 周期切分 (Line B)
CYCLE_SPLITS = [
    ('2016-01-01', '2018-01-26', 'slow_bull'),
    ('2018-01-29', '2019-01-03', 'bear'),
    ('2019-01-04', '2020-12-31', 'range_bull'),
]

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ═══════════════════════════════════════════
# 工具: 计算因子权重 (Train期, 防前视)
# ═══════════════════════════════════════════
def compute_factor_weights(factor_ids, db_path=TDX_DB):
    """从 factor_ic_daily 计算 Train 期 (<=2015-12-31) 的 IC_mean 和 IR。
    返回三套权重: equal, ic, ir (均为 {factor_id: weight})"""
    db = sqlite3.connect(db_path)
    placeholders = ','.join(['?' for _ in factor_ids])
    rows = db.execute(f"""
        SELECT factor_id, AVG(T1_IC), AVG(T1_IC)/NULLIF(AVG(T1_IC*T1_IC)-AVG(T1_IC)*AVG(T1_IC), 0)
        FROM (SELECT factor_id, T1_IC, T1_IC*T1_IC as t1_sq FROM factor_ic_daily
              WHERE date <= '2015-12-31' AND factor_id IN ({placeholders}))
        GROUP BY factor_id
    """, factor_ids).fetchall()
    db.close()

    ic = {}
    ir = {}
    for fid, ic_mean, ir_val in rows:
        if ic_mean is not None and abs(ic_mean) > 0:
            ic[fid] = abs(ic_mean)
        if ir_val is not None and ir_val > 0:
            ir[fid] = ir_val

    # 归一化权重
    def normalize(d):
        total = sum(d.values())
        return {k: v/total*len(d) for k, v in d.items()} if total > 0 else {}

    return {
        'equal': {fid: 1.0 for fid in factor_ids},
        'ic': normalize(ic) if ic else {fid: 1.0 for fid in factor_ids},
        'ir': normalize(ir) if ir else {fid: 1.0 for fid in factor_ids},
    }


# ═══════════════════════════════════════════
# 工具: 从 stock_sw2 加载行业映射
# ═══════════════════════════════════════════
def load_industry_map():
    db = sqlite3.connect(TDX_DB)
    df = pd.read_sql("SELECT code, sw2_code FROM stock_sw2", db)
    db.close()
    return dict(zip(df['code'], df['sw2_code']))


# ═══════════════════════════════════════════
# 工具: 每日选股回测 (同 backtest_validation.simulate_daily_picks)
# ═══════════════════════════════════════════
def simulate_daily_picks(panel, factor_dfs, start, end, industry_map, fwd_T1, factor_weights=None):
    close = panel['close']  # noqa: F841
    dates = close.index[(close.index >= start) & (close.index <= end)]

    daily_records = []
    for day in dates:
        # 取当日因子值
        factors_today = []
        for name, fdf in factor_dfs:
            if day not in fdf.index:
                continue
            vals = fdf.loc[day].dropna()
            if len(vals) > DAILY_PICK_K + 5:
                factors_today.append((name, vals))
        if len(factors_today) < 1:
            continue

        # 过滤涨停
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

        # 复合排名 (支持加权)
        composite = pd.Series(0.0, index=pool)
        total_w = 0.0
        for name, vals in factors_today:
            w = factor_weights.get(name, 1.0) if factor_weights else 1.0
            composite += vals[pool].rank(pct=True) * w
            total_w += w
        composite /= total_w if total_w > 0 else 1
        top = composite.nlargest(DAILY_PICK_K)

        # T+1 收益
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
# Line B: 牛熊周期稳定性
# ═══════════════════════════════════════════
def run_line_b(panel, factor_ids, industry_map, fwd_T1, factor_dfs=None):
    log("=" * 50)
    log("Line B: 牛熊周期稳定性")

    if factor_dfs is None:
        factor_dfs = []
        for aid in factor_ids:
            zoo, fid = aid.split('/')
            try:
                vals = compute_alpha(zoo, fid + '.py', panel)
                if vals is not None and not vals.empty:
                    factor_dfs.append((aid, vals))
                    log(f"  {aid}: computed {vals.shape}")
            except Exception as e:
                log(f"  {aid}: ERROR {e}")
            gc.collect()

    results_by_cycle = {}
    for cs, ce, label in CYCLE_SPLITS:
        r = simulate_daily_picks(panel, factor_dfs, cs, ce, industry_map, fwd_T1)
        results_by_cycle[label] = r
        log(f"  {label} ({cs}~{ce}): WR={r['WR']:.2%}, ret={r['mean_return']:.4f}, "
            f"rp={r['mean_return_pct']:.2%}, trades={r['n_trades']}")

    # 稳定性评分: 三阶段 WR 的 std (越小越稳定)
    wr_values = [results_by_cycle[k]['WR'] for k in results_by_cycle]
    stability = 1.0 - float(np.std(wr_values)) * 3  # std=0 → stability=1.0

    result = {
        'line': 'B',
        'mode': 'cycle_stability',
        'n_factors': len(factor_ids),
        'factor_ids': factor_ids,
        'cycles': results_by_cycle,
        'stability_score': round(max(0, stability), 4),
        'wr_std': round(float(np.std(wr_values)), 4),
    }
    return result


# ═══════════════════════════════════════════
# Line C: BayesianRidge walk-forward
# ═══════════════════════════════════════════
def run_line_c(panel, factor_ids, industry_map, fwd_T1, factor_dfs=None):
    log("=" * 50)
    log("Line C: BayesianRidge walk-forward")
    from sklearn.linear_model import BayesianRidge

    WINDOW = 120

    close = panel['close']
    all_dates = list(close.index[(close.index >= VALID_START) & (close.index <= VALID_END)])

    # --c-split: only process a fraction of dates
    if C_SPLIT is not None:
        chunk, total = C_SPLIT
        n = len(all_dates)
        start_idx = (chunk - 1) * n // total
        end_idx = chunk * n // total
        dates = all_dates[start_idx:end_idx]
        log(f"  Split {chunk}/{total}: dates[{start_idx}:{end_idx}] = {len(dates)} days ({dates[0].date()} ~ {dates[-1].date()})")
    else:
        dates = all_dates

    if len(dates) < WINDOW:
        log(f"  Too few dates ({len(dates)}) for window {WINDOW}")
        return {'line': 'C', 'mode': 'ridge', 'error': f'too few dates: {len(dates)}'}

    if factor_dfs is None:
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

    if len(factor_dfs) < 2:
        log("  Too few factors for Ridge")
        return {'line': 'C', 'mode': 'ridge', 'error': 'too few factors'}

    daily_records_ridge = []

    for di in range(WINDOW, len(dates)):
        train_dates = dates[di - WINDOW:di]
        test_date = dates[di]

        # 构建训练集: 对每个因子, 取 train_dates 上的 rank + 当天收益
        X_train = []
        y_train = []
        common_codes = None

        for _, fdf in factor_dfs:
            train_slice = fdf.loc[fdf.index.isin(train_dates)]
            if train_slice.empty:
                continue
            train_codes = set(c for d in train_dates if d in train_slice.index
                             for c in train_slice.columns if pd.notna(train_slice.loc[d, c]))
            if common_codes is None:
                common_codes = train_codes
            else:
                common_codes = common_codes.intersection(train_codes)

        if common_codes is None or len(common_codes) < 50:
            continue

        for td in train_dates:
            if td not in fwd_T1.index:
                continue
            for code in common_codes:
                feats = []
                ok = True
                for _, fdf in factor_dfs:
                    if td in fdf.index and code in fdf.columns:
                        v = fdf.loc[td, code]
                        if pd.notna(v):
                            feats.append(v)
                        else:
                            ok = False; break
                    else:
                        ok = False; break
                if not ok or not feats:
                    continue
                ret = fwd_T1.loc[td, code] if td in fwd_T1.index and code in fwd_T1.columns else np.nan
                if pd.notna(ret):
                    X_train.append(feats)
                    y_train.append(ret)

        if len(X_train) < 100:
            continue

        # 训练 BayesianRidge
        try:
            model = BayesianRidge(max_iter=300)
            model.fit(X_train, y_train)
        except Exception:
            continue

        # 在 test_date 上预测权重 → 选股
        if test_date not in close.index:
            continue
        test_codes = common_codes
        X_test = []
        test_code_list = []
        for code in test_codes:
            feats = []
            ok = True
            for _, fdf in factor_dfs:
                if test_date in fdf.index and code in fdf.columns:
                    v = fdf.loc[test_date, code]
                    if pd.notna(v):
                        feats.append(v)
                    else:
                        ok = False; break
                else:
                    ok = False; break
            if ok and feats:
                X_test.append(feats)
                test_code_list.append(code)

        if len(X_test) < DAILY_PICK_K:
            continue

        pred = model.predict(X_test)
        scores = pd.Series(pred, index=test_code_list)
        top = scores.nlargest(DAILY_PICK_K)

        # T+1 验证
        if test_date not in fwd_T1.index:
            continue
        fwd_day = fwd_T1.loc[test_date].dropna()
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
            sr = fwd_day[code]
            beat = 1 if sr > ind_med[sw2] else 0
            rp = ret_pct.get(code)
            daily_records_ridge.append({
                'date': str(test_date.date()), 'code': code,
                'return_pct': round(float(sr), 4),
                'beat': beat,
                'return_percentile': round(float(rp), 4) if rp is not None else None,
            })

        if len(daily_records_ridge) % 100 == 0:
            log(f"  C progress: {len(daily_records_ridge)} trades from {di-WINDOW+1}/{len(dates)-WINDOW} test days")

    # --- 同时跑等权对照 ---
    eq_result = simulate_daily_picks(panel, factor_dfs, VALID_START, VALID_END, industry_map, fwd_T1)

    if daily_records_ridge:
        dr = pd.DataFrame(daily_records_ridge)
        ridge_wr = float(dr['beat'].mean())
        ridge_ret = float(dr['return_pct'].mean())
        ridge_rp = float(dr['return_percentile'].mean())
    else:
        ridge_wr = ridge_ret = ridge_rp = 0.0

    result = {
        'line': 'C',
        'mode': 'ridge_walk_forward',
        'n_factors': len(factor_ids),
        'window': WINDOW,
        'ridge': {
            'n_trades': len(daily_records_ridge),
            'WR': round(ridge_wr, 4),
            'mean_return': round(ridge_ret, 4),
            'mean_return_pct': round(ridge_rp, 4),
        },
        'equal_weight': eq_result,
        'ridge_vs_equal_wr_diff': round(ridge_wr - eq_result['WR'], 4),
        'breakthrough_53': ridge_wr > 0.53,
    }
    return result


# ═══════════════════════════════════════════
# Line D: 全量等权对比
# ═══════════════════════════════════════════
def run_line_d(panel, factor_ids, industry_map, fwd_T1, factor_dfs=None):
    log("=" * 50)
    log("Line D: 全量等权对比 (Top3 / Top5 / All)")

    configs = []
    if len(factor_ids) >= 3:
        configs.append(('Top3', 3))
    if len(factor_ids) >= 5:
        configs.append(('Top5', 5))
    configs.append(('All', len(factor_ids)))

    results = {}
    for label, n_factors in configs:
        log(f"  {label}: {n_factors} factors...")
        if factor_dfs is not None:
            fdfs = factor_dfs[:n_factors]  # 直接用预计算切片
        else:
            fdfs = []
            for aid in factor_ids[:n_factors]:
                zoo, fid = aid.split('/')
                try:
                    vals = compute_alpha(zoo, fid + '.py', panel)
                    if vals is not None and not vals.empty:
                        fdfs.append((aid, vals))
                except Exception:
                    pass
                gc.collect()

        r = simulate_daily_picks(panel, fdfs, VALID_START, VALID_END, industry_map, fwd_T1)
        results[label] = r
        log(f"    WR={r['WR']:.2%}, ret={r['mean_return']:.4f}, "
            f"rp={r['mean_return_pct']:.2%}, trades={r['n_trades']}")
        del fdfs
        gc.collect()

    result = {
        'line': 'D',
        'mode': 'equal_weight_compare',
        'results': results,
        'best_config': max(results, key=lambda k: results[k].get('WR', 0)),
        'best_wr': max(r['WR'] for r in results.values()),
    }
    return result


# ═══════════════════════════════════════════
# Main
# ═══════════════════════════════════════════
def main():
    if MODE not in ('cycle', 'ridge', 'equal', 'all'):
        log(f"Usage: line_bcd_backtest.py --mode=<cycle|ridge|equal|all>")
        log(f"  all — B+C+D 串行, 共用面板, 推荐")
        sys.exit(1)

    log("=" * 60)
    log(f"Line B/C/D — Mode: {MODE}")
    log(f"  Valid: {VALID_START} ~ {VALID_END}")
    log("=" * 60)

    # 加载 Line A 结果
    if not os.path.exists(FACTOR_JSON):
        log(f"FATAL: {FACTOR_JSON} not found. Run Line A first.")
        sys.exit(1)
    with open(FACTOR_JSON) as f:
        factor_data = json.load(f)

    ortho = factor_data.get('all_orthogonal', [])
    qualified = [o for o in ortho if o.get('status') in ('confirmed', 'degraded', 'unstable')]
    qualified.sort(key=lambda x: x.get('ic_mean', 0), reverse=True)
    factor_ids = [q['id'] for q in qualified]
    log(f"  {len(factor_ids)} qualified factors from Line A: {factor_ids[:5]}...")

    # 构建面板 (共用)
    log("Building panel for Valid period...")
    t0 = time.time()
    panel = build_daily_panel(lookback_days=4200, db_path='tdx', date_end=VALID_END)
    dates = panel['close'].index
    log(f"  Panel: {len(dates)}d × {len(panel['close'].columns)}c "
        f"({dates[0].date()} ~ {dates[-1].date()}) [{time.time()-t0:.0f}s]")

    log("Loading industry map...")
    industry_map = load_industry_map()
    log(f"  {len(industry_map)} stocks mapped")

    log("Computing forward returns...")
    fwd_all = compute_forward_returns(panel, horizons=[1])
    fwd_T1 = fwd_all[1]
    del fwd_all
    gc.collect()

    # ── ALL 模式: 预计算一次因子值, 串行 B→C→D ──
    if MODE == 'all':
        log("Precomputing all factor values (shared across B/C/D)...")
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
        log(f"  {len(all_fdfs)} factors computed ({time.time()-t0:.0f}s)")

        results_all = {}

        # B
        t_b = time.time()
        results_all['B'] = run_line_b(panel, factor_ids, industry_map, fwd_T1, all_fdfs)
        log(f"Line B done ({time.time()-t_b:.0f}s)")
        gc.collect()

        # C
        t_c = time.time()
        results_all['C'] = run_line_c(panel, factor_ids, industry_map, fwd_T1, all_fdfs)
        log(f"Line C done ({time.time()-t_c:.0f}s)")
        gc.collect()

        # D
        t_d = time.time()
        results_all['D'] = run_line_d(panel, factor_ids, industry_map, fwd_T1, all_fdfs)
        log(f"Line D done ({time.time()-t_d:.0f}s)")

        # 分别存
        for key in results_all:
            if key == 'C' and C_SPLIT is not None:
                suffix = f'_split{C_SPLIT[0]}of{C_SPLIT[1]}'
            else:
                suffix = ''
            fname = 'cycle' if key == 'B' else 'ridge' if key == 'C' else 'equal'
            out_path = os.path.join(OUT_DIR, f'line_{fname}{suffix}_results.json')
            with open(out_path, 'w') as f:
                json.dump(results_all[key], f, ensure_ascii=False, indent=2)
            log(f"  {key} saved to {out_path}")

        log(f"\n=== B+C+D ALL DONE ===")
        return

    # ── 单模式 (调试用) ──
    if MODE == 'cycle':
        result = run_line_b(panel, factor_ids, industry_map, fwd_T1)
    elif MODE == 'ridge':
        result = run_line_c(panel, factor_ids, industry_map, fwd_T1)
    elif MODE == 'equal':
        result = run_line_d(panel, factor_ids, industry_map, fwd_T1)

    out_path = os.path.join(OUT_DIR, f'line_{MODE}_results.json')
    with open(out_path, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"\nResults saved to {out_path}")
    log(json.dumps({k: v for k, v in result.items() if k != 'cycles'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
