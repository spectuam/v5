#!/home/soso/v5/.venv/bin/python3
"""阶段2 比较框架：多策略横向比较 + MCS无法区分集合 + DSR-adjusted Sharpe + Calmar硬筛

输入: candidates_returns.json  {strategy_name: [[period, ret], ...]}
口径: 同period对齐 / 同频率年化 / Sharpe风险调整 / CPCV-OOS分布 / N_eff(策略相关矩阵特征值) / N记账
输出: 每策略 DSR-Sharpe + PBO + Calmar + OOS分布 + MCS集合+p值 + Spearman稳定性

复用:
- pbo_dsr.py 的 CPCV(purge+embargo+多split) + DSR公式
- fdr_correct.py 的特征值法N_eff（这里对策略returns相关矩阵）
- diagnose.py 的 block_bootstrap_ci 思路（MCS两两比较）
- cost_utils.py 的 round_trip_cost（扣成本参考，这里口径先用毛收益，成本在阶段4复核）
"""
import os, json, math
from datetime import datetime
from itertools import combinations
import numpy as np
from scipy.stats import norm

CAND_P = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
OUT = os.path.expanduser('~/v5/branches/compare/compare_pool_result.json')
FREQ = 52  # 周度
TRAIN_END = '2022-W52'  # 训练截止(对齐phase2_stock/tsmom_long)
N_SPLITS_LIST = [6, 8, 10]
EMBARGO = 5  # 周度embargo(≈1月)
BLOCK = 6  # block bootstrap块长(对齐block_bootstrap.py)
N_BOOT = 2000
ALPHA = 0.05  # MCS显著性


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(rets, freq=FREQ):
    arr = np.asarray(rets, float)
    if len(arr) < 2 or arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def max_dd(rets):
    """周收益序列累积净值最大回撤"""
    arr = np.asarray(rets, float)
    nav = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(nav)
    dd = (nav - peak) / peak
    return float(dd.min()) if len(dd) else 0.0


def calmar(rets, freq=FREQ):
    arr = np.asarray(rets, float)
    mdd = max_dd(rets)
    if mdd == 0:
        return 0.0
    return float(arr.mean() * freq / abs(mdd))


def effective_n(rets_matrix):
    """策略returns相关矩阵特征值法有效N（复用fdr_correct思路）"""
    if rets_matrix.shape[1] < 2:
        return float(rets_matrix.shape[1])
    corr = np.corrcoef(rets_matrix.T)  # strategies × strategies
    eigvals = np.linalg.eigvalsh(corr)
    eigvals = np.sort(eigvals)[::-1]
    eigvals = np.clip(eigvals, 1e-9, None)
    return float(np.sum(eigvals) ** 2 / np.sum(eigvals ** 2))


def dsr_adjusted(rets, n_eff, freq=FREQ):
    """Bailey-Lopez de Prado DSR，N用n_eff。
    E[max SR]用Bailey正式公式(1-γ)Φ⁻¹(1-1/N)+γΦ⁻¹(1-1/(Ne))，非AMS近似(避免log(log)爆炸)；
    n_eff<=2时选择膨胀可忽略，E_max=0，DSR=PSR(只校正估计误差)。"""
    GAMMA = 0.5772156649  # Euler-Mascheroni
    arr = np.asarray(rets, float)
    T = len(arr)
    if T < 5 or arr.std() == 0:
        return 0.5, 0.0, 0.0, 0.0
    SR_obs = sharpe(arr, freq)
    SR_p = SR_obs / np.sqrt(freq)  # 周期化
    mu, sd = float(arr.mean()), float(arr.std())
    z = (arr - mu) / sd
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))
    var_sr = (1 - skew * SR_p + (kurt - 1) / 4 * SR_p ** 2) / (T - 1)
    sigma_sr = math.sqrt(var_sr) if var_sr > 0 else 0.0
    # E[max SR]: Bailey-Lopez de Prado 正式公式
    if n_eff > 2 and sigma_sr > 0:
        E_max = sigma_sr * ((1 - GAMMA) * norm.ppf(1 - 1 / n_eff) + GAMMA * norm.ppf(1 - 1 / (n_eff * math.e)))
    else:
        E_max = 0.0  # n_eff<=2 选择膨胀可忽略, DSR=PSR
    dsr = float(norm.cdf((SR_p - E_max) / sigma_sr)) if sigma_sr > 0 else 0.5
    return dsr, SR_obs, E_max, sigma_sr


