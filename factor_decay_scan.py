#!/home/soso/v5/.venv/bin/python3
"""v5 因子衰减扫描 — 主脚本 (v3 流式正交化)

每周末跑一次:
  1. daily_kline 构建后复权面板
  2. 460 因子计算 + T+1 IC（只保留 IC_mean，不存 DataFrame/Series）
  3. 流式贪婪正交去重 — 逐个因子算值、比相关性、释放
  4. 正交池 × 5 周期 IC + 衰减拟合 + 随机对照（一次 compute，全用完）
  5. 逐个叠加定 N → 输出 Top N 因子列表

内存: 全程只存 panel(~200MB) + 最多1个因子 DataFrame(~3MB) + 已入选因子暂存。
峰值 < 500MB。

用法:
  ~/v5/.venv/bin/python3 ~/v5/factor_decay_scan.py --tdx                    # 全量扫描
  ~/v5/.venv/bin/python3 ~/v5/factor_decay_scan.py --tdx --date-end 2015-12-31  # 只看Train期
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
    build_daily_panel, panel_date_range,
    compute_forward_returns, compute_ic_series, compute_ic_summary,
    _shuffle_within_rows, compute_random_ic_series, alpha_series_paired,
    t_stat, fit_decay_curve, categorize_factor,
)

TDX_DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")

OUT_PATH = os.path.expanduser("~/ading/data/reports/factor_decay_results.json")
OUT_PATH_TDX = os.path.expanduser("~/ading/data/reports/factor_decay_results_tdx.json")

# --tdx 命令行开关
USE_TDX = '--tdx' in sys.argv
DB_PATH = 'tdx' if USE_TDX else None
OUT_PATH = OUT_PATH_TDX if USE_TDX else OUT_PATH
if USE_TDX:
    # 额外清理: 之前可能有旧的因子 pickle
    STACK_DIR = os.path.expanduser("~/ading/cache/factor_stacked_tdx")
    os.makedirs(STACK_DIR, exist_ok=True)

# --date-end 命令行: 限制面板截止日期 (用于时间分离, 如 '2015-12-31')
DATE_END = None
for i, arg in enumerate(sys.argv):
    if arg == '--date-end' and i + 1 < len(sys.argv):
        DATE_END = sys.argv[i + 1]
        break

LOOKBACK_DAYS = 9999  # 用全部可用数据
HORIZONS = [1, 3, 5, 10, 20]
RANDOM_SEEDS = 5
CORR_THRESHOLD = 0.7
N_MAX = 10
THRESHOLDS = {'ic_min': 0.02, 'alpha_t_min': 2.0, 'half_life_min': 2.0, 'r2_min': 0.3, 'ir_min': 0.3}
# 注: IR门槛0.3源自v4.2 factor_cluster(IC>0.02, IR>0.3, 365天数据, 产出44个正交因子)

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ═══════════════════════════════════
# Step 1: 面板
# ═══════════════════════════════════
log(f"Step 1/7: Building panel ({LOOKBACK_DAYS}d lookback, date_end={DATE_END or 'all'})...")
t0 = time.time()
panel = build_daily_panel(lookback_days=LOOKBACK_DAYS, db_path=DB_PATH, date_end=DATE_END)
date_start, date_end = panel_date_range(panel)
n_dates = len(panel['close'].index)
n_codes = len(panel['close'].columns)
log(f"  {n_dates}d × {n_codes}c, {date_start} ~ {date_end} ({time.time()-t0:.0f}s)")

# ═══════════════════════════════════
# Step 2: IC 查表预筛选 → 只算通过筛选的因子值（存到文件给 Step 3）
# ═══════════════════════════════════
log("Step 2/7: IC table lookup + factor compute (filtered)...")
t0 = time.time()

from factor_zoo_adapter import list_alpha_factors, compute_alpha
all_factors = list_alpha_factors()
log(f"  {len(all_factors)} factors in zoo")

# 2a. 从 IC 表查 Train 期 IC 和 IR (防前视)
ic_db = sqlite3.connect(TDX_DB)
ic_rows = {}
date_filter = f"date <= '{DATE_END}'" if DATE_END else "1=1"
for r in ic_db.execute(f"""
    SELECT factor_id, AVG(T1_IC), AVG(T1_IC)/NULLIF(SQRT(AVG(T1_IC*T1_IC)-AVG(T1_IC)*AVG(T1_IC)),0)
    FROM factor_ic_daily
    WHERE {date_filter}
    GROUP BY factor_id
