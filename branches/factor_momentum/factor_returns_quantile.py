#!/home/soso/v5/.venv/bin/python3
"""因子分位段多头收益（top10/20/30/40%，周度，A股 long-only 口径）

与 factor_returns_top.py 同口径，但 week_rets（每周全市场 T+5）算一次后
复用给 4 个分位段，避免重复跑最慢的全市场扫描。
top30% 重算与原 factor_returns_top.json 对比作一致性校验。
"""
import sqlite3, os, json, gc, time
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUTDIR = os.path.expanduser('~/v5/branches/factor_momentum')
HORIZON = 5
PCTS = [0.10, 0.20, 0.30, 0.40]
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
    log("=" * 60); log("因子分位段多头收益 (周度, 4分位复用 week_rets)"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池:{len(orth)}因子, 分位:{PCTS}")
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
    log(f"周数:{len(weeks)}, 股票:{len(codes)}")

    # --- week_rets 算一次（最慢，4分位复用）---
    log("预算每周全市场T+5收益(算一次,4分位复用)...")
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

    # --- 读每个因子pkl一次，循环4分位 ---
    log("读因子pkl并算4分位多头收益...")
    results = {p: {} for p in PCTS}
    for i, fid in enumerate(orth):
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        for p in PCTS:
            fr = {}
            for wk in weeks:
                ds = week_first[wk]
                if ds not in fdf.index:
                    continue
                vals = fdf.loc[ds].dropna()
                if len(vals) < 30:
                    continue
                top = vals.sort_values().iloc[int(len(vals) * (1 - p)):].index
                tr = [x for x in (week_rets[wk].get(c) for c in top) if x is not None]
                if not tr:
                    continue
                fr[wk] = float(np.mean(tr))  # 只多头，不减bottom
            results[p][fid] = fr
        del fdf; gc.collect()
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    db.close()

    # --- 输出 + 一致性校验 ---
    log("-" * 60); log("分位段汇总（全部多头收益 t 值）:")
    for p in PCTS:
        out = os.path.join(OUTDIR, f'factor_returns_top_{int(p*100)}.json')
        json.dump(results[p], open(out, 'w'), indent=2, ensure_ascii=False, default=float)
        all_rets = [v for fr in results[p].values() for v in fr.values()]
        arr = np.array(all_rets)
        t = float(arr.mean() / (arr.std() / np.sqrt(len(arr))))
        log(f"  top{int(p*100)}%: written {os.path.basename(out)}, n={len(arr)}, mean={arr.mean():.4f}, t={t:.2f}")

    # top30 与原文件一致性校验
    orig = '/home/soso/v5/branches/factor_momentum/factor_returns_top.json'
    if os.path.exists(orig):
        o = json.load(open(orig))
        diff = sum(1 for f in o for w in o[f] if f in results[0.30] and w in results[0.30][f] and abs(o[f][w] - results[0.30][f][w]) > 1e-9)
        log(f"  校验 top30 与原 factor_returns_top.json 不一致点数: {diff} (应为0)")


if __name__ == '__main__':
    main()
