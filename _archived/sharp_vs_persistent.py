#!/home/soso/v5/.venv/bin/python3
"""Sharp vs Persistent — 两种因子排序法的 6:2:2 回测对比

Persistent (现有): IC_mean 排序, 偏好稳定不衰减的因子
Sharp (新分支):    sharp_score 排序, 偏好 T+1 高且迅速衰减的因子

sharp_score = T+1_IC × (T+1_IC - T+20_IC) × IC>0%
"""
import sys, os, json, gc, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime, date
from factor_decay_utils import build_daily_panel
from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/stock_data.db")
JSON_PATH = os.path.expanduser("~/ading/data/reports/factor_decay_results.json")
FACTOR_LOOKBACK = 90  # 因子计算需要的历史天数
TOP_K = 5  # 每天选几只

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

# ──── 1. 加载 28 个正交因子 ────
log("Loading factor_decay_results.json...")
with open(JSON_PATH) as f:
    data = json.load(f)

ortho = data['all_orthogonal']
log(f"  {len(ortho)} factors loaded")

# ──── 2. 两种排序 ────
# Persistent: IC_mean 降序
persistent_ranked = sorted(ortho, key=lambda x: x['ic_mean'], reverse=True)

# Sharp: sharp_score 降序
# T+20 >= T+1 的因子 (persistent), sharp_score 自然低
for f in ortho:
    ic_by_h = f.get('ic_by_horizon', {})
    t1 = ic_by_h.get('T+1', 0)
    t20 = ic_by_h.get('T+20', 0)
    ic_pos = 1.0  # 都用已知的 IC>0
    f['sharp_score'] = t1 * (t1 - t20) * ic_pos

sharp_ranked = sorted(ortho, key=lambda x: x['sharp_score'], reverse=True)

N_for_branch = {}
# Persistent 的 N (来自 JSON — 如果存在)
# 否则用叠加法
cumulative = data.get('cumulative_ic', [])
if cumulative:
    ic_vals = [(c['k'], c['ic']) for c in cumulative]
    best_k = 1; best_ic = ic_vals[0][1]
    for k, ic in ic_vals[1:]:
        if ic > best_ic + 0.001:
            best_k = k; best_ic = ic
        elif ic < best_ic - 0.002:
            break
    N_persistent = best_k
else:
    N_persistent = 3

# Sharp 分支: 同样叠加法（用 IC_mean 作为权重，sharp 只改变顺序）
N_sharp = min(N_persistent + 2, 10)  # sharp 分支允许稍多因子

log(f"\n{'='*60}")
log(f"  Persistent Top {N_persistent}:")
for f in persistent_ranked[:N_persistent]:
    ic_h = f.get('ic_by_horizon', {})
    log(f"    {f['id']:30s}  T+1={f['ic_mean']:.4f}  "
        f"T+5={ic_h.get('T+5',0):.4f}  T+20={ic_h.get('T+20',0):.4f}  "
        f"sharp={f['sharp_score']:.6f}  cat={f.get('category','')}")

log(f"\n  Sharp Top {N_sharp}:")
for f in sharp_ranked[:N_sharp]:
    ic_h = f.get('ic_by_horizon', {})
    log(f"    {f['id']:30s}  T+1={f['ic_mean']:.4f}  "
        f"T+5={ic_h.get('T+5',0):.4f}  T+20={ic_h.get('T+20',0):.4f}  "
        f"sharp={f['sharp_score']:.6f}  cat={f.get('category','')}")

