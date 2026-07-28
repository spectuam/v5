#!/home/soso/v5/.venv/bin/python3
"""#11 2.5 PBO/DSR
PBO: CPCV 6份 C(6,3)=20组合, 3策略(k=1,3,5) train选最优, test排名, PBO=test末50%(rank>N/2)比例
DSR: Bailey-Lopez de Prado, N=3(实际独立,TSFM=CSFM等价), T=训练月数, SR_obs=k5样本内
注: 2.4不显著(p>0.05), 预期PBO高/DSR>0.95
"""
import sqlite3, os, json, math
from datetime import datetime
from collections import defaultdict
from itertools import combinations
import numpy as np
from scipy.stats import norm

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/pbo_dsr_result.json')
K_IC = 12
N_SPLITS = 6
KS = [1, 3, 5]
TRAIN_END = '2022-12'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(returns, freq=12):
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, float)
    if arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def main():
    log("=" * 60); log("#11 2.5 PBO/DSR"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    ic_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL GROUP BY ym ORDER BY 1", (fid,)).fetchall()
        for ym, ic in rows:
            ic_monthly[fid][ym] = ic
    ret_monthly = defaultdict(dict)
    for fid in orth:
        rows = db.execute("SELECT period, return FROM factor_map WHERE granularity='month' AND factor=?", (fid,)).fetchall()
        for ym, ret in rows:
            ret_monthly[fid][ym] = ret
    yms = sorted(set(ym for fid in ic_monthly for ym in ic_monthly[fid]))
    yms = [y for y in yms if '2016-01' <= y <= '2026-06']

    # 3 策略月收益序列
    strat_rets = {k: {} for k in KS}
    for i, ym in enumerate(yms):
        if i < K_IC:
            continue
        past = yms[i - K_IC:i]
        ic_vals = {}
        for fid in orth:
            vals = [ic_monthly[fid].get(py) for py in past]
            vals = [v for v in vals if v is not None]
            if vals:
                ic_vals[fid] = float(np.mean(vals))
        if not ic_vals:
            continue
        sorted_fids = sorted(ic_vals, key=lambda f: -ic_vals[f])
        for k in KS:
            active = sorted_fids[:k]
            rets = [ret_monthly[fid].get(ym) for fid in active]
            rets = [r for r in rets if r is not None]
            if rets:
                strat_rets[k][ym] = float(np.mean(rets))

    common_yms = sorted(set.intersection(*[set(strat_rets[k]) for k in KS]))
    log(f"共同月数: {len(common_yms)}")
    rets_arr = {k: np.array([strat_rets[k][y] for y in common_yms]) for k in KS}
    n = len(common_yms)

    # PBO CPCV
    splits = np.array_split(np.arange(n), N_SPLITS)
    combos = list(combinations(range(N_SPLITS), N_SPLITS // 2))
    log(f"CPCV: {N_SPLITS}份, {len(combos)}组合 (train/test各3份)")
    test_ranks = []
    for train_split in combos:
        test_split = tuple(i for i in range(N_SPLITS) if i not in train_split)
        train_idx = np.concatenate([splits[i] for i in train_split])
        test_idx = np.concatenate([splits[i] for i in test_split])
        train_sh = {k: sharpe(rets_arr[k][train_idx]) for k in KS}
        best_k = max(train_sh, key=train_sh.get)
        test_sh = {k: sharpe(rets_arr[k][test_idx]) for k in KS}
        sorted_k = sorted(test_sh, key=test_sh.get, reverse=True)
        rank = sorted_k.index(best_k) + 1
        test_ranks.append(rank)
    pbo = float(np.mean([r > len(KS) / 2 for r in test_ranks]))
    log(f"PBO = {pbo:.3f} (test排名末50%比例, <0.5好)")
    rank_dist = {int(r): int(c) for r, c in zip(*np.unique(test_ranks, return_counts=True))}
    log(f"test排名分布: {rank_dist}")

    # DSR (Bailey-Lopez de Prado)
    train_idx_full = [i for i, y in enumerate(common_yms) if y <= TRAIN_END]
    r5 = rets_arr[5][train_idx_full]
    SR_obs = sharpe(r5)  # 年化
    T = len(train_idx_full)
    N = len(KS)  # 3 实际独立
    SR_monthly = SR_obs / np.sqrt(12)
    mu, sd = float(r5.mean()), float(r5.std())
    if sd > 0:
        z = (r5 - mu) / sd
        skew = float(np.mean(z ** 3))
        kurt = float(np.mean(z ** 4))
    else:
        skew, kurt = 0.0, 3.0
    var_sr = (1 - skew * SR_monthly + (kurt - 1) / 4 * SR_monthly ** 2) / (T - 1)
    sigma_sr = float(np.sqrt(var_sr)) if var_sr > 0 else 0.0
    E_max = sigma_sr * (2 * np.log(N) - np.log(np.log(N))) if N > 1 and np.log(N) > 0 else 0.0
    dsr = float(norm.cdf((SR_monthly - E_max) / sigma_sr)) if sigma_sr > 0 else 0.5
    log(f"DSR = {dsr:.3f} (N={N}, T={T}, SR年化{SR_obs:.3f}/月{SR_monthly:.4f}, E[max]{E_max:.4f}, σ{sigma_sr:.4f}, skew{skew:.3f}, kurt{kurt:.3f})")

    verdict_pbo = '通过(<0.5)' if pbo < 0.5 else '不通过(过拟合)'
    verdict_dsr = '通过(<0.95)' if dsr < 0.95 else '不通过(>0.95)'
    log(f"判定: PBO {verdict_pbo}, DSR {verdict_dsr}")

    out = {'run_at': datetime.now().isoformat(), 'n_splits': N_SPLITS, 'n_combos': len(combos),
           'pbo': round(pbo, 4), 'pbo_pass': pbo < 0.5, 'test_ranks': test_ranks, 'rank_dist': rank_dist,
           'dsr': round(dsr, 4), 'dsr_pass': dsr < 0.95, 'N': N, 'T': T,
           'SR_obs': round(SR_obs, 4), 'E_max': round(E_max, 4), 'sigma_sr': round(sigma_sr, 4),
           'skew': round(skew, 3), 'kurt': round(kurt, 3)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
