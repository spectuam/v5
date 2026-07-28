#!/home/soso/v5/.venv/bin/python3
"""#3 Decile 十分位分组诊断（完整严谨版，§6）
每月每因子按因子值分10组(D1=最高), 算每组市值加权T+20收益 + 单调性t(D1-D10 spread NW)
市值加权: amount代理(前20日均成交额,近似市值--无流通股本), get_weights封装未来替换
单调性: D1-D10 spread 序列 NW t (替代启发式分类的主判据)
"""
import sqlite3, os, json, gc, time
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/decile_result.json')
ALL_START, ALL_END = '2015-01-01', '2026-06-30'
HORIZON = 20
N_DECILE = 10


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(db, code, date_str, H):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def get_weights(db, code, date_str):
    """权重函数：前20日均成交额（代理流动性，近似市值--大市值股成交额大）
    未来流通股本可用时改此处：return close × circulating_shares（流通市值）
    """
    rows = db.execute("SELECT amount FROM daily_kline WHERE code=? AND date < ? AND amount>0 ORDER BY date DESC LIMIT 20",
                      (code, date_str + ' 23:59:59')).fetchall()
    if len(rows) < 10:
        return 0.0
    return float(np.mean([r[0] for r in rows]))


def newey_west_t(returns, max_lag=None, horizon=HORIZON):
    n = len(returns)
    if n < 10:
        return 0.0, 1.0
    if max_lag is None:
        max_lag = max(min(int(4 * (n / 100) ** (2 / 9)), n // 4), horizon - 1)  # #7: max(自动,19)
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


def classify(rets, t_mono, p_mono):
    """rets: [D1..D10] 市值加权收益; t_mono/p_mono: D1-D10 spread NW t/p"""
    if len(rets) < N_DECILE:
        return 'insufficient'
    d1, d10 = rets[0], rets[-1]
    best = int(np.argmax(rets))
    sig = p_mono < 0.05
    if best == 0 and d1 > d10 and sig:
        return 'd1_best'           # D1最好且单调显著
    if best in (1, 2) and rets[0] < rets[best]:
        return 'd1_collapse'       # D2/D3最好D1塌陷
    if max(rets[:3]) - min(rets[:3]) < 0.005:
        return 'd1_d3_flat'
    if best == N_DECILE - 1 and d10 > d1:
        return 'd10_best'
    return 'non_monotone'


def main():
    log("=" * 60); log("#3 Decile（市值加权amount代理+单调性t）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)}, N_DECILE={N_DECILE}, 加权=amount代理前20日均")
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]
    yms = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(date,1,7) ym FROM daily_kline WHERE date>=? AND date<=? ORDER BY 1",
        (ALL_START, ALL_END)).fetchall()]
    month_date = {ym: str(db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()[0])[:10] for ym in yms}
    log(f"月数: {len(month_date)}")

    # 预算月度全市场 T+20收益 + amount权重
    log("预算月度T+20收益 + amount权重...")
    month_rets = {}; month_wts = {}
    t0 = time.time()
    for i, (ym, ds) in enumerate(month_date.items()):
        rets = {}; wts = {}
        for code in codes:
            r = t_return(db, code, ds, HORIZON)
            w = get_weights(db, code, ds)
            if r is not None and w > 0:
                rets[code] = r; wts[code] = w
        month_rets[ym] = rets; month_wts[ym] = wts
        if (i + 1) % 24 == 0:
            log(f"  {i+1}/{len(month_date)} [{time.time()-t0:.0f}s]")

    # 38 因子 decile（市值加权）
    log("算38因子decile(市值加权)...")
    results = {}
    for i, fid in enumerate(orth):
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        decile_rets = defaultdict(list)
        spread_series = []
        for ym, ds in month_date.items():
            if ds not in fdf.index:
                continue
            day_vals = fdf.loc[ds].dropna()
            if len(day_vals) < N_DECILE * 10:
                continue
            sorted_vals = day_vals.sort_values(ascending=False)
            groups = np.array_split(sorted_vals.index, N_DECILE)
            d1_wret = None; d10_wret = None
            for gi, gidx in enumerate(groups):
                wr = [(month_rets[ym].get(c), month_wts[ym].get(c, 0)) for c in gidx]
                wr = [(r, w) for r, w in wr if r is not None and w > 0]
                if not wr:
                    continue
                wavg = sum(r * w for r, w in wr) / sum(w for r, w in wr)
                decile_rets[gi + 1].append(wavg)
                if gi == 0:
                    d1_wret = wavg
                if gi == N_DECILE - 1:
                    d10_wret = wavg
            if d1_wret is not None and d10_wret is not None:
                spread_series.append(d1_wret - d10_wret)
        avg = {d: float(np.mean(rs)) for d, rs in decile_rets.items() if rs}
        if len(avg) < N_DECILE:
            results[fid] = {'status': 'insufficient'}
            continue
        rets_list = [avg[d] for d in range(1, N_DECILE + 1)]
        t_mono, p_mono = newey_west_t(np.array(spread_series)) if spread_series else (0, 1.0)
        results[fid] = {
            'decile_avg': {str(k): round(v, 5) for k, v in avg.items()},
            'class': classify(rets_list, t_mono, p_mono),
            'd1_minus_d10': round(rets_list[0] - rets_list[-1], 5),
            'mono_t': round(t_mono, 2), 'mono_p': round(p_mono, 3),
        }
        del fdf; gc.collect()
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    classes = defaultdict(list)
    for fid, r in results.items():
        if 'class' in r:
            classes[r['class']].append(fid)
    log("=== 分类(市值加权+单调性t) ===")
    for c, facs in classes.items():
        log(f"  {c}: {len(facs)} -> {facs[:8]}")
    for fid in ['gtja191/alpha_016', 'alpha101/alpha_044', 'alpha101/alpha_015']:
        r = results.get(fid, {})
        log(f"  {fid}: class={r.get('class')} D1={r.get('decile_avg', {}).get('1')} D10={r.get('decile_avg', {}).get('10')} mono_t={r.get('mono_t')} p={r.get('mono_p')}")

    out = {'run_at': datetime.now().isoformat(), 'period': '2015-2026', 'n_decile': N_DECILE,
           'weighting': 'amount_proxy_20d_avg(近似市值,无流通股本,get_weights封装未来替换)',
           'factors': results, 'class_counts': {c: len(v) for c, v in classes.items()}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