"""):
    ic_rows[r[0]] = (r[1] or 0, r[2] or 0)
ic_db.close()
log(f"  {len(ic_rows)} factors in IC table for Train period")

fwd_all = compute_forward_returns(panel, horizons=HORIZONS)
fwd_T1 = fwd_all[1]

STACK_DIR = os.path.expanduser("~/ading/cache/factor_stacked")
os.makedirs(STACK_DIR, exist_ok=True)

factor_ic = {}       # {aid: IC_mean}
factor_files = {}    # {aid: file_path}
n_ok, n_skip, n_filtered = 0, 0, 0

for i, fac in enumerate(all_factors):
    zoo, fid = fac['zoo'], fac['id']
    aid = f'{zoo}/{fid}'

    # 2b. 查表: IC是否过门槛
    ic_mean, ir_val = ic_rows.get(aid, (0, 0))
    if ic_mean == 0:
        n_skip += 1
        continue

    factor_ic[aid] = ic_mean

    if not (ic_mean >= THRESHOLDS['ic_min'] and ir_val >= THRESHOLDS['ir_min']):
        n_filtered += 1
        continue

    # 2c. 通过筛选 → 算因子值存盘 (给 Step 3 正交去重用)
    try:
        result = compute_alpha(zoo, fid + '.py', panel)
        if result is None or result.empty:
            n_skip += 1
            del result
            continue

        s = result.stack().dropna()
        if len(s) > 1000:
            fpath = os.path.join(STACK_DIR, aid.replace('/', '_') + '.pkl')
            s.to_pickle(fpath)
            factor_files[aid] = fpath
        del s, result
        n_ok += 1
    except Exception:
        n_skip += 1

    if (i + 1) % 100 == 0:
        log(f"    [{i+1}/{len(all_factors)}] ok={n_ok} skip={n_skip} filtered={n_filtered}")
        gc.collect()

gc.collect()
log(f"  {n_ok} computed, {n_skip} skipped, {n_filtered} IC-filtered out ({time.time()-t0:.0f}s)")

# ═══════════════════════════════════
# Step 3: 流式贪婪正交去重（从文件读，不重算）
# ═══════════════════════════════════
log(f"Step 3/7: Streaming greedy orthogonalization ({len(factor_files)} factors, from disk)...")
t0 = time.time()

sorted_ids = sorted(factor_files.keys(), key=lambda x: factor_ic[x], reverse=True)

selected_stacked = []  # list of (aid, pd.Series)
selected_ids = []
n_checked = 0

for aid in sorted_ids:
    fpath = factor_files.get(aid)
    if not fpath or not os.path.exists(fpath):
        continue

    # 从文件读，不重算
    cur = pd.read_pickle(fpath)

    # 跟已入选因子逐个比相关性
    conflict = False
    for prev_aid, prev_s in selected_stacked:
        common = cur.index.intersection(prev_s.index)
        if len(common) >= 100:
            c = cur.loc[common].corr(prev_s.loc[common])
            if not np.isnan(c) and c > CORR_THRESHOLD:
                conflict = True
                break

    if conflict:
        del cur
    else:
        selected_ids.append(aid)
        selected_stacked.append((aid, cur))

    n_checked += 1
    if n_checked % 50 == 0:
        log(f"    [{n_checked}/{len(sorted_ids)}] selected={len(selected_ids)}")
        gc.collect()

ortho_pool = selected_ids
log(f"  {len(ortho_pool)} orthogonal factors ({time.time()-t0:.0f}s)")

# 清理
del selected_stacked
# 删临时文件
for fpath in factor_files.values():
    try:
        os.remove(fpath)
    except OSError:
        pass
del factor_files
gc.collect()

# ═══════════════════════════════════
# Step 4: 正交池 × 衰减 + 随机对照（一次 compute 全用完）
# ═══════════════════════════════════
log(f"Step 4/7: Multi-horizon IC from table + decay + random control ({len(ortho_pool)})...")
t0 = time.time()

# 4a. 从 IC 表查多周期 IC (Train 期)
ic_db = sqlite3.connect(TDX_DB)
placeholders = ','.join(['?' for _ in ortho_pool])
date_filter = f"date <= '{DATE_END}'" if DATE_END else "1=1"
multi_ic_rows = ic_db.execute(f"""
    SELECT factor_id,
           AVG(T1_IC), AVG(T3_IC), AVG(T5_IC), AVG(T10_IC), AVG(T20_IC)
    FROM factor_ic_daily
    WHERE {date_filter} AND factor_id IN ({placeholders})
    GROUP BY factor_id
