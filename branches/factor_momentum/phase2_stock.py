#!/home/soso/v5/.venv/bin/python3
"""#11 2.2 选股级回测 v2（完整严谨，替代因子级）
TSFM+CSFM×k∈{1,3,5}=6策略, 选股级: 放行因子的Top10股票合并去重等权
训练2016-2022选样本内夏普最高, OOS 2023-2026
数据: factor_ic_daily(IC) + factor pkl(因子值Top10) + daily_kline(T20收益)
解耦: 只读三表。phase2.py 因子级保留对比。
"""
import sqlite3, os, json, gc, time
from datetime import datetime
from collections import defaultdict
import numpy as np
import pandas as pd

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
PKL_DIR = os.path.expanduser('~/ading/cache/t3a_factors')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/phase2_stock_result.json')
K = 12
TOP_STOCK = 10
TRAIN_END = '2022-12'
HORIZON = 20


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def t_return(db, code, date_str, H=HORIZON):
    rows = db.execute("SELECT close FROM daily_kline WHERE code=? AND date > ? AND close>0 ORDER BY date LIMIT ?",
                      (code, date_str + ' 23:59:59', H)).fetchall()
    buy = db.execute("SELECT close FROM daily_kline WHERE code=? AND date LIKE ?", (code, date_str + '%')).fetchone()
    if not buy or buy[0] <= 0 or len(rows) < H:
        return None
    return rows[-1][0] / buy[0] - 1


def sharpe(returns, freq=12):
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    if arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def main():
    log("=" * 60); log("#11 2.2 选股级回测v2(TSFM+CSFM×k=6,Top10合并去重)"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池:{len(orth)}, K={K}, 每因子Top{TOP_STOCK}")
    db = sqlite3.connect(DB)
    codes = [r[0] for r in db.execute(
        "SELECT s.symbol FROM stock_info s WHERE s.class='stock' AND s.name NOT LIKE '%ST%' AND s.symbol NOT LIKE 'bj%'").fetchall()]

    # IC月度
    ic_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL GROUP BY ym ORDER BY 1", (fid,)).fetchall()
        for ym, ic in rows:
            ic_monthly[fid][ym] = ic
    yms = sorted(set(ym for fid in ic_monthly for ym in ic_monthly[fid]))
    yms = [y for y in yms if '2016-01' <= y <= '2026-06']
    month_date = {ym: str(db.execute("SELECT MIN(date) FROM daily_kline WHERE date LIKE ?", (ym + '%',)).fetchone()[0])[:10] for ym in yms}
    log(f"月数:{len(month_date)}")

    # 月度预算全市场T+20收益
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
        if (i + 1) % 24 == 0:
            log(f"  {i+1}/{len(month_date)} [{time.time()-t0:.0f}s]")

    # 38因子每月Top10(从pkl)
    log("读38因子pkl,算每月Top10...")
    factor_top10 = {}
    for i, fid in enumerate(orth):
        fn = fid.replace('/', '_', 1) + '.pkl'
        path = os.path.join(PKL_DIR, fn)
        if not os.path.exists(path):
            continue
        fdf = pd.read_pickle(path)
        fdf.index = fdf.index.astype(str).str[:10]
        factor_top10[fid] = {}
        for ym, ds in month_date.items():
            if ds not in fdf.index:
                continue
            day_vals = fdf.loc[ds].dropna()
            if len(day_vals) < TOP_STOCK:
                continue
            factor_top10[fid][ym] = set(day_vals.nlargest(TOP_STOCK).index)
        del fdf; gc.collect()
        if (i + 1) % 5 == 0:
            log(f"  {i+1}/{len(orth)} done")

    # 6策略选股级回测
    strategies = [('TSFM', k) for k in [1, 3, 5]] + [('CSFM', k) for k in [1, 3, 5]]
    results = {}
    for name, k in strategies:
        train_rets = []; oos_rets = []
        for i, ym in enumerate(yms):
            if i < K:
                continue
            past = yms[i - K:i]
            ic_vals = {}
            for fid in orth:
                vals = [ic_monthly[fid].get(py) for py in past]
                vals = [v for v in vals if v is not None]
                if vals:
                    ic_vals[fid] = float(np.mean(vals))
            if not ic_vals:
                continue
            sorted_fids = sorted(ic_vals, key=lambda f: -ic_vals[f])
            if name == 'TSFM':
                pos = [f for f in sorted_fids if ic_vals[f] > 0]
                active = pos[:k]
            else:
                active = sorted_fids[:k]
            if not active:
                continue
            # 合并Top10去重
            stocks = set()
            for fid in active:
                stocks |= factor_top10.get(fid, {}).get(ym, set())
            if not stocks:
                continue
            rets = [month_rets[ym].get(s) for s in stocks]
            rets = [r for r in rets if r is not None]
            if not rets:
                continue
            port = float(np.mean(rets))
            if ym <= TRAIN_END:
                train_rets.append(port)
            else:
                oos_rets.append(port)
        tr_sh = sharpe(train_rets); oos_sh = sharpe(oos_rets)
        tr_mean = float(np.mean(train_rets)) if train_rets else 0
        oos_mean = float(np.mean(oos_rets)) if oos_rets else 0
        results[f"{name}_k{k}"] = {'train_sharpe': round(tr_sh, 3), 'oos_sharpe': round(oos_sh, 3),
                                   'train_n': len(train_rets), 'oos_n': len(oos_rets),
                                   'train_annual': round(tr_mean * 12, 4), 'oos_annual': round(oos_mean * 12, 4)}
        log(f"  {name}_k{k}: 训练夏普{tr_sh:.3f}(年化{tr_mean*12:.2%}) OOS夏普{oos_sh:.3f}(年化{oos_mean*12:.2%})")

    best = max(results, key=lambda kk: results[kk]['train_sharpe']) if results else None
    if best:
        log(f"样本内最高:{best}(训练{results[best]['train_sharpe']},OOS{results[best]['oos_sharpe']})")
    log("对标Ma2024:TSFM 9.91%/t=6.07,CSFM 7.02%/t=3.44/夏普0.80")

    out = {'run_at': datetime.now().isoformat(), 'K': K, 'top_stock': TOP_STOCK,
           'level': '选股级(Top10合并去重等权)', 'train': '2016-2022', 'oos': '2023-2026',
           'strategies': results, 'best': best}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")
    db.close()


if __name__ == '__main__':
    main()