# ──── 3. 回测函数 ────
def backtest_picks(factor_ids, period_start, period_end, label, db_conn):
    """对给定因子列表, 在指定日期范围内做 daily_pick 模拟"""
    log(f"\n  {label}: {period_start} ~ {period_end}")

    panel = build_daily_panel(lookback_days=9999)

    # 预计算所有因子的值
    factor_dfs = {}
    for fid in factor_ids:
        zoo, fname = fid.split('/')
        try:
            result = compute_alpha(zoo, fname + '.py', panel)
            if result is not None and not result.empty:
                factor_dfs[fid] = result
        except Exception as e:
            log(f"    SKIP {fid}: {e}")
        gc.collect()

    if not factor_dfs:
        log("    ERROR: no factors computable")
        return None

    # 逐日选股
    trading_dates = panel['close'].index[
        (panel['close'].index >= period_start) &
        (panel['close'].index <= period_end)
    ]
    log(f"    {len(trading_dates)} trading days")

    results = []
    for dt in trading_dates:
        dt_str = str(dt.date())

        # 复合排名
        comp = None
        for fid, vals in factor_dfs.items():
            if dt in vals.index:
                row = vals.loc[dt]
                p = row.rank(pct=True) / len(factor_dfs)
                comp = p if comp is None else comp + p

        if comp is None or comp.dropna().empty:
            continue

        # 涨停过滤
        close_today = panel['close'].loc[dt]
        close_yesterday = panel['close'].shift(1).loc[dt] if dt > panel['close'].index[0] else None
        if close_yesterday is not None:
            limit_filter = close_yesterday > 0
            today_gain = (close_today - close_yesterday) / close_yesterday * 100
            valid = (today_gain < 9.8) & limit_filter & close_today.notna()
            comp = comp[comp.index.isin(comp.index[valid])]

        if len(comp.dropna()) < TOP_K:
            continue

        top5 = comp.nlargest(TOP_K)

        for db_code in top5.index:  # panel codes already sh.600000 format

            # T+1 收益
            row = db_conn.execute("""
                SELECT d1.close, d2.close
                FROM daily_kline d1 JOIN daily_kline d2 ON d1.code = d2.code
                WHERE d1.code = ? AND d1.date = ?
                  AND d2.date = (SELECT MIN(date) FROM daily_kline
                                 WHERE code = d1.code AND date > d1.date)
            """, (db_code, dt_str)).fetchone()

            if not row or not row[0] or row[0] <= 0:
                continue
            ret = (row[1] - row[0]) / row[0] * 100

            # 行业中位数
            sw2_row = db_conn.execute(
                "SELECT sw2_code FROM stock_sw2 WHERE code = ?", (db_code,)
            ).fetchone()
            beat = 0
            if sw2_row:
                peers = [r[0] for r in db_conn.execute(
                    "SELECT code FROM stock_sw2 WHERE sw2_code = ? AND code != ? LIMIT 100",
                    (sw2_row[0], db_code)
                ).fetchall()]
                peer_rets = []
                for pc in peers:
                    pr = db_conn.execute("""
                        SELECT d1.close, d2.close FROM daily_kline d1
                        JOIN daily_kline d2 ON d1.code = d2.code
                        WHERE d1.code = ? AND d1.date = ?
                          AND d2.date = (SELECT MIN(date) FROM daily_kline
                                         WHERE code = d1.code AND date > d1.date)
                    """, (pc, dt_str)).fetchone()
                    if pr and pr[0] and pr[0] > 0:
                        peer_rets.append((pr[1] - pr[0]) / pr[0] * 100)
                if peer_rets:
                    med = np.median(peer_rets)
                    beat = 1 if ret > med else 0

            results.append({'date': dt_str, 'code': db_code, 'return': ret, 'beat': beat})

    if not results:
        return None

    df_r = pd.DataFrame(results)
    wr = df_r['beat'].mean() * 100
    avg_ret = df_r['return'].mean()
    n_picks = len(df_r)

    log(f"    Picks: {n_picks}  WR: {wr:.1f}%  Avg ret: {avg_ret:+.2f}%")

    return {'wr': wr, 'avg_ret': avg_ret, 'n_picks': n_picks, 'n_days': df_r['date'].nunique()}

# ──── 4. 跑两个分支 ────
db = sqlite3.connect(DB)

persistent_ids = [f['id'] for f in persistent_ranked[:N_persistent]]
sharp_ids = [f['id'] for f in sharp_ranked[:N_sharp]]

result_persistent = backtest_picks(
    persistent_ids, '2026-01-02', '2026-07-13', 'Persistent', db)
result_sharp = backtest_picks(
    sharp_ids, '2026-01-02', '2026-07-13', 'Sharp', db)

db.close()

# ──── 5. 对比 ────
log(f"\n{'='*60}")
log(f"  对比: Persistent vs Sharp (测试集 2026-01-02 ~ 2026-07-13)")
log(f"  {'Branch':<20} {'Factors':>10} {'WR':>10} {'Avg Ret':>10}")
log(f"  {'-'*50}")
for name, result, ids in [
    ('Persistent', result_persistent, persistent_ids),
    ('Sharp', result_sharp, sharp_ids),
]:
    if result:
        factor_str = ','.join([i.split('/')[1][:6] for i in ids])
        log(f"  {name:<20} {factor_str:>10} {result['wr']:>9.1f}% {result['avg_ret']:>+9.2f}%")

if result_persistent and result_sharp:
    delta = result_sharp['wr'] - result_persistent['wr']
    log(f"\n  Sharp - Persistent = {delta:+.1f}%")
    if delta > 0:
        log(f"  ✅ Sharp 分支胜出")
    elif delta < 0:
        log(f"  ❌ Persistent 更好")
    else:
        log(f"  平手")
log(f"{'='*60}")
