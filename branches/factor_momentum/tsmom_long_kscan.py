#!/home/soso/v5/.venv/bin/python3
"""long-only TSMOM K扫描：K=1/4/24 看最优形成期"""
import os, json
from datetime import datetime
import numpy as np

RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
RET_TOP = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_top.json')
TRAIN_END = '2022-W52'
FREQ = 52


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(r):
    if len(r) < 2: return 0.0
    arr = np.array(r)
    if arr.std() == 0: return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(FREQ))


def stats(r):
    if not r: return {}
    arr = np.array(r)
    t = float(arr.mean() / (arr.std() / np.sqrt(len(arr)))) if arr.std() > 0 else 0
    return {'n': len(arr), 'annual': float(arr.mean() * FREQ), 'sharpe': sharpe(r), 't': t}


def run_k(ls, top, factors, wks, K):
    ls_by = {w: {} for w in wks}
    top_by = {w: {} for w in wks}
    for f in factors:
        for w, r in ls[f].items(): ls_by[w][f] = r
        for w, r in top[f].items(): top_by[w][f] = r
    rets, wks_used = [], []
    for i, w in enumerate(wks):
        if i < K: continue
        past = wks[i - K:i]
        port = 0.0; nf = 0
        for f in factors:
            past_ls = [ls_by[p].get(f) for p in past]
            past_ls = [x for x in past_ls if x is not None]
            if len(past_ls) < max(1, K // 2): continue
            if np.mean(past_ls) > 0:
                tr = top_by[w].get(f)
                if tr is not None:
                    port += tr; nf += 1
        if nf:
            rets.append(port / nf); wks_used.append(w)
    tr_r = [r for w, r in zip(wks_used, rets) if w <= TRAIN_END]
    oos_r = [r for w, r in zip(wks_used, rets) if w > TRAIN_END]
    return stats(rets), stats(tr_r), stats(oos_r)


def main():
    ls = json.load(open(RET_LS))
    top = json.load(open(RET_TOP))
    factors = [f for f in ls if f in top]
    wks = sorted(set(w for f in factors for w in ls[f]))
    log(f"因子:{len(factors)}, 周数:{len(wks)}")
    log(f"{'K':<5} {'全段夏普':<10} {'训练夏普':<10} {'OOS夏普':<10} {'OOS年化':<10} {'OOS t':<8}")
    out = {}
    for K in [1, 4, 24]:
        full, tr, oos = run_k(ls, top, factors, wks, K)
        out[K] = {'full': full, 'train': tr, 'oos': oos}
        log(f"{K:<5} {full['sharpe']:<10.2f} {tr['sharpe']:<10.2f} {oos['sharpe']:<10.2f} {oos['annual']:<10.2%} {oos['t']:<8.2f}")
    json.dump(out, open(os.path.expanduser('~/v5/branches/factor_momentum/tsmom_long_kscan_result.json'), 'w'), indent=2, default=float)


if __name__ == '__main__':
    main()
