#!/home/soso/v5/.venv/bin/python3
"""market_regime statsmodels 版（Hamilton 1989 / KNS 1998 谱系）

替换 hmmlearn 简易版（见 market_regime.py.hmmlearn.bak）。修复文献调研5硬伤：
  ①5状态过多 -> AIC/BIC 数据驱动选状态数（数据选 k=2）
  ②2特征Gaussian非标准 -> 单收益序列 mean/variance 切换（KNS 标准）
  ③缺AR结构 -> KNS 方差切换是市场状态标准（MS-AR 标注 future）
  ④周频非主流 -> 月频（Hamilton/KNS 事实标准）
  ⑤covariance混用 -> 单变量无 covariance

自带 Hamilton filter（因果）+ Kim smoother（全样本），非手搓 hmmlearn。

输出 market_regime_result.json:
  - month_state_smoothed: 理论上限（Kim smoother 用全样本，look-ahead）
  - month_state_filtered: live 因果（Hamilton filter 只用过去）
  - week_state: month 传播到周（filtered=live，兼容 state_adaptive 接口）
  - week_state_smoothed: month 传播到周（smoothed=上限）
  - state_stats(sigma2/count/年化/SR/MDD) + transmat + aic_bic + probs

文献: Hamilton 1989 Econometrica 57(2):357-384 (DOI 10.2307/1912559);
      KNS 1998 (Kim-Nelson-Startz 方差切换); statsmodels regime_switching 文档。
"""
import os, json, warnings
from datetime import datetime
from collections import OrderedDict
import numpy as np
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

MKT = os.path.expanduser('~/v5/branches/compare/market_benchmark_returns.json')
OUT = os.path.expanduser('~/v5/branches/compare/market_regime_result.json')
K_CANDIDATES = [2, 3, 4]
TREND = 'n'  # KNS: 零均值，方差切换
MAXITER = 1000
N_RESTARTS = 5  # n_init 精神：多次 fit 取最佳 llf 防不收敛
LABELS_BY_K = {
    2: ['calm', 'crash'],
    3: ['calm', 'normal', 'crash'],
    4: ['calm', 'normal', 'turbulent', 'crash'],
}


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def week_to_month(wk):
    """ISO 周 -> YYYY-MM（周一首日所在月）。W53 越界则夹到 W52。"""
    y, w = int(wk[:4]), int(wk[6:8])
    try:
        monday = datetime.fromisocalendar(y, w, 1)
    except ValueError:
        monday = datetime.fromisocalendar(y, 52, 1)
    return monday.strftime('%Y-%m')


def monthly_resample(weekly_pairs):
    """周收益 compound -> 月收益。返回 (months_sorted, mret_array)。"""
    mon = OrderedDict()
    for w, ret in weekly_pairs:
        mon.setdefault(week_to_month(w), []).append(ret)
    months = sorted(mon)
    mret = np.array([float(np.prod([1 + r for r in mon[ym]]) - 1) for ym in months])
    return months, mret


def fit_k(mret, k):
    """fit MarkovRegression(k, trend=n, switching_variance)，N_RESTARTS 次取最佳 llf。"""
    best = None
    for _ in range(N_RESTARTS):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                mod = MarkovRegression(mret, k_regimes=k, trend=TREND, switching_variance=True)
                res = mod.fit(maxiter=MAXITER, disp=False)
                if best is None or res.llf > best.llf:
                    best = res
        except Exception:
            continue
    return best


def aic_bic(res, n):
    npar = len(res.params)
    return -2 * res.llf + 2 * npar, -2 * res.llf + npar * np.log(n)


def build_transmat(res, k):
    """从 params 的 p[i->j] 名解析转移矩阵；每行末列（未参数化）取补。"""
    pnames = res.model.param_names
    params = res.params
    trans = np.zeros((k, k))
    seen = {i: set() for i in range(k)}
    for idx, name in enumerate(pnames):
        if name.startswith('p[') and '->' in name:
            inside = name[2:name.index(']')]
            i_str, j_str = inside.split('->')
            i, j = int(i_str), int(j_str)
            trans[i][j] = float(params[idx])
            seen[i].add(j)
    for i in range(k):
        missing = set(range(k)) - seen[i]
        if missing:
            trans[i][list(missing)[0]] = 1.0 - sum(trans[i][j] for j in seen[i])
    return trans


def label_by_variance(res, k):
    """状态按 sigma2 升序标注（低波动在前），修 label-switching。"""
    pnames = res.model.param_names
    sig_idx = [i for i, n in enumerate(pnames) if 'sigma2' in n]
    sig_vals = [float(res.params[i]) for i in sig_idx]
    order = np.argsort(sig_vals)  # asc：低波动排名在前
    labels = LABELS_BY_K.get(k, [f's{i}' for i in range(k)])
    regime_label = {}
    for rank, regime in enumerate(order):
        regime_label[int(regime)] = labels[rank] if rank < len(labels) else f's{regime}'
    return regime_label, sig_vals


def max_dd(rets):
    arr = np.asarray(rets, float)
    if len(arr) == 0:
        return 0.0
    nav = np.cumprod(1 + arr)
    peak = np.maximum.accumulate(nav)
    return float(((nav - peak) / peak).min())


def state_stats(mret, reg_assign, regime_label, sig_vals, k):
    out = {}
    for r in range(k):
        mask = reg_assign == r
        arr = mret[mask]
        if len(arr) == 0:
            continue
        sr = float(arr.mean() / arr.std() * np.sqrt(12)) if arr.std() > 0 else 0.0
        out[regime_label[r]] = {
            'regime': r, 'n_months': int(mask.sum()),
            'sigma2': round(float(sig_vals[r]), 5),
            'annual': round(float(arr.mean() * 12), 4),
            'vol_annual': round(float(arr.std() * np.sqrt(12)), 4),
            'sharpe': round(sr, 2),
            'max_dd': round(max_dd(arr), 3),
        }
    return out


