#!/home/soso/v5/.venv/bin/python3
"""28正交因子按IC排名分成8组(每组3个), 逐组回测, 找最优IC区间"""
import sys, os, json, gc, warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
import sqlite3
from datetime import datetime
from factor_decay_utils import build_daily_panel
from factor_zoo_adapter import compute_alpha

DB = os.path.expanduser("~/ading/db/stock_data.db")
JSON_PATH = os.path.expanduser("~/ading/data/reports/factor_decay_results.json")
TOP_K = 5
GROUP_SIZE = 3

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def backtest_group(factor_specs, label, panel, db):
    """回测一组因子, 返回 WR"""
    factor_dfs = {}
    for zoo, fname in factor_specs:
        try:
            vals = compute_alpha(zoo, fname, panel)
            if vals is not None and not vals.empty:
                factor_dfs[f'{zoo}/{fname[:-3]}'] = vals
        except Exception:
            pass
        gc.collect()

    if not factor_dfs:
        return None

    nf = len(factor_dfs)
    results = []
    dates = panel['close'].index[
        (panel['close'].index >= '2026-01-02') & (panel['close'].index <= '2026-07-15')
    ]

    for dt in dates:
        dt_str = str(dt.date())
        comp = None; nu = 0
        for fid, vals in factor_dfs.items():
            if dt in vals.index:
                p = vals.loc[dt].rank(pct=True)
                comp = p if comp is None else comp + p
                nu += 1
        if comp is None or nu == 0:
            continue
        comp = comp / nu

        ct = panel['close'].loc[dt]
        cy = panel['close'].shift(1).loc[dt] if len(panel['close'].index) > 1 else None
        if cy is not None:
            v = (cy > 0) & ct.notna() & ((ct - cy) / cy * 100 < 9.8)
            comp = comp[comp.index.isin(v.index[v])]

        if len(comp.dropna()) < TOP_K:
            continue

        for code in comp.nlargest(TOP_K).index:
            r = db.execute("""
                SELECT d1.close, d2.close FROM daily_kline d1
                JOIN daily_kline d2 ON d1.code = d2.code
                WHERE d1.code = ? AND d1.date = ?
                  AND d2.date = (SELECT MIN(date) FROM daily_kline
                                 WHERE code = d1.code AND date > d1.date)
            """, (code, dt_str)).fetchone()
            if not r or not r[0] or r[0] <= 0:
                continue
            ret = (r[1] - r[0]) / r[0] * 100

            sw2_row = db.execute("SELECT sw2_code FROM stock_sw2 WHERE code=?", (code,)).fetchone()
            beat = 0
            if sw2_row:
                peers = [p[0] for p in db.execute(
                    "SELECT code FROM stock_sw2 WHERE sw2_code=? AND code!=? LIMIT 50",
                    (sw2_row[0], code)
                ).fetchall()]
                prs = []
                for pc in peers:
                    pr = db.execute("""
                        SELECT d1.close, d2.close FROM daily_kline d1
                        JOIN daily_kline d2 ON d1.code = d2.code
                        WHERE d1.code = ? AND d1.date = ?
                          AND d2.date = (SELECT MIN(date) FROM daily_kline
                                         WHERE code = d1.code AND date > d1.date)
                    """, (pc, dt_str)).fetchone()
                    if pr and pr[0] and pr[0] > 0:
                        prs.append((pr[1] - pr[0]) / pr[0] * 100)
                if prs:
                    beat = 1 if ret > np.median(prs) else 0
            results.append({'ret': ret, 'beat': beat})

    if not results:
        return None
    df = pd.DataFrame(results)
    return {
        'wr': round(df['beat'].mean() * 100, 1),
        'avg_ret': round(df['return'].mean() if 'return' in df else df['ret'].mean(), 2),
        'n_picks': len(df),
        'pos_rate': round((df['ret'] > 0).mean() * 100, 1),
    }


log("Building panel...")
panel = build_daily_panel(lookback_days=9999)
db = sqlite3.connect(DB)

with open(JSON_PATH) as f:
    data = json.load(f)
ortho = sorted(data['all_orthogonal'], key=lambda x: x['ic_mean'], reverse=True)

# 分组
all_ids = [(f['id'].split('/')[0], f['id'].split('/')[1] + '.py', f['ic_mean']) for f in ortho]
groups = []
for i in range(0, len(all_ids), GROUP_SIZE):
    g = all_ids[i:i+GROUP_SIZE]
    avg_ic = np.mean([x[2] for x in g])
    names = [x[0] + '/' + x[1][:-3] for x in g]
    groups.append((g, avg_ic, names))

log(f"28 factors → {len(groups)} groups (size {GROUP_SIZE})")

results = []
for idx, (group, avg_ic, names) in enumerate(groups):
    ranges = f"{(idx*GROUP_SIZE+1)}-{min((idx+1)*GROUP_SIZE, 28)}"
    specs = [(z, f) for z, f, _ in group]
    log(f"\n  Group {ranges} (avg IC={avg_ic:.4f}): {', '.join(names)}")
    r = backtest_group(specs, f"G{ranges}", panel, db)
    if r:
        results.append((ranges, len(specs), avg_ic, r['wr'], r['avg_ret'], r['pos_rate'], r['n_picks']))
        log(f"    WR={r['wr']:.1f}%")
    gc.collect()

db.close()

log(f"\n{'='*70}")
log(f"  分组回测结果 (28正交因子, 每组3个, 按IC排名)")
log(f"  {'IC Rank':<10} {'N':>3} {'Avg IC':>8} {'WR':>8} {'Avg Ret':>10} {'Pos%':>7} {'Picks':>7}")
log(f"  {'-'*53}")
max_wr = 0; max_grp = ""
for ranges, n, ic, wr, avg_ret, pos, picks in results:
    star = "*" if wr > max_wr else " "
    if wr > max_wr:
        max_wr = wr; max_grp = ranges
    log(f"  {ranges:<10} {n:>3} {ic:>+8.4f} {wr:>7.1f}% {avg_ret:>+9.2f}% {pos:>6.1f}% {picks:>7} {star}")

log(f"\n  最佳组: IC排名 {max_grp}, WR={max_wr:.1f}%")
top3_wr = results[0][3] if results else 0
log(f"  vs Top3: Δ={max_wr-top3_wr:+.1f}%")
log(f"{'='*70}")
