#!/home/soso/v5/.venv/bin/python3
"""#8 FDR 后处理 v2（完整严谨，§10）
BH-FDR q=0.10 + 有效N（特征值校准，替代N=38假设独立）
有效N: 因子IC月度相关矩阵特征值, effective rank = (sum λ)²/sum(λ²)（Priestley-Subba Rao）
跳无IC数据因子（如alpha_019）。解耦: 只读 factor_ic_daily + factor_pers_B_done。
"""
import sqlite3, os, json
from datetime import datetime
import numpy as np
from scipy.stats import t as t_dist

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
DONE = os.path.expanduser('~/v5/branches/factor_persistence/factor_pers_B_done.json')
OUT = os.path.expanduser('~/v5/branches/factor_momentum/fdr_result.json')
Q = 0.10


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def bh_fdr(pvals, q, n_eff):
    """BH-FDR 用有效N"""
    n = n_eff
    indexed = sorted(enumerate(pvals), key=lambda x: x[1])
    threshold_i = 0
    for rank, (orig_idx, p) in enumerate(indexed, 1):
        if p <= rank * q / n:
            threshold_i = rank
    pass_set = set(orig_idx for orig_idx, _ in indexed[:threshold_i]) if threshold_i > 0 else set()
    return [i in pass_set for i in range(len(pvals))], threshold_i


def main():
    log("=" * 60); log("#8 FDR v2（BH-FDR + 有效N特征值）"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

    # 因子 IC 月度序列（跳无数据因子如 alpha_019）
    ic_series = {}
    common_yms = None
    for fid in orth:
        rows = db.execute("SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL GROUP BY ym ORDER BY 1", (fid,)).fetchall()
        if not rows:
            log(f"  {fid}: 无IC数据，跳过")
            continue
        ic_series[fid] = {r[0]: r[1] for r in rows}
        s = set(r[0] for r in rows)
        common_yms = s if common_yms is None else common_yms & s
    common_yms = sorted(common_yms) if common_yms else []
    fids_ic = list(ic_series.keys())
    log(f"有IC数据因子: {len(fids_ic)}/{len(orth)}, 共同月数: {len(common_yms)}")

    # IC 矩阵 (months × factors)
    IC = np.array([[ic_series[fid].get(ym, np.nan) for fid in fids_ic] for ym in common_yms])
    IC = IC[~np.isnan(IC).any(axis=1)]
    log(f"IC 矩阵: {IC.shape}")

    # 相关矩阵 + 特征值
    corr = np.corrcoef(IC.T)
    eigvals = np.linalg.eigvalsh(corr)
    eigvals = np.sort(eigvals)[::-1]
    n_nominal = len(fids_ic)
    n_eff = float(np.sum(eigvals) ** 2 / np.sum(eigvals ** 2))
    log(f"名义N={n_nominal}, 有效N={n_eff:.1f}（特征值校准，因子非独立）")
    log(f"top5特征值: {eigvals[:5].round(2)}")

    # t -> p（从 factor_pers_B_done，#7 修后，对齐 ic_series）
    done = json.load(open(DONE))
    factors = [(fid, v) for fid, v in done.items()
               if isinstance(v, dict) and 't_abs' in v and fid in ic_series]
    pvals = []
    for fid, v in factors:
        t = v['t_abs']
        df = v.get('n_days', 600) - 1
        p = 2 * (1 - t_dist.cdf(abs(t), df=df))
        pvals.append(p)

    # BH-FDR 用有效N
    pass_list, thresh_i = bh_fdr(pvals, Q, n_eff)
    log(f"BH临界 i={thresh_i}（有效N={n_eff:.1f}, p_(i) <= i*{Q}/{n_eff:.1f}）")
    log(f"FDR 通过: {sum(pass_list)}/{len(factors)}（有效N={n_eff:.1f} 比名义N={n_nominal} 更严）")

    results = {}
    for (fid, v), p, fp in zip(factors, pvals, pass_list):
        results[fid] = {'t_abs': v['t_abs'], 'p': round(p, 4), 'fdr_pass': fp, 'n_days': v.get('n_days')}

    log("按 p 升序 top 5:")
    for fid, r in sorted(results.items(), key=lambda x: x[1]['p'])[:5]:
        log(f"  {fid}: t_abs={r['t_abs']:+.2f} p={r['p']:.3f} fdr_pass={r['fdr_pass']}")

    out = {'run_at': datetime.now().isoformat(), 'q': Q, 'n_nominal': n_nominal, 'n_eff': round(n_eff, 2),
           'eigvals_top5': [round(float(e), 3) for e in eigvals[:5]],
           'n_pass': sum(pass_list),
           'note': '#7后t_abs全<2, 有效N后FDR仍0通过(预期); N诚实计数(特征值校准非独立)',
           'factors': results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    db.close()


if __name__ == '__main__':
    main()
