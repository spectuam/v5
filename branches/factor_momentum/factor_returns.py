#!/home/soso/v5/.venv/bin/python3
"""因子收益时间序列（EL口径：top30%-bottom30% 多空收益，月度）
复现 GK/EL TSMOM 的信号基础。每月每因子多空组合收益。
数据: factor pkl(因子值) + daily_kline(T+20收益)
解耦: 只读两表，流式每因子算完释放。
"""
import sqlite3, os, json, gc, time
from datetime import datetime
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns.json')
HORIZON = 20
TOP_PCT, BOT_PCT = 0.30, 0.30  # top30% - bottom30%


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(db, code, date_str, H=HORIZON):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def main():
    log("=" * 60); log("因子收益时间序列 (EL口径 top30%-bottom30% 多空, 月度)"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池:{len(orth)}因子")
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]

    yms = [f"{y}-{m:02d}" for y in range(2016, 2027) for m in range(1, 13) if '2016-01' <= f"{y}-{m:02d}" <= '2026-06']
    month_date = {}
    for ym in yms:
        r = db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()
        if r and r[0]:
            month_date[ym] = str(r[0])[:10]
    log(f"月数:{len(month_date)}, 股票:{len(codes)}")

    # 预算月度全市场T+20收益
    log("预算月度全市场T+20收益...")
    month_rets = {}
    t0 = time.time()
    for i, (ym, ds) in enumerate(month_date.items()):
        rets = {}
        for code in codes:
            r = t_return(db, code, ds)
            if r is not None:
                rets[code] = r
        month_rets[ym] = rets
        if (i + 1) % 12 == 0:
            log(f"  {i+1}/{len(month_date)} [{time.time()-t0:.0f}s]")

    # 每因子每月 top30%-bottom30% 多空收益
    log("算每因子每月多空收益...")
    factor_ret = {}
    for i, fid in enumerate(orth):
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        fr = {}
        for ym, ds in month_date.items():
            if ds not in fdf.index:
                continue
            vals = fdf.loc[ds].dropna()
            if len(vals) < 30:
                continue
            sorted_vals = vals.sort_values()
            n = len(sorted_vals)
            nb = int(n * BOT_PCT)
            nt = int(n * (1 - TOP_PCT))
            bot = sorted_vals.iloc[:nb].index
            top = sorted_vals.iloc[nt:].index
            tr = [x for x in (month_rets[ym].get(c) for c in top) if x is not None]
            br = [x for x in (month_rets[ym].get(c) for c in bot) if x is not None]
            if not tr or not br:
                continue
            fr[ym] = float(np.mean(tr) - np.mean(br))
        factor_ret[fid] = fr
        del fdf; gc.collect()
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    json.dump(factor_ret, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")
    all_rets = [v for fr in factor_ret.values() for v in fr.values()]
    if all_rets:
        arr = np.array(all_rets)
        log(f"全部多空收益: n={len(arr)}, mean={arr.mean():.4f}, t={arr.mean()/(arr.std()/np.sqrt(len(arr))):.2f}")
    db.close()


if __name__ == '__main__':
    main()
