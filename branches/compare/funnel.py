#!/home/soso/v5/.venv/bin/python3
"""funnel 五路交集漏斗：E(经济先验) -> D(去冗余) -> B/A/C(增量打分) -> 候选因子集 -> 候选策略

顺序: E硬筛(全过) -> D去冗余(保留9) -> 在D保留集上 A/B/C打分综合排名 -> 选Top-K因子
-> 构造候选策略(等权多空/TSMOM sign多头/等权多头) -> 算returns -> 喂compare_pool

B路fdr_result全0通过(t_abs全<2), 故B用p值排名而非硬筛(避免交集空)。
"""
import os, json
from datetime import datetime
import numpy as np

ECON = os.path.expanduser('~/v5/branches/compare/economics_prior.json')
DSEL = os.path.expanduser('~/v5/branches/compare/double_selection_result.json')
IR = os.path.expanduser('~/v5/branches/compare/ir_result.json')
FDR = os.path.expanduser('~/v5/branches/factor_momentum/fdr_result.json')
MONO = os.path.expanduser('~/v5/branches/compare/monotonicity_result.json')
RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
RET_TOP = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_top_30.json')
OUT = os.path.expanduser('~/v5/branches/compare/funnel_result.json')
CAND = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
TOP_K = 5


def rank_dict(d, key, descending=True):
    """按key排名, descending=True大的排名高"""
    items = sorted(d.items(), key=lambda x: -x[1].get(key, 0) if descending else x[1].get(key, 1))
    return {f: i + 1 for i, (f, _) in enumerate(items)}


def strategy_returns(factor_set, ret_source, wks, mode='ls'):
    """算因子集组合returns: ls=等权多空, top=等权多头"""
    out = {}
    for w in wks:
        vals = [ret_source[f].get(w) for f in factor_set if f in ret_source and w in ret_source[f]]
        vals = [v for v in vals if v is not None]
        if vals:
            out[w] = float(np.mean(vals))
    return out


def main():
    log = lambda m: print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)
    log("=" * 60); log("funnel 五路交集漏斗"); log("=" * 60)

    econ = json.load(open(ECON))
    dsel = json.load(open(DSEL))
    ir = json.load(open(IR))
    fdr = json.load(open(FDR))
    mono = json.load(open(MONO))

    # E硬筛
    e_pass = {f for f, v in econ.items() if v.get('economic_pass')}
    # D去冗余
    d_keep = set(dsel.get('keep', []))
    log(f"E硬筛: {len(e_pass)}因子全过")
    log(f"D去冗余保留: {len(d_keep)}")

    # D保留集上 A/B/C打分
    candidates = sorted(d_keep & e_pass)
    log(f"E∩D候选: {len(candidates)} -> {candidates}")

    # A路IR排名
    a_rank = rank_dict({f: ir.get(f, {}) for f in candidates}, 'ir', True)
    # B路p值排名(p小排名高)
    b_rank = rank_dict({f: fdr.get('factors', {}).get(f, {}) for f in candidates}, 'p', False)
    # C路|rho|排名
    c_data = {f: {'abs_rho': abs(mono.get(f, {}).get('spearman_rho', 0))} for f in candidates}
    c_rank = rank_dict(c_data, 'abs_rho', True)

    # 综合排名(三路均值,小=好)
    composite = {}
    for f in candidates:
        composite[f] = round((a_rank[f] + b_rank[f] + c_rank[f]) / 3, 2)
    top = sorted(composite.items(), key=lambda x: x[1])[:TOP_K]
    top_factors = [f for f, _ in top]
    log(f"综合排名Top{TOP_K}: {top}")

    # 构造候选策略
    ls = json.load(open(RET_LS))
    top_r = json.load(open(RET_TOP))
    wks = sorted(set(w for f in top_factors for w in ls.get(f, {})))

    cands = {}
    # top5等权多空(配置层)
    rets = strategy_returns(top_factors, ls, wks, 'ls')
    arr = np.array(list(rets.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    cands['funnel_top5_eq_ls'] = [[w, rets[w]] for w in sorted(rets)]
    log(f"funnel_top5_eq_ls: SR{sr:.2f} 年化{arr.mean()*52:.2%}")

    # top5等权多头
    rets = strategy_returns(top_factors, top_r, wks, 'top')
    arr = np.array(list(rets.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    cands['funnel_top5_eq_long'] = [[w, rets[w]] for w in sorted(rets)]
    log(f"funnel_top5_eq_long: SR{sr:.2f} 年化{arr.mean()*52:.2%}")

    # top5 TSMOM sign筛多头(12周)
    K = 12
    ls_by = {w: {} for w in wks}
    for f in top_factors:
        for w, r in ls.get(f, {}).items():
            ls_by[w][f] = r
    tsmom = {}
    for i, w in enumerate(wks):
        if i < K:
            continue
        past = wks[i - K:i]
        port = 0.0; nf = 0
        for f in top_factors:
            past_ls = [ls_by[p].get(f) for p in past]
            past_ls = [x for x in past_ls if x is not None]
            if len(past_ls) < K // 2:
                continue
            if np.mean(past_ls) > 0:
                tr = top_r.get(f, {}).get(w)
                if tr is not None:
                    port += tr; nf += 1
        if nf:
            tsmom[w] = float(port / nf)
    arr = np.array(list(tsmom.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    cands['funnel_top5_tsmom_long'] = [[w, tsmom[w]] for w in sorted(tsmom)]
    log(f"funnel_top5_tsmom_long: SR{sr:.2f} 年化{arr.mean()*52:.2%}")

    # 存funnel结果
    out = {
        'run_at': datetime.now().isoformat(),
        'e_pass': len(e_pass), 'd_keep': len(d_keep),
        'candidates_e_d': candidates,
        'composite_rank': composite, 'top_factors': top_factors,
        'strategies': list(cands.keys()),
    }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")

    # 合并候选进 candidates_returns.json
    all_cands = json.load(open(CAND))
    for k, v in cands.items():
        all_cands[k] = v
    json.dump(all_cands, open(CAND, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"合并进 candidates_returns.json: {list(all_cands.keys())}")


if __name__ == '__main__':
    main()
