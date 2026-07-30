#!/home/soso/v5/.venv/bin/python3
"""TSMOM 周度复现（week口径，12周形成期）
对标 month 版（夏普1.02），看 week 是否更强（诊断层 week 信号更强）。
"""
import os, json
from datetime import datetime
import numpy as np

OUT = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_week_result.json')
RET_FILE = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
K = 12  # 12周形成期
TRAIN_END = '2022-W52'
FREQ = 52


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(returns, freq=FREQ):
    if len(returns) < 2: return 0.0
    arr = np.array(returns)
    if arr.std() == 0: return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def stats(returns):
    if not returns: return {}
    arr = np.array(returns)
    t = float(arr.mean() / (arr.std() / np.sqrt(len(arr)))) if arr.std() > 0 else 0
    return {'n': len(arr), 'annual': float(arr.mean() * FREQ), 'sharpe': sharpe(returns), 't': t}


def main():
    log("=" * 60); log("TSMOM 周度复现 (12周形成期, sign等权)"); log("=" * 60)
    factor_ret = json.load(open(RET_FILE))
    factors = list(factor_ret.keys())
    wks = sorted(set(w for f in factors for w in factor_ret[f]))
    log(f"因子:{len(factors)}, 周数:{len(wks)}")

    ret_by_week = {w: {} for w in wks}
    for f in factors:
        for w, r in factor_ret[f].items():
            ret_by_week[w][f] = r

    ts_rets = []
    for i, w in enumerate(wks):
        if i < K: continue
        past = wks[i - K:i]
        cur = ret_by_week[w]
        port = 0.0; nf = 0
        for f in factors:
            past_rets = [ret_by_week[p].get(f) for p in past]
            past_rets = [x for x in past_rets if x is not None]
            if len(past_rets) < K // 2: continue
            past_mean = float(np.mean(past_rets))
            if f not in cur: continue
            sign = 1.0 if past_mean > 0 else -1.0
            port += sign * cur[f]
            nf += 1
        if nf == 0: continue
        port /= nf
        ts_rets.append((w, port))

    all_r = [r for _, r in ts_rets]
    tr_r = [r for w, r in ts_rets if w <= TRAIN_END]
    oos_r = [r for w, r in ts_rets if w > TRAIN_END]
    log(f"全段: {stats(all_r)}")
    log(f"训练(<=2022-W52): {stats(tr_r)}")
    log(f"OOS(>2022-W52): {stats(oos_r)}")
    log("对标: month TSMOM 全段夏普1.02/训练1.31/OOS0.69")

    out = {'strategy': 'TSMOM_sign_12w', 'K': K, 'factors': len(factors),
           'full': stats(all_r), 'train': stats(tr_r), 'oos': stats(oos_r),
           'returns': ts_rets}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")


if __name__ == '__main__':
    main()