""", ortho_pool).fetchall()
ic_db.close()

# {aid: {1: IC_mean, 3: IC_mean, ...}}
ic_by_factor = {}
for r in multi_ic_rows:
    ic_by_factor[r[0]] = {1: r[1], 3: r[2], 5: r[3], 10: r[4], 20: r[5]}

fit_results = {}
random_results = {}

for idx, aid in enumerate(ortho_pool):
    # 4b. 衰减拟合 (直接用 IC 表)
    ic_vals = [ic_by_factor.get(aid, {}).get(H, np.nan) for H in HORIZONS]
    hl, r2, detail = fit_decay_curve(HORIZONS, ic_vals)
    fit_results[aid] = {
        'half_life': hl, 'r2': r2,
        'ic_by_horizon': {f'T+{H}': ic_by_factor.get(aid, {}).get(H, np.nan) for H in HORIZONS},
        'fit_detail': detail,
    }

    # 4c. 随机对照 (还需要因子值，只算正交池的38个因子)
    zoo, fid = aid.split('/')
    try:
        vals = compute_alpha(zoo, fid + '.py', panel)
        if vals is None or vals.empty:
            continue
    except Exception:
        continue

    ic_signal = compute_ic_series(vals, fwd_T1)
    ic_random = compute_random_ic_series(vals, fwd_T1, n_seeds=RANDOM_SEEDS)
    alpha_s = alpha_series_paired(ic_signal, ic_random)
    alpha_t_val = t_stat(alpha_s)
    random_results[aid] = {
        'alpha_t': round(alpha_t_val, 2),
        'signal_ic_mean': round(ic_signal.mean(), 6) if len(ic_signal) > 0 else 0,
        'random_ic_mean': round(ic_random.mean(), 6) if len(ic_random) > 0 else 0,
        'n_paired_days': len(alpha_s),
    }

    del vals
    if (idx + 1) % 20 == 0:
        log(f"    [{idx+1}/{len(ortho_pool)}]")
        gc.collect()

gc.collect()
log(f"  {time.time()-t0:.0f}s")

# ═══════════════════════════════════
# Step 5: 分类 + 叠加定 N
# ═══════════════════════════════════
log("Step 5/7: Classification + Top N selection...")
t0 = time.time()

categorized = []
for aid in ortho_pool:
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
    categorized.append({
        'id': aid, 'ic_mean': round(ic, 6),
        'ic_by_horizon': fit.get('ic_by_horizon', {}),
        'half_life': cat.get('half_life'),
        'r2': fit.get('r2'), 'alpha_t': rand.get('alpha_t', 0),
        'category': cat['category'], 'status': cat['status'],
        'recommended_freq': cat.get('recommended_freq', ''),
    })

qualified = [c for c in categorized if c['status'] in ('confirmed', 'degraded', 'unstable')]
qualified.sort(key=lambda x: x['ic_mean'], reverse=True)

# 逐个叠加定 N — 流式加载，不囤
log("  Finding optimal N via cumulative IC...")
cumulative_ic = []
n_to_test = min(len(qualified), N_MAX)
comp_acc = None
count_acc = 0

for k in range(n_to_test):
    aid = qualified[k]['id']
    zoo, fid = aid.split('/')
    try:
        vals = compute_alpha(zoo, fid + '.py', panel)
        if vals is not None and not vals.empty:
            p = vals.rank(pct=True)
            comp_acc = p if comp_acc is None else comp_acc + p
            count_acc += 1
        del vals
    except Exception:
        del vals
        continue

    if comp_acc is not None and count_acc > 0:
        avg = comp_acc / count_acc
        c_ic = compute_ic_series(avg, fwd_T1)
        c_ic_mean = c_ic.mean() if len(c_ic) > 0 else 0
        cumulative_ic.append((k + 1, float(c_ic_mean)))
        log(f"    Top {k+1}: cumulative IC = {c_ic_mean:+.4f}")
    else:
        cumulative_ic.append((k + 1, 0.0))

    gc.collect()

# 找拐点
if cumulative_ic:
    ic_vals = [x[1] for x in cumulative_ic]
    best_k = 1; best_ic = ic_vals[0]
    for i in range(1, len(ic_vals)):
        if ic_vals[i] > best_ic + 0.001:
            best_k = i + 1; best_ic = ic_vals[i]
        elif ic_vals[i] < best_ic - 0.002:
            break
    N = best_k
else:
    N = min(3, len(qualified))

top_n = qualified[:N]
top_ids = [t['id'] for t in top_n]
log(f"  Selected Top {N}: {', '.join(top_ids)}")

del comp_acc
gc.collect()

# ═══════════════════════════════════
# 输出
# ═══════════════════════════════════
summary = {
    'short_half_life': sum(1 for c in categorized
                           if c.get('half_life') and c['half_life'] <= 5),
    'medium_half_life': sum(1 for c in categorized
                            if c.get('half_life') and 5 < c['half_life'] <= 15),
    'long_half_life': sum(1 for c in categorized
                          if c.get('half_life') and c['half_life'] > 15),
    'eliminated': sum(1 for c in categorized if c['status'] == 'dead'),
    'noise': sum(1 for c in categorized if c['status'] == 'noise'),
    'too_short': sum(1 for c in categorized if c['status'] == 'too_short'),
}

output = {
    'run_date': date.today().strftime('%Y-%m-%d'),
    'data_range': [date_start, date_end],
    'n_factors_total': len(all_factors),
    'n_factors_valid': n_ok,
    'n_orthogonal_pool': len(ortho_pool),
    'n_qualified': len(qualified),
    'n_selected': N,
    'selected_factors': [{
        'id': t['id'], 'ic_mean': t['ic_mean'],
        'ic_by_horizon': t['ic_by_horizon'],
        'half_life': t['half_life'],
        'category': t['category'],
        'recommended_freq': t.get('recommended_freq', ''),
    } for t in top_n],
    'all_orthogonal': categorized,
    'cumulative_ic': [{'k': k, 'ic': ic} for k, ic in cumulative_ic],
    'summary': summary,
}

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

log(f"\n{'='*55}")
log(f"  v5 因子衰减扫描完成")
log(f"  面板: {n_dates}d × {n_codes}c ({date_start} ~ {date_end})")
log(f"  因子: {n_ok} valid / {len(all_factors)} total")
log(f"  正交池: {len(ortho_pool)} factors")
log(f"  通过门槛: {len(qualified)} factors")
log(f"  Top {N}: {', '.join(top_ids)}")
log(f"  半衰期: 短{summary['short_half_life']} / "
    f"中{summary['medium_half_life']} / 长{summary['long_half_life']}")
log(f"  输出: {OUT_PATH}")
log(f"{'='*55}")
