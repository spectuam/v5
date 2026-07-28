#!/home/soso/v5/.venv/bin/python3
"""#8 FDR 后处理脚本：BH-FDR q=0.10 多重检验校正（§10 第一接入点）
读 38 因子 #7 修后 t_abs -> 算 p -> BH-FDR -> 写 fdr_pass
解耦：只读 factor_pers_B_done.json，写新 fdr_result.json；不碰 daily_pick_v5.py 生产。
"""
import json, os
from datetime import datetime
from scipy.stats import t as t_dist

DONE = os.path.expanduser('~/v5/branches/factor_persistence/factor_pers_B_done.json')
OUT = os.path.expanduser('~/v5/branches/factor_momentum/fdr_result.json')
Q = 0.10  # FDR 阈值


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def bh_fdr(pvals, q):
    """BH-FDR: 返回每个 p 的 pass/fail + 临界 rank i"""
    n = len(pvals)
    indexed = sorted(enumerate(pvals), key=lambda x: x[1])  # 按 p 升序
    threshold_i = 0
    for rank, (orig_idx, p) in enumerate(indexed, 1):  # rank=1..n
        if p <= rank * q / n:
            threshold_i = rank
    pass_set = set(orig_idx for orig_idx, _ in indexed[:threshold_i]) if threshold_i > 0 else set()
    return [i in pass_set for i in range(n)], threshold_i


def main():
    log("=" * 60); log("#8 FDR 后处理（BH-FDR q=0.10）"); log("=" * 60)
    done = json.load(open(DONE))
    factors = [(fid, v) for fid, v in done.items() if isinstance(v, dict) and 't_abs' in v]
    log(f"因子数: {len(factors)}")

    pvals = []
    for fid, v in factors:
        t = v['t_abs']
        df = v.get('n_days', 600) - 1
        p = 2 * (1 - t_dist.cdf(abs(t), df=df))  # 双尾 p
        pvals.append(p)

    pass_list, thresh_i = bh_fdr(pvals, Q)
    log(f"BH 临界 i={thresh_i}（p_(i) <= i*{Q}/{len(factors)}）")
    log(f"FDR 通过: {sum(pass_list)}/{len(factors)}")

    results = {}
    for (fid, v), p, fp in zip(factors, pvals, pass_list):
        results[fid] = {'t_abs': v['t_abs'], 'p': round(p, 4), 'fdr_pass': fp, 'n_days': v.get('n_days')}

    log("按 p 升序 top 10:")
    for fid, r in sorted(results.items(), key=lambda x: x[1]['p'])[:10]:
        log(f"  {fid}: t_abs={r['t_abs']:+.2f} p={r['p']:.3f} fdr_pass={r['fdr_pass']}")

    out = {'run_at': datetime.now().isoformat(), 'q': Q, 'n': len(factors),
           'threshold_i': thresh_i, 'n_pass': sum(pass_list),
           'note': '#7 NW修复后 t_abs 全<2, 预期 FDR 0 通过; fdr_pass 字段就位待信号阳性接 daily_pick',
           'factors': results}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")


if __name__ == '__main__':
    main()
