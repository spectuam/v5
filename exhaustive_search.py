#!/home/soso/v5/.venv/bin/python3
"""全组合搜索: N=1~3因子组合的最优WR

策略:
  1. 预计算28个因子值 (一次)
  2. 单因子WR排名 (28次)
  3. 双因子全组合 C(28,2)=378次
  4. 三因子: 基于最佳10对 × 剩余26 = 260次 (非全量, 速度优先)

每轮WR评判: 测试集 2026-01-02 ~ 2026-07-13
"""
import sys, os, gc, warnings, itertools, json
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
from datetime import datetime
from factor_decay_utils import build_daily_panel
from factor_zoo_adapter import compute_alpha
import sqlite3

DB = os.path.expanduser("~/ading/db/stock_data.db")
JSON_PATH = os.path.expanduser("~/ading/data/reports/factor_decay_results.json")
TOP_K = 5

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ──── 1. 预计算28个因子 ────
log("Loading factors + panel...")
with open(JSON_PATH) as f:
    data = json.load(f)
ortho = sorted(data['all_orthogonal'], key=lambda x: x['ic_mean'], reverse=True)
all_factors = [(f['id'].split('/')[0], f['id'].split('/')[1] + '.py', f['id'],
                f['ic_mean']) for f in ortho]

panel = build_daily_panel(lookback_days=9999)

log(f"Precomputing {len(all_factors)} factor DataFrames...")
FACTOR_CACHE = {}
for zoo, fname, fid, ic in all_factors:
    try:
        vals = compute_alpha(zoo, fname, panel)
        if vals is not None and not vals.empty:
            FACTOR_CACHE[fid] = vals
    except Exception:
        pass
log(f"  {len(FACTOR_CACHE)} factors ready")

# ──── 2. 预加载 DB 数据 ────
# 测试期所有交易日的所有股票 T+1 收益和行业中位数 (批量查询, 避免逐笔查DB)
log("Pre-loading T+1 returns and sector medians...")
db = sqlite3.connect(DB)

# T+1 收益: (code, date) → ret
t1_returns = {}
dates_list = sorted(panel['close'].index[
    (panel['close'].index >= '2026-01-02') & (panel['close'].index <= '2026-07-15')
])
for row in db.execute("""
    SELECT d1.code, d1.date, (d2.close - d1.close)/d1.close*100
    FROM daily_kline d1
    JOIN daily_kline d2 ON d1.code = d2.code
    WHERE d1.date >= '2026-01-02' AND d1.date <= '2026-07-15' AND d1.close > 0
      AND d2.date = (SELECT MIN(date) FROM daily_kline
                     WHERE code = d1.code AND date > d1.date)
      AND d2.close IS NOT NULL
"""):
    t1_returns[(row[0], row[1])] = row[2]

# 行业映射: code → sw2_code
sw2_map = {}
for row in db.execute("SELECT code, sw2_code FROM stock_sw2"):
    sw2_map[row[0]] = row[1]

# 行业 → codes 映射
sw2_codes = {}
for row in db.execute("SELECT code, sw2_code FROM stock_sw2"):
    sw2_codes.setdefault(row[1], []).append(row[0])

# 每日每行业中位数 (计算一次, 缓存)
sector_medians = {}
for dt in dates_list:
    dt_str = str(dt.date())
    for sw2, codes in list(sw2_codes.items())[:200]:  # 前200个行业 (覆盖大部分)
        rets = []
        for c in codes[:100]:  # 每个行业最多取100只
            r = t1_returns.get((c, dt_str))
            if r is not None:
                rets.append(r)
        if rets:
            sector_medians[(sw2, dt_str)] = np.median(rets)

db.close()
log(f"  {len(t1_returns)} returns, {len(sector_medians)} sector medians loaded")