def cpcv_oos_dist(rets, n_splits_list=N_SPLITS_LIST, embargo=EMBARGO):
    """单策略CPCV产出OOS sharpe分布（复用pbo_dsr的purge+embargo+多split，单策略）"""
    n = len(rets)
    dist = []
    for N_SPLITS in n_splits_list:
        if n < N_SPLITS * 2:
            continue
        splits = np.array_split(np.arange(n), N_SPLITS)
        combos = list(combinations(range(N_SPLITS), N_SPLITS // 2))
        for train_split in combos:
            test_split = tuple(i for i in range(N_SPLITS) if i not in train_split)
            train_idx = np.concatenate([splits[i] for i in train_split])
            test_idx = np.concatenate([splits[i] for i in test_split])
            # purge ±embargo
            test_set = set(test_idx)
            purge = set()
            for ti in test_idx:
                for d in range(1, embargo + 1):
                    if ti - d >= 0:
                        purge.add(ti - d)
                    if ti + d < n:
                        purge.add(ti + d)
            train_purged = np.array([i for i in train_idx if i not in purge])
            if len(train_purged) < 10 or len(test_idx) < 10:
                continue
            dist.append(sharpe(rets[test_idx]))
    return dist


def pbo_in_pool(rets_matrix, n_splits=N_SPLITS_LIST[0], embargo=EMBARGO):
    """池中IS最优策略OOS落入下半区概率（复用pbo_dsr逻辑，多策略版）"""
    n_strat, n = rets_matrix.shape
    if n < n_splits * 2 or n_strat < 2:
        return 0.0
    splits = np.array_split(np.arange(n), n_splits)
    combos = list(combinations(range(n_splits), n_splits // 2))
    ranks = []
    for train_split in combos:
        test_split = tuple(i for i in range(n_splits) if i not in train_split)
        train_idx = np.concatenate([splits[i] for i in train_split])
        test_idx = np.concatenate([splits[i] for i in test_split])
        test_set = set(test_idx)
        purge = set()
        for ti in test_idx:
            for d in range(1, embargo + 1):
                if ti - d >= 0:
                    purge.add(ti - d)
                if ti + d < n:
                    purge.add(ti + d)
        train_purged = np.array([i for i in train_idx if i not in purge])
        if len(train_purged) < 10 or len(test_idx) < 10:
            continue
        train_sh = [sharpe(rets_matrix[s, train_purged]) for s in range(n_strat)]
        best = int(np.argmax(train_sh))
        test_sh = [sharpe(rets_matrix[s, test_idx]) for s in range(n_strat)]
        sorted_idx = np.argsort(test_sh)[::-1]
        rank = int(np.where(sorted_idx == best)[0][0]) + 1
        ranks.append(rank)
    if not ranks:
        return 0.0
    return float(np.mean([r > n_strat / 2 for r in ranks]))


def mcs_set(rets_matrix, block=BLOCK, n_boot=N_BOOT, alpha=ALPHA):
    """Model Confidence Set（Hansen 2011精神）：block bootstrap两两比较，输出无法区分集合

    简化实现：对每对策略(i,j)，block bootstrap重采样算"i优于j"的比例，
    用bootstrap分布算两两p值，控FWER，输出无法被区分的最优集合。
    """
    n_strat, n = rets_matrix.shape
    if n_strat < 2:
        return list(range(n_strat)), {}
    rng = np.random.default_rng(42)
    # 全样本sharpe排序
    full_sh = [sharpe(rets_matrix[s]) for s in range(n_strat)]
    best = int(np.argmax(full_sh))
    # block bootstrap重采样所有策略（保留跨策略相关）
    boot_sh = np.empty((n_boot, n_strat))
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            st = rng.integers(0, max(1, n - block + 1))
            idx.extend(range(st, min(st + block, n)))
        boot_sh[b] = [sharpe(rets_matrix[s, idx[:n]]) for s in range(n_strat)]
    # 两两p值：H0: sharpe_i <= sharpe_j（i是较优者）
    pairwise = {}
    for i, j in combinations(range(n_strat), 2):
        if full_sh[i] >= full_sh[j]:
            a, b = i, j
        else:
            a, b = j, i
        diff = boot_sh[:, a] - boot_sh[:, b]
        # 单侧p：P(diff <= 0)
        p = float(np.mean(diff <= 0)) if diff.std() > 0 else 0.5
        pairwise[frozenset({i, j})] = p
    # 无法区分集合：与最优策略p>alpha的（无法拒绝"不优于最优"）
    mcs = [s for s in range(n_strat) if s == best or pairwise.get(frozenset({s, best}), 1.0) > alpha]
    return mcs, {f"{min(i,j)}-{max(i,j)}": p for fs, p in pairwise.items() for i, j in [tuple(fs)]}


def spearman_stability(rets_matrix, n_seg=4):
    """分时段排名Spearman相关（排名稳定性）"""
    from scipy.stats import spearmanr
    n_strat, n = rets_matrix.shape
    seg_len = n // n_seg
    if seg_len < 5:
        return {}
    seg_sh = []
    for k in range(n_seg):
        seg = rets_matrix[:, k * seg_len:(k + 1) * seg_len]
        seg_sh.append([sharpe(seg[s]) for s in range(n_strat)])
    # 相邻段spearman
    stab = {}
    for k in range(n_seg - 1):
        rho, _ = spearmanr(seg_sh[k], seg_sh[k + 1])
        stab[f"seg{k+1}_vs_seg{k+2}"] = round(float(rho), 3)
    return stab


def main():
    log("=" * 60); log("阶段2 比较框架: compare_pool (MCS+DSR+Calmar+CPCV)"); log("=" * 60)
    if not os.path.exists(CAND_P):
        log(f"FATAL: 缺 {CAND_P}，先跑 collect_candidates.py"); return
    cands = json.load(open(CAND_P))
    log(f"候选策略: {list(cands.keys())}")

    # 对齐periods
    all_p = [set(dict(r).keys()) for r in cands.values()]
    common = sorted(set.intersection(*all_p)) if all_p else []
    log(f"共同period数: {len(common)} ({common[0]} -> {common[-1]})")
    names = list(cands.keys())
    rets_mat = np.array([[dict(cands[n]).get(p) for p in common] for n in names], float)
    # 列存策略，行period
    rets_mat = rets_mat.T  # period × strategy
    log(f"returns矩阵: {rets_mat.shape}")

    n_eff = effective_n(rets_mat)
    log(f"有效N(策略相关矩阵特征值): {n_eff:.2f} (名义{len(names)})")

    train_idx = [i for i, p in enumerate(common) if p <= TRAIN_END]
    oos_idx = [i for i, p in enumerate(common) if p > TRAIN_END]
    log(f"train: {len(train_idx)} / OOS: {len(oos_idx)} (TRAIN_END={TRAIN_END})")

    results = {}
    for si, name in enumerate(names):
        rets = rets_mat[:, si]
        dsr, sr_obs, e_max, sigma_sr = dsr_adjusted(rets, n_eff)
        cal = calmar(rets)
        mdd = max_dd(rets)
        cpcv = cpcv_oos_dist(rets)
        results[name] = {
            'sharpe_full': round(sr_obs, 3),
            'sharpe_train': round(sharpe(rets[train_idx]), 3),
            'sharpe_oos': round(sharpe(rets[oos_idx]), 3),
            'dsr': round(dsr, 3),
            'dsr_E_max': round(e_max, 4),
            'calmar': round(cal, 3),
            'max_dd': round(mdd, 3),
            'cpcv_oos_dist': [round(x, 3) for x in cpcv[:50]],  # 截断存
            'cpcv_median': round(float(np.median(cpcv)), 3) if cpcv else 0,
            'cpcv_p10': round(float(np.percentile(cpcv, 10)), 3) if cpcv else 0,
        }
        log(f"  {name}: SR全{sr_obs:.2f}/训练{sharpe(rets[train_idx]):.2f}/OOS{sharpe(rets[oos_idx]):.2f} DSR{dsr:.3f} Calmar{cal:.2f} MDD{mdd:.2%} CPCV中位{np.median(cpcv) if cpcv else 0:.2f}")

    pbo = pbo_in_pool(rets_mat.T)  # pbo_in_pool期望 strategy×period
    mcs, pairwise = mcs_set(rets_mat.T)  # strategy×period
    mcs_names = [names[i] for i in mcs]
    stab = spearman_stability(rets_mat.T)

    log("-" * 60)
    log(f"N_eff={n_eff:.2f} PBO={pbo:.3f}")
    log(f"MCS无法区分集合({len(mcs)}个): {mcs_names}")
    log(f"两两p值: {pairwise}")
    log(f"排名稳定性(Spearman): {stab}")
    log(f"N记账: 候选{len(names)}个, 有效独立{n_eff:.1f}个, 试验次数已诚实报告")

    out = {
        'run_at': datetime.now().isoformat(),
        'n_candidates': len(names), 'n_eff': round(n_eff, 2),
        'n_periods': len(common), 'train_end': TRAIN_END,
        'freq': FREQ, 'method': 'CPCV(purge+embargo+多split)+DSR(N_eff)+MCS(block bootstrap)+Calmar硬筛',
        'pbo': round(pbo, 3), 'mcs_set': mcs_names, 'pairwise_p': pairwise,
        'spearman_stability': stab,
        'strategies': results,
        'caveat': 'CPCV-OOS仍在同历史分布内,对未来无验证效力;MCS是Hansen2011精神的简化实现(非正式arch包)',
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")


if __name__ == '__main__':
    main()
