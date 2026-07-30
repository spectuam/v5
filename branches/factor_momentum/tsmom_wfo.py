#!/home/soso/v5/.venv/bin/python3
"""TSMOM 周度 WFO（滚动窗口稳健性）
TSMOM 无参数训练（K=12固定sign等权），过拟合主要是时段差异。
看滚动1年(52周)窗口夏普分布 + OOS段分段，判断OOS是否真稳。
"""
import os, json
from datetime import datetime
import numpy as np

RET_FILE = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_week_result.json')
WIN = 52  # 滚动窗口1年
FREQ = 52


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(returns):
    if len(returns) < 2: return 0.0
    arr = np.array(returns)
    if arr.std() == 0: return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(FREQ))


def main():
    log("=" * 60); log("TSMOM 周度 WFO (滚动52周窗口夏普分布)"); log("=" * 60)
    data = json.load(open(RET_FILE))
    rets = [r for _, r in data['returns']]
    wks = [w for w, _ in data['returns']]
    log(f"总周数:{len(rets)}")

    # 滚动52周窗口夏普
    sharps = []
    for i in range(len(rets) - WIN + 1):
        w = rets[i:i + WIN]
        sharps.append(sharpe(w))
    sharps = np.array(sharps)
    log(f"滚动{WIN}周窗口夏普分布 (n={len(sharps)}):")
    log(f"  min={sharps.min():.2f} p25={np.percentile(sharps,25):.2f} median={np.median(sharps):.2f} p75={np.percentile(sharps,75):.2f} max={sharps.max():.2f}")
    log(f"  负窗口占比: {(sharps<0).mean():.1%}")
    log(f"  >1占比: {(sharps>1).mean():.1%}, >0.5占比: {(sharps>0.5).mean():.1%}")

    # OOS段(>2022-W52)分段（4段，每段~45周）
    oos_idx = [i for i, w in enumerate(wks) if w > '2022-W52']
    oos_rets = [rets[i] for i in oos_idx]
    log(f"\nOOS段({len(oos_rets)}周)分段夏普:")
    n4 = len(oos_rets) // 4
    for j in range(4):
        seg = oos_rets[j*n4:(j+1)*n4]
        log(f"  段{j+1}({len(seg)}周): 夏普{sharpe(seg):.2f}, 年化{np.mean(seg)*FREQ:.2%}")

    # K稳健性（不同形成期，看OOS是否依赖K）
    factor_ret = json.load(open(os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')))
    factors = list(factor_ret.keys())
    all_wks = sorted(set(w for f in factors for w in factor_ret[f]))
    ret_by = {w: {} for w in all_wks}
    for f in factors:
        for w, r in factor_ret[f].items():
            ret_by[w][f] = r
    log(f"\nK稳健性(OOS段，不同形成期):")
    for K in [1, 3, 6, 12, 24]:
        oos_r = []
        for i, w in enumerate(all_wks):
            if i < K or w <= '2022-W52': continue
            past = all_wks[i-K:i]
            port = 0; nf = 0
            for f in factors:
                pr = [ret_by[p].get(f) for p in past]
                pr = [x for x in pr if x is not None]
                if len(pr) < K//2 or f not in ret_by[w]: continue
                sign = 1.0 if np.mean(pr) > 0 else -1.0
                port += sign * ret_by[w][f]; nf += 1
            if nf: oos_r.append(port/nf)
        log(f"  K={K}: OOS夏普{sharpe(oos_r):.2f}, 年化{np.mean(oos_r)*FREQ:.2%}, n={len(oos_r)}")

    json.dump({'rolling_sharps': sharps.tolist(),
               'rolling_dist': {'min': float(sharps.min()), 'p25': float(np.percentile(sharps,25)),
                                'median': float(np.median(sharps)), 'p75': float(np.percentile(sharps,75)),
                                'max': float(sharps.max()), 'neg_pct': float((sharps<0).mean())}},
              open(os.path.expanduser('~/v5/branches/factor_momentum/tsmom_wfo_result.json'), 'w'),
              indent=2, ensure_ascii=False, default=float)
    log("written: tsmom_wfo_result.json")


if __name__ == '__main__':
    main()
