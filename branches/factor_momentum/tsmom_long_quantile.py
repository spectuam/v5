#!/home/soso/v5/.venv/bin/python3
"""long-only TSMOM 筛因子选股 - 分位段对比（top10/20/30/40%）

信号层固定：过去12周多空收益均值>0 保留(sign=+1)，<0 剔除（同一信号层）
持仓层对比：保留因子的 top{X}% 多头收益等权平均，X ∈ {10,20,30,40}
输出：全段/训练/OOS/扣成本net/换手/OOS4段夏普
"""
import os, json
from datetime import datetime
import numpy as np

RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
TOP_DIR = os.path.expanduser('~/v5/branches/factor_momentum')
PCTS = [0.10, 0.20, 0.30, 0.40]
K = 12
TRAIN_END = '2022-W52'
FREQ = 52
COST_A = 0.0030  # A股 round-trip 30bp


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(r, freq=FREQ):
    if len(r) < 2:
        return 0.0
    arr = np.array(r)
    if arr.std() == 0:
        return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def stats(r):
    if not r:
        return {}
    arr = np.array(r)
    t = float(arr.mean() / (arr.std() / np.sqrt(len(arr)))) if arr.std() > 0 else 0
    return {'n': len(arr), 'annual': float(arr.mean() * FREQ), 'sharpe': sharpe(r), 't': t}


def run_one(ls, top, factors, wks):
    ls_by = {w: {} for w in wks}
    top_by = {w: {} for w in wks}
    for f in factors:
        for w, r in ls[f].items():
            ls_by[w][f] = r
        for w, r in top[f].items():
            top_by[w][f] = r
    rets, wks_used, active_sets, turnovers = [], [], [], []
    for i, w in enumerate(wks):
        if i < K:
            continue
        past = wks[i - K:i]
        port = 0.0; nf = 0; active = set()
        for f in factors:
            past_ls = [ls_by[p].get(f) for p in past]
            past_ls = [x for x in past_ls if x is not None]
            if len(past_ls) < K // 2:
                continue
            if np.mean(past_ls) > 0:
                tr = top_by[w].get(f)
                if tr is not None:
                    port += tr; nf += 1; active.add(f)
        if nf:
            rets.append(port / nf)
            wks_used.append(w)
            active_sets.append(active)
            if len(active_sets) >= 2:
                changed = len(active_sets[-1] ^ active_sets[-2])
                turnovers.append(changed / len(factors))
    tr_r = [r for w, r in zip(wks_used, rets) if w <= TRAIN_END]
    oos_r = [r for w, r in zip(wks_used, rets) if w > TRAIN_END]
    net = [r - COST_A * t for r, t in zip(rets, turnovers + [0])][:len(rets)]
    seg4 = []
    if len(oos_r) >= 4:
        n4 = len(oos_r) // 4
        seg4 = [round(sharpe(oos_r[j * n4:(j + 1) * n4]), 2) for j in range(4)]
    return {
        'full': stats(rets), 'train': stats(tr_r), 'oos': stats(oos_r),
        'net': stats(net),
        'avg_turnover': float(np.mean(turnovers)) if turnovers else 0,
        'avg_active': float(np.mean([len(a) for a in active_sets])) if active_sets else 0,
        'seg4_sharpe': seg4,
    }


def main():
    log("=" * 60); log("long-only TSMOM 分位段对比 (top10/20/30/40%)"); log("=" * 60)
    ls = json.load(open(RET_LS))
    summary = {}
    for p in PCTS:
        topp = os.path.join(TOP_DIR, f'factor_returns_top_{int(p*100)}.json')
        if not os.path.exists(topp):
            log(f"缺 {topp}，跳过 top{int(p*100)}%")
            continue
        top = json.load(open(topp))
        factors = [f for f in ls if f in top]
        wks = sorted(set(w for f in factors for w in ls[f]))
        log(f"top{int(p*100)}%: {len(factors)}因子, {len(wks)}周 ...")
        r = run_one(ls, top, factors, wks)
        summary[f'top{int(p*100)}'] = r
        log(f"  全段:{r['full']} 训练:{r['train']} OOS:{r['oos']} net:{r['net']}")
        log(f"  保留因子:{r['avg_active']:.1f}/{len(factors)} 换手:{r['avg_turnover']:.1%}/周 OOS4段夏普:{r['seg4_sharpe']}")
    OUT = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_long_quantile_result.json')
    json.dump(summary, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written {OUT}")


if __name__ == '__main__':
    main()
