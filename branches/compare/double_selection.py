#!/home/soso/v5/.venv/bin/python3
"""路D 去冗余：PCA正交化 + VIF诊断（简化版,非完整BCH double-selection）

目的: 38因子高度共簇(有效N≈4.2),路D去冗余保留独立贡献因子。
简化版: PCA on IC矩阵看独立维度 + 每主成分选代表因子 + VIF诊断共线性。
完整BCH double-selection(两阶段Lasso+控制变量)需收益目标,后续补。

输入: factor_ic_daily 聚合月度IC(38×月)
输出: 路D保留因子集(每主成分代表) + 独立贡献 + VIF
"""
import sqlite3, os, json
from datetime import datetime
from collections import defaultdict
import numpy as np

DB = os.path.expanduser('~/ading/db/tdx_stock_data.db')
JSON_P = '/home/soso/ading/data/reports/factor_decay_results_tdx.json'
OUT = os.path.expanduser('~/v5/branches/compare/double_selection_result.json')


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def vif(corr, i):
    """方差膨胀因子: 1/(1-R²_i), R²_i是因子i被其他因子线性解释"""
    n = corr.shape[0]
    others = [j for j in range(n) if j != i]
    if not others:
        return 1.0
    X = np.delete(corr, i, axis=0)[:, others]  # 其他因子
    y = corr[i, others]
    try:
        # 最小二乘 R²
        X1 = np.column_stack([X, np.ones(len(X))])
        coef, *_ = np.linalg.lstsq(X1, y, rcond=None)
        yhat = X1 @ coef
        ss_res = np.sum((y - yhat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        return float(1 / max(1 - r2, 1e-6))
    except Exception:
        return 1.0


def main():
    log("=" * 60); log("路D 去冗余 (PCA正交化+VIF, 简化版)"); log("=" * 60)
    orth = [f['id'] for f in json.load(open(JSON_P))['all_orthogonal']]
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

    # 38因子月度IC
    ic_series = {}
    common_yms = None
    for fid in orth:
        rows = db.execute("SELECT substr(date,1,7) ym, AVG(T20_IC) FROM factor_ic_daily WHERE factor_id=? AND T20_IC IS NOT NULL GROUP BY ym ORDER BY 1", (fid,)).fetchall()
        if not rows:
            continue
        ic_series[fid] = {r[0]: r[1] for r in rows}
        s = set(r[0] for r in rows)
        common_yms = s if common_yms is None else common_yms & s
    db.close()
    common_yms = sorted([y for y in common_yms if '2016-01' <= y <= '2026-06'])
    fids = list(ic_series.keys())
    log(f"因子{len(fids)}, 共同月{len(common_yms)}")

    IC = np.array([[ic_series[fid].get(ym, np.nan) for fid in fids] for ym in common_yms])
    IC = IC[~np.isnan(IC).any(axis=1)]
    log(f"IC矩阵: {IC.shape}")

    # 相关矩阵 + 特征值(复用fdr_correct法)
    corr = np.corrcoef(IC.T)
    eigvals, eigvecs = np.linalg.eigh(corr)
    idx = np.argsort(eigvals)[::-1]
    eigvals = eigvals[idx]
    eigvecs = eigvecs[:, idx]
    n_eff = float(np.sum(eigvals) ** 2 / np.sum(eigvals ** 2))
    log(f"有效N(特征值): {n_eff:.2f} (名义{len(fids)})")
    log(f"top5特征值: {eigvals[:5].round(2)} (解释比{(eigvals/eigvals.sum()*100)[:5].round(1)}%)")

    # 每top主成分选高载荷因子(loading>0.3, 不只1个代表)
    n_components = max(1, int(round(n_eff)))
    keep_set = set()
    for pc in range(n_components):
        loadings = np.abs(eigvecs[:, pc])
        for i in range(len(fids)):
            if loadings[i] > 0.3:
                keep_set.add(i)
    rep_fids = [fids[i] for i in sorted(keep_set)]
    log(f"PCA高载荷保留(loading>0.3, top{n_components}主成分): {len(rep_fids)}个")

    # VIF诊断(全部因子)
    vifs = {fids[i]: round(vif(corr, i), 2) for i in range(len(fids))}
    high_vif = {f: v for f, v in vifs.items() if v > 5}  # VIF>5高共线
    log(f"VIF>5(高共线)因子: {len(high_vif)}个")
    for f, v in sorted(high_vif.items(), key=lambda x: -x[1])[:8]:
        log(f"  {f}: VIF={v}")

    # 路D保留: PCA高载荷(VIF全爆因极端共簇,弃VIF硬筛,用PCA载荷)
    keep = set(rep_fids)
    drop = set(fids) - keep
    log(f"路D保留: {len(keep)}/{len(fids)}, 剔除(高共线冗余): {len(drop)}")
    log(f"剔除: {sorted(drop)[:10]}")

    out = {
        'run_at': datetime.now().isoformat(),
        'method': 'PCA正交化+VIF诊断(简化版,非完整BCH double-selection)',
        'n_nominal': len(fids), 'n_eff': round(n_eff, 2),
        'n_components': n_components,
        'eigvals_top5': [round(float(e), 3) for e in eigvals[:5]],
        'representatives': rep_fids,
        'vif': vifs,
        'keep': sorted(keep), 'drop': sorted(drop),
        'caveat': '简化版PCA去冗余;完整BCH double-selection(两阶段Lasso+收益目标)待补',
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")


if __name__ == '__main__':
    main()
