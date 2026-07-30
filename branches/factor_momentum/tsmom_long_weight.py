#!/home/soso/v5/.venv/bin/python3
"""long-only 持仓加权：等权 vs 信号强度加权
信号强度加权: 保留因子按过去12周多空收益均值大小加权(>0的因子)
K=4(最优), top30%多头
"""
import os, json
from datetime import datetime
import numpy as np

RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
RET_TOP = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_top.json')
TRAIN_END = '2022-W52'
FREQ = 52
K = 4


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


def run(ls, top, factors, wks, weighted=False):
    ls_by = {w: {} for w in wks}
    top_by = {w: {} for w in wks}
    for f in factors:
        for w, r in ls[f].items(): ls_by[w][f] = r
        for w, r in top[f].items(): top_by[w][f] = r
    rets, wks_used = [], []
    for i, w in enumerate(wks):
        if i < K: continue
        past = wks[i - K:i]
        picks = []
        for f in factors:
            past_ls = [x for x in (ls_by[p].get(f) for p in past) if x is not None]
            if len(past_ls) < max(1, K // 2): continue
            pm = float(np.mean(past_ls))
            if pm > 0:
                tr = top_by[w].get(f)
                if tr is not None:
                    picks.append((pm, tr))
        if picks:
            if weighted:
                wts = np.array([p for p, _ in picks])
                wts = wts / wts.sum()
                port = float(np.sum(wts * np.array([t for _, t in picks])))
            else:
                port = float(np.mean([t for _, t in picks]))
            rets.append(port); wks_used.append(w)
    tr_r = [r for w, r in zip(wks_used, rets) if w <= TRAIN_END]
    oos_r = [r for w, r in zip(wks_used, rets) if w > TRAIN_END]
    return stats(rets), stats(tr_r), stats(oos_r)


def main():
    ls = json.load(open(RET_LS))
    top = json.load(open(RET_TOP))
    factors = [f for f in ls if f in top]
    wks = sorted(set(w for f in factors for w in ls[f]))
    log(f"K={K}, 因子:{len(factors)}")
    eq_f, eq_tr, eq_oos = run(ls, top, factors, wks, weighted=False)
    w_f, w_tr, w_oos = run(ls, top, factors, wks, weighted=True)
    log(f"等权:        全段{eq_f['sharpe']:.2f} 训练{eq_tr['sharpe']:.2f} OOS{eq_oos['sharpe']:.2f}(年化{eq_oos['annual']:.2%})")
    log(f"信号强度加权: 全段{w_f['sharpe']:.2f} 训练{w_tr['sharpe']:.2f} OOS{w_oos['sharpe']:.2f}(年化{w_oos['annual']:.2%})")
    json.dump({'equal': {'full': eq_f, 'train': eq_tr, 'oos': eq_oos},
               'signal_weighted': {'full': w_f, 'train': w_tr, 'oos': w_oos}},
              open(os.path.expanduser('~/v5/branches/factor_momentum/tsmom_long_weight_result.json'), 'w'), indent=2, default=float)


if __name__ == '__main__':
    main()
