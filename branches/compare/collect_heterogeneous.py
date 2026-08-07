#!/home/soso/v5/.venv/bin/python3
"""补充异构候选策略returns，合并进 candidates_returns.json

秒级，用已有 factor_returns_week.json(38因子多空收益)，不重跑全市场：
- tsmom_ls_K12: sign筛(12周多空>0保留) + 多空收益持仓(做多正收益因子做空负收益因子)
- eq38_ls: 等权38因子多空(GK配置层口径，所有因子多空等权)

异构于 tsmom_long(多头)。market等权基准需重跑全市场(10min)，后台另补。
"""
import os, json
from datetime import datetime
import numpy as np

RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
CAND_P = os.path.expanduser('~/v5/branches/compare/candidates_returns.json')
K = 12


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main():
    log("=" * 60); log("补充异构候选 (tsmom_ls + eq38_ls)"); log("=" * 60)
    ls = json.load(open(RET_LS))
    factors = list(ls.keys())
    wks = sorted(set(w for f in factors for w in ls[f]))
    ls_by = {w: {} for w in wks}
    for f in factors:
        for w, r in ls[f].items():
            ls_by[w][f] = r

    # 1. tsmom_ls_K12: sign筛 + 多空持仓(>0做多ls收益, <0做空ls收益即取负)
    tsmom_ls = {}
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
            cur = ls_by[w].get(f)
            if cur is None:
                continue
            if np.mean(past_ls) > 0:
                port += cur      # 做多正收益因子
            else:
                port -= cur      # 做空负收益因子(sign反转)
            nf += 1
        if nf:
            tsmom_ls[w] = float(port / nf)
    arr = np.array(list(tsmom_ls.values()))
    sr = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    log(f"tsmom_ls_K12: {len(tsmom_ls)}周, 全段夏普{sr:.2f}, 年化{arr.mean()*52:.2%}")

    # 2. eq38_ls: 等权38因子多空(每周所有因子多空收益均值, GK配置层)
    eq38 = {}
    for w in wks:
        vals = [ls_by[w].get(f) for f in factors if ls_by[w].get(f) is not None]
        if vals:
            eq38[w] = float(np.mean(vals))
    arr2 = np.array(list(eq38.values()))
    sr2 = float(arr2.mean() / arr2.std() * np.sqrt(52)) if arr2.std() > 0 else 0
    log(f"eq38_ls: {len(eq38)}周, 全段夏普{sr2:.2f}, 年化{arr2.mean()*52:.2%}")

    # 合并进 candidates_returns.json
    cands = json.load(open(CAND_P)) if os.path.exists(CAND_P) else {}
    cands['tsmom_ls_K12'] = [[w, tsmom_ls[w]] for w in sorted(tsmom_ls)]
    cands['eq38_ls'] = [[w, eq38[w]] for w in sorted(eq38)]
    json.dump(cands, open(CAND_P, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"合并后候选: {list(cands.keys())}")
    log(f"written: {CAND_P}")


if __name__ == '__main__':
    main()
