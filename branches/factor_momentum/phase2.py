#!/home/soso/v5/.venv/bin/python3
"""#11 因子动量阶段二：TSFM + CSFM × k∈{1,3,5} = 6 策略
预登记 N=6（登记簿）。训练 2016-2022 选样本内夏普最高，OOS 2023-2026。
TSFM_k: 过去K=12期IC均值>0的因子取前k(按IC降序)
CSFM_k: 过去K=12期IC均值前k个(不论正负)
组合收益 = 放行因子当月factor_map ret均值(因子等权)
数据：factor_ic_daily(IC月均) + factor_map(月ret)。解耦只读。
"""
import sqlite3, os, json
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/phase2_result.json')
K = 12
TRAIN_END = '2022-12'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(returns, freq=12):
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    if arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def main():
    log("=" * 60); log("#11 因子动量阶段二（TSFM+CSFM×k=6策略）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    log(f"正交池: {len(orth)} 因子, K={K}")
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

    # 月均 IC
    ic_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("""SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily
            WHERE factor_id=? AND T20_IC IS NOT NULL GROUP BY ym ORDER BY 1""", (fid,)).fetchall()
        for ym, ic in rows:
            ic_monthly[fid][ym] = ic

    # 月 ret（factor_map）
    ret_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT period, return FROM factor_map WHERE granularity='month' AND factor=?", (fid,)).fetchall()
        for ym, ret in rows:
            ret_monthly[fid][ym] = ret

    yms = sorted(set(ym for fid in ic_monthly for ym in ic_monthly[fid]))
    yms = [y for y in yms if y >= '2016-01' and y <= '2026-06']
    log(f"月数: {len(yms)} ({yms[0]}~{yms[-1]})")

    strategies = [('TSFM', k) for k in [1, 3, 5]] + [('CSFM', k) for k in [1, 3, 5]]
    results = {}
    for name, k in strategies:
        train_rets = []; oos_rets = []
        for i, ym in enumerate(yms):
            if i < K:
                continue
            past_yms = yms[i - K:i]
            ic_vals = {}
            for fid in orth:
                vals = [ic_monthly[fid].get(py) for py in past_yms]
                vals = [v for v in vals if v is not None]
                if vals:
                    ic_vals[fid] = float(np.mean(vals))
            if not ic_vals:
                continue
            sorted_fids = sorted(ic_vals, key=lambda f: -ic_vals[f])
            if name == 'TSFM':
                pos = [f for f in sorted_fids if ic_vals[f] > 0]
                active = pos[:k]
            else:  # CSFM
                active = sorted_fids[:k]
            if not active:
                continue
            rets = [ret_monthly[fid].get(ym) for fid in active]
            rets = [r for r in rets if r is not None]
            if not rets:
                continue
            port_ret = float(np.mean(rets))
            if ym <= TRAIN_END:
                train_rets.append(port_ret)
            else:
                oos_rets.append(port_ret)
        tr_sh = sharpe(train_rets); oos_sh = sharpe(oos_rets)
        tr_mean = float(np.mean(train_rets)) if train_rets else 0
        oos_mean = float(np.mean(oos_rets)) if oos_rets else 0
        results[f"{name}_k{k}"] = {
            'train_sharpe': round(tr_sh, 3), 'oos_sharpe': round(oos_sh, 3),
            'train_n': len(train_rets), 'oos_n': len(oos_rets),
            'train_mean': round(tr_mean, 5), 'oos_mean': round(oos_mean, 5),
            'train_annual': round(tr_mean * 12, 4), 'oos_annual': round(oos_mean * 12, 4),
        }
        log(f"  {name}_k{k}: 训练夏普={tr_sh:.3f}(n={len(train_rets)},年化{tr_mean*12:.2%}) OOS夏普={oos_sh:.3f}(n={len(oos_rets)},年化{oos_mean*12:.2%})")

    best = max(results, key=lambda kk: results[kk]['train_sharpe']) if results else None
    if best:
        log(f"样本内夏普最高: {best} (训练{results[best]['train_sharpe']}, OOS{results[best]['oos_sharpe']})")
    log("对标 Ma 2024: TSFM 9.91%/t=6.07, CSFM 7.02%/t=3.44/夏普0.80")

    out = {'run_at': datetime.now().isoformat(), 'K': K, 'train': '2016-2022', 'oos': '2023-2026',
           'strategies': results, 'best': best}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
