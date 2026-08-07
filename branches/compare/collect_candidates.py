#!/home/soso/v5/.venv/bin/python3
"""准备候选策略returns -> candidates_returns.json

阶段2跑通用：TSMOM long-only 的 K 变体（K=1/4/12/24），复用已有
factor_returns_week.json(多空信号) + factor_returns_top_30.json(top30多头收益)。
秒级，不重跑全市场扫描。

后续补多样性候选：lowvol / phase2 IC选股 / 等权市场基准（需重跑，10-15min）。
"""
import os, json
from datetime import datetime
import numpy as np

RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
RET_TOP = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_top_30.json')
OUT = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
KS = [1, 4, 12, 24]


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def tsmom_long_returns(ls, top, factors, wks, K):
    """复用tsmom_long_select.py的run_one逻辑，改K参数，返回{week: ret}"""
    ls_by = {w: {} for w in wks}
    top_by = {w: {} for w in wks}
    for f in factors:
        for w, r in ls[f].items():
            ls_by[w][f] = r
        for w, r in top[f].items():
            top_by[w][f] = r
    out = {}
    for i, w in enumerate(wks):
        if i < K:
            continue
        past = wks[i - K:i]
        port = 0.0; nf = 0
        for f in factors:
            past_ls = [ls_by[p].get(f) for p in past]
            past_ls = [x for x in past_ls if x is not None]
            if len(past_ls) < K // 2:
                continue
            if np.mean(past_ls) > 0:
                tr = top_by[w].get(f)
                if tr is not None:
                    port += tr; nf += 1
        if nf:
            out[w] = float(port / nf)
    return out


def main():
    log("=" * 60); log("准备候选策略returns (TSMOM K变体)"); log("=" * 60)
    ls = json.load(open(RET_LS))
    top = json.load(open(RET_TOP))
    factors = [f for f in ls if f in top]
    wks = sorted(set(w for f in factors for w in ls[f]))
    log(f"因子{len(factors)} 周{len(wks)} K变体{KS}")

    cands = {}
    for K in KS:
        r = tsmom_long_returns(ls, top, factors, wks, K)
        cands[f'tsmom_long_K{K}'] = [[w, r[w]] for w in sorted(r)]
        arr = np.array(list(r.values()))
        sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
        log(f"  K={K}: {len(r)}周, 全段夏普{sr:.2f}, 年化{arr.mean()*52:.2%}")

    json.dump(cands, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written: {OUT}")
    log("注: K变体高度相关(同策略不同K)，MCS预期显示'无法区分'，证明框架work即可")
    log("后续补lowvol/phase2/等权基准增加候选多样性")


if __name__ == '__main__':
    main()