# ──── 3. 快速回测函数 (因子值已缓存, DB已预加载) ────
def quick_backtest(factor_keys):
    """用已缓存的因子值, 快速回测。factor_keys: list of factor ids"""
    nf = len(factor_keys)
    if nf == 0:
        return None

    results = []
    for dt in dates_list:
        dt_str = str(dt.date())
        close_today = panel['close'].loc[dt]

        # 复合排名
        comp = None
        for fk in factor_keys:
            vals = FACTOR_CACHE[fk]
            if dt not in vals.index:
                continue
            p = vals.loc[dt].rank(pct=True)
            comp = p if comp is None else comp + p
        if comp is None:
            continue
        comp = comp / nf

        # 涨停过滤
        close_yesterday = panel['close'].shift(1).loc[dt]
        valid = (close_yesterday > 0) & close_today.notna()
        valid = valid & ((close_today - close_yesterday) / close_yesterday * 100 < 9.8)
        valid_codes = valid.index[valid]
        comp = comp[comp.index.isin(valid_codes)]
        valid_codes_in_comp = comp.dropna().index

        if len(valid_codes_in_comp) < TOP_K:
            continue

        top5 = comp.loc[valid_codes_in_comp].nlargest(TOP_K)

        for code in top5.index:
            ret = t1_returns.get((code, dt_str))
            if ret is None:
                continue
            sw2 = sw2_map.get(code)
            if not sw2:
                continue
            med = sector_medians.get((sw2, dt_str))
            if med is None:
                continue
            results.append({'ret': ret, 'beat': 1 if ret > med else 0})

    if not results:
        return None
    df = pd.DataFrame(results)
    return {
        'wr': round(df['beat'].mean() * 100, 2),
        'avg_ret': round(df['ret'].mean(), 3),
        'n_picks': len(df),
    }


# ──── 4. 单因子搜索 ────
log(f"\n{'='*60}")
log("  N=1: 单因子最优")
t0 = datetime.now()
best1 = {}
for fid, vals in FACTOR_CACHE.items():
    r = quick_backtest([fid])
    if r:
        best1[fid] = r['wr']
        log(f"    {fid:30s} WR={r['wr']:.1f}%")
top1_id = max(best1, key=best1.get)
log(f"  Best: {top1_id} (WR={best1[top1_id]:.1f}%) in {(datetime.now()-t0).total_seconds():.0f}s")

# ──── 5. 双因子全组合 ────
log(f"\n{'='*60}")
log("  N=2: 双因子全组合 C(28,2)=378")
t0 = datetime.now()
all_ids = list(FACTOR_CACHE.keys())
pair_results = {}
count = 0
for i, j in itertools.combinations(range(len(all_ids)), 2):
    r = quick_backtest([all_ids[i], all_ids[j]])
    if r:
        pair_results[(all_ids[i], all_ids[j])] = r['wr']
    count += 1
    if count % 100 == 0:
        elapsed = (datetime.now() - t0).total_seconds()
        log(f"    [{count}/378] {elapsed:.0f}s")

best2_pair = max(pair_results, key=pair_results.get)
best2_wr = pair_results[best2_pair]
log(f"  Best: {best2_pair[0]}, {best2_pair[1]} (WR={best2_wr:.1f}%) in {(datetime.now()-t0).total_seconds():.0f}s")

# ──── 6. 三因子搜索 — 基于最佳10对 × 剩余因子 ────
log(f"\n{'='*60}")
log("  N=3: 三因子 (最佳10对 × 剩余因子)")
t0 = datetime.now()
top_pairs = sorted(pair_results.items(), key=lambda x: x[1], reverse=True)[:10]

triple_results = {}
for (a, b), base_wr in top_pairs:
    used = {a, b}
    for c in all_ids:
        if c in used:
            continue
        r = quick_backtest([a, b, c])
        if r:
            triple_results[(a, b, c)] = r['wr']

best3_triple = max(triple_results, key=triple_results.get)
best3_wr = triple_results[best3_triple]
log(f"  Best: {best3_triple[0]}, {best3_triple[1]}, {best3_triple[2]} (WR={best3_wr:.1f}%) in {(datetime.now()-t0).total_seconds():.0f}s")

# ──── 7. 输出 ────
log(f"\n{'='*60}")
log(f"  最优因子组合 (全组合搜索)")
log(f"  {'N':>3} {'WR':>8} {'Combo':>60}")
log(f"  {'-'*72}")
r1 = quick_backtest([top1_id])
log(f"  {1:>3} {best1[top1_id]:>7.1f}% {top1_id:>60}")
log(f"  {2:>3} {best2_wr:>7.1f}% {best2_pair[0]:>30s} + {best2_pair[1]:>30s}")
log(f"  {3:>3} {best3_wr:>7.1f}% {best3_triple[0]:>20s} + {best3_triple[1]:>20s} + {best3_triple[2]:>20s}")
log(f"{'='*60}")
