#!/home/soso/v5/.venv/bin/python3
"""#4 多头端 IC 诊断 v2（完整严谨，§7）
top N 扫描(30/50/100) + 多头端 IC 的 NW t(max_lag=max(自动,19))
诊断模式,看预测力是否在头部(做多拿得到)
解耦: 只读 factor pkl + daily_kline + factor_ic_daily。
"""
import sqlite3, os, json, gc, time, math
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, t as t_dist
from scipy import stats as scipy_stats

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/long_ic_result.json')
ALL_START, ALL_END = '2015-01-01', '2026-06-30'
TRAIN_END = '2022-12-31'
TOPNS = [30, 50, 100]
HORIZON = 20
IC_STRONG = 0.02


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(db, code, date_str, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def newey_west_t(returns, max_lag=None, horizon=HORIZON):
    n = len(returns)
    if n < 10:
        return 0.0, 1.0
    if max_lag is None:
        max_lag = max(min(int(4 * (n / 100) ** (2 / 9)), n // 4), horizon - 1)
    mean = np.mean(returns)
    gamma0 = np.var(returns, ddof=0)
    nw_var = gamma0
    for k in range(1, max_lag + 1):
        if n - k > 0:
            nw_var += 2 * np.mean((returns[:-k] - mean) * (returns[k:] - mean))
    nw_se = np.sqrt(nw_var / n) if nw_var > 0 else 0
    if nw_se == 0:
        return 0.0, 1.0
    t_nw = mean / nw_se
    p_val = 2 * (1 - scipy_stats.t.cdf(abs(t_nw), df=max(1, n // 4)))
    return float(t_nw), float(p_val)


def classify(full_ic, long_ic):
    if full_ic > IC_STRONG and long_ic > IC_STRONG:
        return 'head_strong'
    if full_ic > IC_STRONG and long_ic <= IC_STRONG:
        return 'tail_concentrated'
    if full_ic <= IC_STRONG and long_ic > IC_STRONG:
        return 'long_only_strong'
    return 'weak'


def main():
    log("=" * 60); log("#4 多头端 IC v2（top N 扫描 + NW t）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)}, TOPNS={TOPNS}")
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    yms = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(date,1,7) ym FROM daily_kline WHERE date>=? AND date<=? ORDER BY 1",
        (ALL_START, ALL_END)).fetchall()]
    month_date = {ym: str(db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()[0])[:10] for ym in yms}
    log(f"月数: {len(month_date)}")

    # 预算月度全市场 T+20 收益
    log("预算月度全市场 T+20 收益...")
    month_rets = {}
    t0 = time.time()
    for i, (ym, ds) in enumerate(month_date.items()):
        rets = {}
        for code in codes:
            r = t_return(db, code, ds, HORIZON)
            if r is not None:
                rets[code] = r
        month_rets[ym] = rets
        if (i + 1) % 24 == 0:
            log(f"  {i+1}/{len(month_date)} [{time.time()-t0:.0f}s]")

    # 全截面 IC
    full_ic_monthly = {}
    for fid in orth:
        rows = db.execute("""SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily
            WHERE factor_id=? AND date>=? AND date<=? AND T20_IC IS NOT NULL GROUP BY ym""", (fid, ALL_START, ALL_END)).fetchall()
        full_ic_monthly[fid] = {r[0]: r[1] for r in rows}

    # 38 因子 top N 多头端 IC（扫描 30/50/100）
    results = {}
    for i, fid in enumerate(orth):
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        # 每 N 算月度 IC 序列
        long_ic_by_n = {n: {} for n in TOPNS}
        for ym, ds in month_date.items():
            if ds not in fdf.index:
                continue
            day_vals = fdf.loc[ds].dropna()
            for n in TOPNS:
                if len(day_vals) < n:
                    continue
                top = day_vals.nlargest(n)
                common = [c for c in top.index if c in month_rets.get(ym, {})]
                if len(common) < 10:
                    continue
                ic, _ = spearmanr(top[common].values, [month_rets[ym][c] for c in common])
                if not np.isnan(ic):
                    long_ic_by_n[n][ym] = float(ic)
        del fdf; gc.collect()

        # 全截面 IC 训练段
        fi_train = [v for ym, v in full_ic_monthly.get(fid, {}).items() if ym <= '2022-12']
        full_train = float(np.mean(fi_train)) if fi_train else 0
        # 每 N NW t（训练段 IC 序列）
        per_n = {}
        for n in TOPNS:
            li_train = [v for ym, v in long_ic_by_n[n].items() if ym <= '2022-12']
            if not li_train:
                per_n[n] = {'long_ic': None, 't': None, 'p': None}
                continue
            long_train = float(np.mean(li_train))
            t_nw, p_nw = newey_west_t(np.array(li_train))
            per_n[n] = {'long_ic': round(long_train, 4), 't': round(t_nw, 2), 'p': round(p_nw, 3),
                        'class': classify(full_train, long_train), 'n_months': len(li_train)}
        results[fid] = {'full_ic_train': round(full_train, 4), 'by_topn': per_n}
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    # 汇总（top50 为主，对比 30/100 敏感性）
    log("=" * 60); log("RESULT (训练段 2015-2022)"); log("=" * 60)
    for n in TOPNS:
        classes = defaultdict(list)
        for fid, r in results.items():
            if n in r.get('by_topn', {}):
                classes[r['by_topn'][n].get('class', 'weak')].append(fid)
        log(f"top{n}: " + " / ".join(f"{c}={len(v)}" for c, v in classes.items()))
    for fid in ['gtja191/alpha_016', 'alpha101/alpha_044', 'alpha101/alpha_015']:
        r = results.get(fid, {})
        log(f"  {fid}: full={r.get('full_ic_train')} | " + " | ".join(f"top{n}={r.get('by_topn',{}).get(n,{}).get('long_ic')}(t={r.get('by_topn',{}).get(n,{}).get('t')},{r.get('by_topn',{}).get(n,{}).get('class')})" for n in TOPNS))

    out = {'run_at': datetime.now().isoformat(), 'topns': TOPNS, 'train': '2015-2022', 'ic_strong': IC_STRONG,
           'factors': results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
