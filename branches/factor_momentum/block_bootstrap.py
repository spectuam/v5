#!/home/soso/v5/.venv/bin/python3
"""#11 2.4 block bootstrap 显著性
k5 策略月收益 block bootstrap 均值 p 值（H0: 均值=0，双侧）
block=6, n_boot=5000。训练/OOS/全段。
"""
import sqlite3, os, json
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/factor_momentum/block_bootstrap_result.json')
K_IC = 12
K_FACTOR = 5
BLOCK = 6
N_BOOT = 5000
TRAIN_END = '2022-12'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def block_bootstrap_p(series, block=BLOCK, n_boot=N_BOOT, seed=42):
    """H0: 均值=0, 返回 (p, obs_mean) 双侧"""
    rng = np.random.default_rng(seed)
    s = np.asarray(series, float)
    n = len(s)
    if n < 2:
        return 1.0, 0.0
    obs_mean = float(np.mean(s))
    centered = s - obs_mean  # H0: 均值=0，center
    boots = np.empty(n_boot)
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            st = rng.integers(0, max(1, n - block + 1))
            idx.extend(range(st, min(st + block, n)))
        boots[b] = np.mean(centered[idx[:n]])
    p = 2 * min(float((boots >= obs_mean).mean()), float((boots <= obs_mean).mean()))
    return min(p, 1.0), obs_mean


def main():
    log("=" * 60); log("#11 2.4 block bootstrap 显著性 (k5)"); log("=" * 60)
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

    train_rets = []; oos_rets = []; all_rets = []
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
        active = sorted_fids[:K_FACTOR]
        rets = [ret_monthly[fid].get(ym) for fid in active]
        rets = [r for r in rets if r is not None]
        if not rets:
            continue
        r = float(np.mean(rets))
        all_rets.append(r)
        if ym <= TRAIN_END:
            train_rets.append(r)
        else:
            oos_rets.append(r)

    log(f"训练 n={len(train_rets)}, OOS n={len(oos_rets)}, 全段 n={len(all_rets)}")
    p_tr, m_tr = block_bootstrap_p(train_rets)
    p_oos, m_oos = block_bootstrap_p(oos_rets)
    p_all, m_all = block_bootstrap_p(all_rets)
    log(f"训练: 均值{m_tr:.5f} p={p_tr:.3f} {'显著' if p_tr < 0.05 else '不显著'}")
    log(f"OOS:  均值{m_oos:.5f} p={p_oos:.3f} {'显著' if p_oos < 0.05 else '不显著'}")
    log(f"全段: 均值{m_all:.5f} p={p_all:.3f} {'显著' if p_all < 0.05 else '不显著'}")

    out = {'run_at': datetime.now().isoformat(), 'block': BLOCK, 'n_boot': N_BOOT,
           'train': {'mean': m_tr, 'p': p_tr, 'n': len(train_rets), 'sig': p_tr < 0.05},
           'oos': {'mean': m_oos, 'p': p_oos, 'n': len(oos_rets), 'sig': p_oos < 0.05},
           'all': {'mean': m_all, 'p': p_all, 'n': len(all_rets), 'sig': p_all < 0.05}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
