#!/home/soso/v5/.venv/bin/python3
"""phase2 IC选股 周度版：TSFM(IC>0选top5) + 因子Top10合并去重 + 周度T+5等权

原 phase2_stock.py 是月度 T+20, 这里改周度 T+5, 和 tsmom 同频进 compare_pool。
IC 从 factor_ic_daily 按周聚合, 因子 pkl 取每周首日值。
"""
import sqlite3, os, json, gc, time
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
CAND = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
HORIZON = 5
K = 12
TOP_STOCK = 10
TOP_FACTOR = 5
START, END = '2016-01-01', '2026-06-30'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def week_key(s):
    iso = datetime.strptime(s[:10], '%Y-%m-%d').isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def t_return(db, code, date_str, H=HORIZON):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60); log("phase2 IC选股 周度版 (TSFM top5+Top10合并, T+5)"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    all_dates = [str(r[0])[:10] for r in db.execute(
        "SELECT DISTINCT date FROM daily_kline WHERE date>=? AND date<=? ORDER BY date", (START, END)).fetchall()]
    week_first = {}
    for d in all_dates:
        wk = week_key(d)
        if wk not in week_first:
            week_first[wk] = d
    weeks = sorted(week_first)
    log(f"周数:{len(weeks)}, 因子{len(orth)}, 股票{len(codes)}")

    # IC按周聚合
    log("IC按周聚合...")
    ic_weekly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT date, T20_IC FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL", (fid,)).fetchall()
        for d, ic in rows:
            wk = week_key(str(d)[:10])
            ic_weekly[fid][wk] = ic  # 同周多日取最后(简化)

    # 预算每周全市场T+5
    log("预算每周全市场T+5收益...")
    week_rets = {}
    t0 = time.time()
    for i, wk in enumerate(weeks):
        ds = week_first[wk]
        rets = {}
        for code in codes:
            r = t_return(db, code, ds)
            if r is not None:
                rets[code] = r
        week_rets[wk] = rets
        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(weeks)} [{time.time()-t0:.0f}s]")
    db.close()

    # 读因子pkl, 每周Top10
    log("读因子pkl算每周Top10...")
    factor_top10 = {}
    for fid in orth:
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        factor_top10[fid] = {}
        for wk in weeks:
            ds = week_first[wk]
            if ds not in fdf.index:
                continue
            vals = fdf.loc[ds].dropna()
            if len(vals) < TOP_STOCK:
                continue
            factor_top10[fid][wk] = set(vals.nlargest(TOP_STOCK).index)
        del fdf; gc.collect()

    # TSFM选股
    log("TSFM选股回测...")
    out = {}
    for i, wk in enumerate(weeks):
        if i < K:
            continue
        past = weeks[i - K:i]
        ic_vals = {}
        for fid in orth:
            vals = [ic_weekly[fid].get(p) for p in past]
            vals = [v for v in vals if v is not None]
            if vals:
                ic_vals[fid] = float(np.mean(vals))
        if not ic_vals:
            continue
        sorted_fids = sorted(ic_vals, key=lambda f: -ic_vals[f])
        active = [f for f in sorted_fids if ic_vals[f] > 0][:TOP_FACTOR]
        if not active:
            continue
        stocks = set()
        for fid in active:
            stocks |= factor_top10.get(fid, {}).get(wk, set())
        if not stocks:
            continue
        rets = [week_rets[wk].get(s) for s in stocks]
        rets = [r for r in rets if r is not None]
        if rets:
            out[wk] = float(np.mean(rets))

    arr = np.array(list(out.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    log(f"phase2_IC: {len(out)}周, 全段夏普{sr:.2f}, 年化{arr.mean()*52:.2%}")

    cands = json.load(open(CAND))
    cands['phase2_ic_weekly'] = [[w, out[w]] for w in sorted(out)]
    json.dump(cands, open(CAND, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"合并进 candidates: {list(cands.keys())}")


if __name__ == '__main__':
    main()
