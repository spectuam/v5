#!/home/soso/v5/.venv/bin/python3
"""v4.2旧5因子 vs v5新Top3 — 公平回测对比
同一把尺子: daily_kline后复权, 申万二级行业中位数, 涨停过滤
"""
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

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def backtest_factors(factor_specs, name, panel, db):
    """用指定因子做逐日选股+回测

    factor_specs: list of (zoo, filename) e.g. ('qlib158', 'min5.py')
    """
    log(f"\n  {name}: computing factors...")
    factor_dfs = {}
    for zoo, fname in factor_specs:
        aid = f'{zoo}/{fname[:-3]}'
        try:
            vals = compute_alpha(zoo, fname, panel)
            if vals is not None and not vals.empty:
                factor_dfs[aid] = vals
                log(f"    {aid}: OK ({vals.shape[0]}d)")
        except Exception as e:
            log(f"    {aid}: SKIP ({e})")
        gc.collect()

    if not factor_dfs:
        return None

    # 逐日选股
    test_dates = panel['close'].index[
        (panel['close'].index >= '2026-01-02') & (panel['close'].index <= '2026-07-15')
    ]
    log(f"    {len(test_dates)} trading days")

    results = []
    n_factors = len(factor_dfs)
    for dt in test_dates:
        dt_str = str(dt.date())
        comp = None; n_used = 0
        for fid, vals in factor_dfs.items():
            if dt in vals.index:
                p = vals.loc[dt].rank(pct=True)
                comp = p if comp is None else comp + p
                n_used += 1

        if comp is None or n_used == 0:
            continue
        comp = comp / n_used

        # 涨停过滤
        close_today = panel['close'].loc[dt]
        close_yesterday = panel['close'].shift(1).loc[dt] if len(panel['close'].index) > 1 else None
        if close_yesterday is not None:
            valid = (close_yesterday > 0) & close_today.notna()
            valid = valid & ((close_today - close_yesterday) / close_yesterday * 100 < 9.8)
        else:
            valid = close_today.notna()
        comp = comp[comp.index.isin(valid.index[valid])]

        if len(comp.dropna()) < TOP_K:
            continue

        top5 = comp.nlargest(TOP_K)

        for code in top5.index:
            row = db.execute("""
                SELECT d1.close, d2.close FROM daily_kline d1
                JOIN daily_kline d2 ON d1.code = d2.code
                WHERE d1.code = ? AND d1.date = ?
                  AND d2.date = (SELECT MIN(date) FROM daily_kline
                                 WHERE code = d1.code AND date > d1.date)
            """, (code, dt_str)).fetchone()
            if not row or not row[0] or row[0] <= 0:
                continue
            ret = (row[1] - row[0]) / row[0] * 100

            sw2_row = db.execute("SELECT sw2_code FROM stock_sw2 WHERE code=?", (code,)).fetchone()
            beat = 0
            if sw2_row:
                peers = [r[0] for r in db.execute(
                    "SELECT code FROM stock_sw2 WHERE sw2_code=? AND code!=? LIMIT 50",
                    (sw2_row[0], code)
                ).fetchall()]
                peer_rets = []
                for pc in peers:
                    pr = db.execute("""
                        SELECT d1.close, d2.close FROM daily_kline d1
                        JOIN daily_kline d2 ON d1.code = d2.code
                        WHERE d1.code = ? AND d1.date = ?
                          AND d2.date = (SELECT MIN(date) FROM daily_kline
                                         WHERE code = d1.code AND date > d1.date)
                    """, (pc, dt_str)).fetchone()
                    if pr and pr[0] and pr[0] > 0:
                        peer_rets.append((pr[1] - pr[0]) / pr[0] * 100)
                if peer_rets:
                    beat = 1 if ret > np.median(peer_rets) else 0

            results.append({'date': dt_str, 'code': code, 'return': ret, 'beat': beat})

    if not results:
        return None

    df_r = pd.DataFrame(results)
    return {
        'wr': round(df_r['beat'].mean() * 100, 1),
        'avg_ret': round(df_r['return'].mean(), 2),
        'n_picks': len(df_r),
        'n_days': df_r['date'].nunique(),
        'pos_rate': round((df_r['return'] > 0).mean() * 100, 1),
    }


# ──── main ────
log("Building panel...")
panel = build_daily_panel(lookback_days=9999)

db = sqlite3.connect(DB)

# v4.2 固定5因子 (来自 v4_backtest_TN.py)
v42_factors = [
    ('qlib158', 'min5.py'),
    ('qlib158', 'qtld10.py'),
    ('alpha101', 'alpha_016.py'),
    ('alpha101', 'alpha_088.py'),
    ('alpha101', 'alpha_040.py'),
]

# v5 Top 3 (从 JSON)
with open(JSON_PATH) as f:
    data = json.load(f)
ortho = sorted(data['all_orthogonal'], key=lambda x: x['ic_mean'], reverse=True)
N = data['n_selected']
v5_factors = [(f['id'].split('/')[0], f['id'].split('/')[1] + '.py') for f in ortho[:N]]

log(f"v4.2: {[z + '/' + f[:-3] for z,f in v42_factors]}")
log(f"v5:   {[z + '/' + f[:-3] for z,f in v5_factors]}")

r42 = backtest_factors(v42_factors, "v4.2 (5F)", panel, db)
r5 = backtest_factors(v5_factors, "v5 (Top 3)", panel, db)

db.close()

# ──── 对比 ────
log(f"\n{'='*65}")
log(f"  v4.2 vs v5 — 公平回测对比 (2026-01-02 ~ 2026-07-13)")
log(f"  {'Branch':<15} {'WR':>8} {'Avg Ret':>10} {'Pos%':>8} {'Picks':>8}")
log(f"  {'-'*49}")
for name, r, specs in [("v4.2 (5F)", r42, v42_factors), ("v5 (3F)", r5, v5_factors)]:
    if r:
        log(f"  {name:<15} {r['wr']:>7.1f}% {r['avg_ret']:>+9.2f}% {r['pos_rate']:>7.1f}% {r['n_picks']:>8}")
if r42 and r5:
    delta = r5['wr'] - r42['wr']
    log(f"\n  v5 - v4.2 = {delta:+.1f}%")
    if delta > 2:
        log(f"  ✅ v5 新因子显著更好")
    elif delta > 0:
        log(f"  △ v5 略好")
    elif delta > -2:
        log(f"  基本持平")
    else:
        log(f"  ❌ v4.2 旧因子更好")
log(f"{'='*65}")
