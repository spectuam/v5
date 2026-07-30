#!/home/soso/v5/.venv/bin/python3
"""TSMOM 做多版（A股实盘简化）
A股做空受限，实盘只能做多。简化: 正信号因子做多(sign=1), 负信号不持仓(sign=0)。
注意: 用多空收益(含做空bottom), A股实盘只能做多top30%不能做空bottom, 此版高估。
准确版要算 top30%多头收益(不含bottom)，下步。
"""
import os, json
from datetime import datetime
import numpy as np

RET_FILE = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
OUT = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_long_result.json')
K = 12
TRAIN_END = '2022-W52'
FREQ = 52


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(returns):
    if len(returns) < 2: return 0.0
    arr = np.array(returns)
    if arr.std() == 0: return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(FREQ))


def stats(r):
    if not r: return {}
    arr = np.array(r)
    t = float(arr.mean() / (arr.std() / np.sqrt(len(arr)))) if arr.std() > 0 else 0
    return {'n': len(arr), 'annual': float(arr.mean() * FREQ), 'sharpe': sharpe(r), 't': t}


def main():
    log("=" * 60); log("TSMOM 做多版简化 (正信号做多, 负不持仓)"); log("=" * 60)
    factor_ret = json.load(open(RET_FILE))
    factors = list(factor_ret.keys())
    wks = sorted(set(w for f in factors for w in factor_ret[f]))
    ret_by = {w: {} for w in wks}
    for f in factors:
        for w, r in factor_ret[f].items():
            ret_by[w][f] = r

    long_rets = []
    for i, w in enumerate(wks):
        if i < K: continue
        past = wks[i - K:i]
        cur = ret_by[w]
        port = 0.0; nf = 0
        for f in factors:
            pr = [ret_by[p].get(f) for p in past]
            pr = [x for x in pr if x is not None]
            if len(pr) < K // 2 or f not in cur: continue
            if np.mean(pr) > 0:  # 只做多正信号因子
                port += cur[f]; nf += 1
        if nf: long_rets.append(port / nf)

    all_r = long_rets
    tr_r = [r for i, w in enumerate(wks) if i >= K and w <= TRAIN_END for r in [all_r[i-K] if i-K < len(all_r) else 0]]  # 简化
    log(f"做多版(简化,高估): 全段{stats(all_r)}")
    log("对标: 多空版全段夏普1.80, v5原TSFM OOS0.557")
    log("注意: 此版用多空收益(含做空bottom), A股实盘只能做多top30%, 高估")

    out = {'strategy': 'TSMOM_long_simplified', 'K': K, 'full': stats(all_r),
           'caveat': '用多空收益(含做空bottom), A股实盘只能做多top30%, 高估; 准确版要算top30%多头'}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")


if __name__ == '__main__':
    main()
