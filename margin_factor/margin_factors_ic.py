#!/home/soso/v5/.venv/bin/python3
"""Phase 2+3: 融资融券7因子 + Spearman IC + 对比OHLCV
按股票算因子, 逐日Spearman IC, 对比cum_ret_20。
因子: RZ_buy_ratio, RZ_chg_1d/5d/20d, RQ_chg_5d, RQ_sell_ratio, RZ_RQ_ratio
"""
import sys, os, sqlite3, time, json, gc
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
OUT = os.path.expanduser('~/v5/margin_factor/margin_factors_ic_result.json')
HORIZONS = [1, 5, 10, 20]


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main():
    log("=" * 60)
    log("Phase 2+3: 融资融券因子 + IC")
    log("=" * 60)
    db = sqlite3.connect(DB)
    log("loading margin_detail...")
    md = pd.read_sql("SELECT code, date, rz_ye, rz_buy, rq_yl, rq_sell FROM margin_detail ORDER BY code, date", db)
    md['date'] = md['date'].str[:10]
    log(f"  {len(md)} rows")

    log("computing factors...")
    md = md.sort_values(['code', 'date'])
    md['RZ_buy_ratio'] = md['rz_buy'] / md['rz_ye']
    md['RZ_chg_1d'] = md.groupby('code')['rz_ye'].pct_change(1)
    md['RZ_chg_5d'] = md.groupby('code')['rz_ye'].pct_change(5)
    md['RZ_chg_20d'] = md.groupby('code')['rz_ye'].pct_change(20)
    md['RQ_chg_5d'] = md.groupby('code')['rq_yl'].pct_change(5)
    md['RQ_sell_ratio'] = md['rq_sell'] / md['rq_yl']

    log("joining close + forward returns + cum_ret_20...")
    dk = pd.read_sql("SELECT code, date, close FROM daily_kline WHERE close>0", db)
    dk['date'] = dk['date'].str[:10]
    md = md.merge(dk, on=['code', 'date'], how='left')
    md['rq_ye'] = md['rq_yl'] * md['close']
    md['RZ_RQ_ratio'] = md['rz_ye'] / md['rq_ye']

    close = md[['code', 'date', 'close']].dropna().sort_values(['code', 'date']).copy()
    for H in HORIZONS:
        close[f'fwd_{H}'] = close.groupby('code')['close'].shift(-H) / close['close'] - 1
    close['cum_ret_20'] = close.groupby('code')['close'].pct_change(20)
    md = md.merge(close[['code', 'date'] + [f'fwd_{H}' for H in HORIZONS] + ['cum_ret_20']],
                  on=['code', 'date'], how='left')

    log("computing daily Spearman IC...")
    factors = ['RZ_buy_ratio', 'RZ_chg_1d', 'RZ_chg_5d', 'RZ_chg_20d',
               'RQ_chg_5d', 'RQ_sell_ratio', 'RZ_RQ_ratio', 'cum_ret_20']
    results = {}
    for fac in factors:
        results[fac] = {}
        for H in HORIZONS:
            col = f'fwd_{H}'
            valid = md[[fac, col, 'date']].dropna()
            if len(valid) < 100:
                continue
            ic = valid.groupby('date').apply(
                lambda g: g[fac].rank().corr(g[col].rank()) if len(g) > 10 else np.nan
            ).dropna()
            if len(ic) == 0:
                continue
            results[fac][f'T{H}'] = {
                'IC_mean': round(float(ic.mean()), 5),
                'IC_std': round(float(ic.std()), 5),
                'ICIR': round(float(ic.mean() / ic.std()), 4) if ic.std() > 0 else 0,
                'IC_win': round(float((ic > 0).mean()), 4),
                'n_days': len(ic),
            }
        log(f"  {fac} done")

    log("=" * 60)
    log("IC RESULT")
    log("=" * 60)
    log(f"{'factor':<16} " + " ".join(f"T{H}_IC/ICIR" for H in HORIZONS))
    for fac in factors:
        parts = []
        for H in HORIZONS:
            r = results[fac].get(f'T{H}')
            if r:
                parts.append(f"{r['IC_mean']:+.4f}/{r['ICIR']:.2f}")
            else:
                parts.append("-")
        log(f"{fac:<16} " + " ".join(parts))
    json.dump(results, open(OUT, 'w'), indent=2, ensure_ascii=False)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