def main():
    log("=" * 60); log("market_regime statsmodels (Hamilton/KNS)"); log("=" * 60)
    mkt_raw = json.load(open(MKT))['market_eq']
    mkt = dict(mkt_raw)
    weeks = sorted(mkt.keys())
    months, mret = monthly_resample([(w, mkt[w]) for w in weeks])
    sr_m = float(mret.mean() / mret.std() * np.sqrt(12)) if mret.std() > 0 else 0
    log(f"月频: {len(months)}月 {months[0]}~{months[-1]}, 年化{mret.mean()*12:.2%} SR{sr_m:.2f}")

    # AIC/BIC 扫描
    log("AIC/BIC 扫描:")
    fits = {}
    aic_bic_table = []
    for k in K_CANDIDATES:
        res = fit_k(mret, k)
        if res is None:
            log(f"  k={k}: fit 失败"); continue
        aic, bic = aic_bic(res, len(mret))
        fits[k] = (res, aic, bic)
        aic_bic_table.append({'k': k, 'nparam': len(res.params), 'llf': round(float(res.llf), 1),
                              'AIC': round(aic, 1), 'BIC': round(bic, 1)})
        log(f"  k={k}: params={len(res.params)} llf={res.llf:.1f} AIC={aic:.1f} BIC={bic:.1f}")
    if not fits:
        log("FATAL: 所有 k fit 失败"); return
    best_k = min(fits, key=lambda k: fits[k][2])  # BIC 最优（更重惩罚复杂度）
    res = fits[best_k][0]
    log(f"BIC 最优: k={best_k}")

    # 方差标注
    regime_label, sig_vals = label_by_variance(res, best_k)
    log("状态（按 sigma2 升序，低波动在前）:")
    for r in range(best_k):
        log(f"  r{r}({regime_label[r]}): sigma2={sig_vals[r]:.5f}")

    # smoothed（上限）+ filtered（live）
    smp = np.asarray(res.smoothed_marginal_probabilities)
    fil = np.asarray(res.filtered_marginal_probabilities)
    reg_sm = smp.argmax(1)
    reg_fil = fil.argmax(1)
    agree = float(np.mean(reg_sm == reg_fil))
    log(f"smoothed vs filtered 一致率: {agree:.1%}（高=live 可达版接近理论上限）")

    month_state_smoothed = {months[i]: regime_label[int(reg_sm[i])] for i in range(len(months))}
    month_state_filtered = {months[i]: regime_label[int(reg_fil[i])] for i in range(len(months))}

    stats_filtered = state_stats(mret, reg_fil, regime_label, sig_vals, best_k)
    stats_smoothed = state_stats(mret, reg_sm, regime_label, sig_vals, best_k)
    log("filtered(live) 状态统计:")
    for lab, st in stats_filtered.items():
        log(f"  {lab}: {st['n_months']}月, 年化{st['annual']:.2%}, 波动{st['vol_annual']:.2%}, SR{st['sharpe']}, MDD{st['max_dd']:.2%}")

    # 转移矩阵 + 期望持续期
    trans = build_transmat(res, best_k)
    exp_dur = np.asarray(res.expected_durations).flatten()
    log("转移矩阵（行=from）:")
    for i in range(best_k):
        log("  " + regime_label[i] + ": " + " ".join(f"{regime_label[j]}={trans[i][j]:.2f}" for j in range(best_k)))
    log("期望持续期(月): " + ", ".join(f"{regime_label[r]}={exp_dur[r]:.1f}" for r in range(best_k)))

    # month 传播到周（filtered=live 默认，兼容 state_adaptive 接口）
    week_state = {}
    week_state_smoothed = {}
    for w in weeks:
        ym = week_to_month(w)
        if ym in month_state_filtered:
            week_state[w] = month_state_filtered[ym]
            week_state_smoothed[w] = month_state_smoothed[ym]
    log(f"week_state: {len(week_state)}周（month 传播）")

    out = {
        'run_at': datetime.now().isoformat(),
        'method': f'statsmodels MarkovRegression(trend={TREND!r}, switching_variance, KNS), 月频, AIC/BIC选k={best_k}',
        'data': {'freq': 'monthly', 'n_months': len(months), 'range': [months[0], months[-1]],
                 'source': 'market_benchmark_returns.json 周收益 compound'},
        'aic_bic': aic_bic_table, 'best_k': best_k,
        'regime_label': regime_label, 'sigma2': [round(float(s), 5) for s in sig_vals],
        'transition_matrix': [[round(float(trans[i][j]), 3) for j in range(best_k)] for i in range(best_k)],
        'expected_duration_months': [round(float(d), 1) for d in exp_dur],
        'smoothed_vs_filtered_agreement': round(agree, 3),
        'state_stats_filtered': stats_filtered,
        'state_stats_smoothed': stats_smoothed,
        'month_state_filtered': month_state_filtered,
        'month_state_smoothed': month_state_smoothed,
        'week_state': week_state,           # filtered=live，state_adaptive 默认读这个
        'week_state_smoothed': week_state_smoothed,
        'smoothed_marginal_probs': [[round(float(x), 3) for x in row] for row in smp],
        'filtered_marginal_probs': [[round(float(x), 3) for x in row] for row in fil],
        'caveat': 'smoothed=Kim smoother 全样本(look-ahead理论上限); filtered=Hamilton filter 因果(live可达); 参数仍全局估计,严格live见market_regime_rolling.py',
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")


if __name__ == '__main__':
    main()
