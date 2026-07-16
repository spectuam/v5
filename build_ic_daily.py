#!/home/soso/v5/.venv/bin/python3
"""因子 IC 日度数据库 — 月度批处理脚本

每个月独立运行:
  build_ic_daily.py 2020-01 2020-12    # 处理 2020年1月~12月
  build_ic_daily.py 2026-07             # 单月

输出: tdx_stock_data.db → factor_ic_daily 表
"""
import sys, os, gc, warnings, sqlite3, time
warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/soso/trading-strategy')
sys.path.insert(0, '/home/soso/.local/lib/python3.12/site-packages/src/factors')
sys.path.insert(0, '/home/soso/v5')

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta as rd
from factor_zoo_adapter import list_alpha_factors, compute_alpha

DB = os.path.expanduser("~/ading/db/tdx_stock_data.db")
MIN_VALID = 30
HORIZONS = [1, 3, 5, 10, 20]
LOOKBACK = 90

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def month_range(start_ym, end_ym):
    start = datetime.strptime(start_ym, '%Y-%m')
    end = datetime.strptime(end_ym, '%Y-%m')
    months = []
    cur = start
    while cur <= end:
        months.append(cur.strftime('%Y-%m'))
        cur += rd(months=1)
    return months

def build_month_panel(ym, db):
    month_start = datetime.strptime(ym, '%Y-%m')
    month_end = month_start + rd(months=1) - timedelta(days=1)
    panel_start = (month_start - timedelta(days=LOOKBACK)).strftime('%Y-%m-%d')
    panel_end = (month_end + timedelta(days=30)).strftime('%Y-%m-%d')

    df = pd.read_sql("""
        SELECT code, date, open, high, low, close, volume, amount
        FROM daily_kline
        WHERE date >= ? AND date <= ? AND close > 0 AND open > 0
          AND code NOT LIKE 'sz.399%%'
        ORDER BY code, date
    """, db, params=(panel_start, panel_end))
    df['date'] = pd.to_datetime(df['date'])
    df['vwap'] = df['amount'] / df['volume']
    df['vwap'] = df['vwap'].replace([np.inf, -np.inf], np.nan)

    panel = {}
    for f in ['open', 'high', 'low', 'close', 'volume', 'vwap', 'amount']:
        w = df.pivot(index='date', columns='code', values=f)
        panel[f] = w.sort_index().astype('float32')
    return panel, month_start, month_end

def daily_ic(factor_df, fwd_df):
    """逐日 Spearman rank IC: factor_df(date×code), fwd_df(date×code)"""
    common_d = factor_df.index.intersection(fwd_df.index)
    common_c = factor_df.columns.intersection(fwd_df.columns)
    if len(common_d) == 0 or len(common_c) == 0:
        return pd.Series(dtype=float)
    f = factor_df.loc[common_d, common_c]
    r = fwd_df.loc[common_d, common_c]
    mask = f.notna() & r.notna()
    valid = mask.sum(axis=1)
    f_rank = f.rank(axis=1)
    r_rank = r.rank(axis=1)
    ic = f_rank.corrwith(r_rank, axis=1)
    return ic[valid >= MIN_VALID]

def process_month(ym, db, factors):
    log(f"  {ym}: panel...")
    t0 = time.time()
    panel, ms, me = build_month_panel(ym, db)

    month_dates = panel['close'].index[(panel['close'].index >= ms) & (panel['close'].index <= me)]
    if len(month_dates) == 0:
        log(f"    no trading days")
        return []

    # 前向收益
    close = panel['close']
    fwd = {H: close.shift(-H) / close - 1.0 for H in HORIZONS}

    log(f"    {len(month_dates)}d, {len(factors)} factors...")
    rows = []; nf = 0
    for fac in factors:
        zoo, fid = fac['zoo'], fac['id']
        aid = f'{zoo}/{fid}'
        try:
            vals = compute_alpha(zoo, fid + '.py', panel)
            if vals is None or vals.empty:
                continue
        except Exception:
            continue

        # 每天每天 IC
        for H in HORIZONS:
            ic_s = daily_ic(vals, fwd[H])
            for dt in ic_s.index:
                if dt in month_dates:
                    rows.append({
                        'factor_id': aid, 'date': str(dt.date())[:10],
                        f'T{H}_IC': round(float(ic_s[dt]), 6),
                    })

        del vals; nf += 1

    del panel, fwd; gc.collect()

    # 合并同 factor+date 的多 horizon 行
    merged = {}
    for r in rows:
        k = (r['factor_id'], r['date'])
        if k not in merged:
            merged[k] = {'factor_id': r['factor_id'], 'date': r['date'], 'n_valid': 0}
        for H in HORIZONS:
            key = f'T{H}_IC'
            if key in r:
                merged[k][key] = r[key]
                merged[k]['n_valid'] = max(merged[k]['n_valid'], 1)  # placeholder

    result = list(merged.values())
    log(f"    {nf}/{len(factors)} factors, {len(result)} rows, {time.time()-t0:.0f}s")
    return result

def main():
    if len(sys.argv) < 2:
        print("Usage: build_ic_daily.py <start_ym> [end_ym]")
        print("Example: build_ic_daily.py 2020-01 2020-12")
        sys.exit(1)

    start_ym, end_ym = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
    months = month_range(start_ym, end_ym)
    log(f"{len(months)} months: {months[0]} ~ {months[-1]}")

    db = sqlite3.connect(DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic_daily (
            factor_id TEXT NOT NULL, date TEXT NOT NULL,
            T1_IC REAL, T3_IC REAL, T5_IC REAL, T10_IC REAL, T20_IC REAL,
            n_valid INTEGER DEFAULT 0,
            PRIMARY KEY (factor_id, date)
        )
    """)
    db.commit()

    factors = list_alpha_factors()
    log(f'{len(factors)} factors')

    total = 0
    for i, ym in enumerate(months):
        rows = process_month(ym, db, factors)
        for r in rows:
            db.execute("INSERT OR REPLACE INTO factor_ic_daily VALUES (?,?,?,?,?,?,?,?)",
                       [r.get(c) for c in ['factor_id','date','T1_IC','T3_IC','T5_IC','T10_IC','T20_IC','n_valid']])
        db.commit()
        total += len(rows)
        log(f"  [{i+1}/{len(months)}] {total} total rows")
        gc.collect()

    db.close()
    log(f"Done: {total} rows")

if __name__ == '__main__':
    main()
