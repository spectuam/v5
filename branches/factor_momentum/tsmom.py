#!/home/soso/v5/.venv/bin/python3
"""TSMOM 复现（GK/EL 口径）：因子收益时序动量
每月: 过去12月因子收益>0做多, <0做空, 等权组合所有因子
数据: factor_returns.json (每月每因子多空收益)
对标: GK TSFM Sharpe 0.84, EL TSMOM 4.19%/t=7.04/夏普0.98
"""
import os, json
from datetime import datetime
import numpy as np

OUT = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_result.json')
RET_FILE = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns.json')
K = 12  # 形成期12月
TRAIN_END = '2022-12'


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(returns, freq=12):
    if len(returns) < 2: return 0.0
    arr = np.array(returns)
    if arr.std() == 0: return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def stats(returns):
    if not returns: return {}
    arr = np.array(returns)
    t = float(arr.mean() / (arr.std() / np.sqrt(len(arr)))) if arr.std() > 0 else 0
    return {'n': len(arr), 'annual': float(arr.mean() * 12), 'sharpe': sharpe(returns), 't': t}


def main():
    log("=" * 60); log("TSMOM 复现 (GK/EL 口径, 12月形成期, sign等权)"); log("=" * 60)
    factor_ret = json.load(open(RET_FILE))
    factors = list(factor_ret.keys())
    yms = sorted(set(ym for f in factors for ym in factor_ret[f]))
    log(f"因子:{len(factors)}, 月份:{len(yms)}")

    ret_by_month = {ym: {} for ym in yms}
    for f in factors:
        for ym, r in factor_ret[f].items():
            ret_by_month[ym][f] = r

    ts_rets = []
    for i, ym in enumerate(yms):
        if i < K: continue
        past = yms[i - K:i]
        cur = ret_by_month[ym]
        port = 0.0; nf = 0
        for f in factors:
            past_rets = [ret_by_month[p].get(f) for p in past]
            past_rets = [x for x in past_rets if x is not None]
            if len(past_rets) < K // 2: continue  # 过去12月至少6个有值
            past_mean = float(np.mean(past_rets))
            if f not in cur: continue
            sign = 1.0 if past_mean > 0 else -1.0
            port += sign * cur[f]
            nf += 1
        if nf == 0: continue
        port /= nf
        ts_rets.append((ym, port))

    all_r = [r for _, r in ts_rets]
    tr_r = [r for ym, r in ts_rets if ym <= TRAIN_END]
    oos_r = [r for ym, r in ts_rets if ym > TRAIN_END]
    log(f"全段: {stats(all_r)}")
    log(f"训练(<=2022-12): {stats(tr_r)}")
    log(f"OOS(>2022-12): {stats(oos_r)}")
    log("对标: GK TSFM Sharpe 0.84, EL TSMOM 4.19%/t=7.04/夏普0.98")

    out = {'strategy': 'TSMOM_sign_12m', 'K': K, 'factors': len(factors),
           'full': stats(all_r), 'train': stats(tr_r), 'oos': stats(oos_r),
           'returns': ts_rets}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")


if __name__ == '__main__':
    main()
