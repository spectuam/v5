#!/home/soso/v5/.venv/bin/python3
"""long-only TSMOM 筛因子选股（A股适配）- 综合：分段 + 扣成本 + WFO
信号: 过去12周多空收益均值>0 保留(sign=+1), <0 剔除
持仓: 保留因子的 top30% 多头收益等权平均
"""
import os, json
from datetime import datetime
import numpy as np

RET_LS = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
RET_TOP = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_top.json')
OUT = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_long_select_result.json')
K = 12
TRAIN_END = '2022-W52'
FREQ = 52
COST_A = 0.0030  # A股 round-trip 30bp


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def sharpe(r, freq=FREQ):
    if len(r) < 2: return 0.0
    arr = np.array(r)
    if arr.std() == 0: return 0.0
    return float(arr.mean() / arr.std() * np.sqrt(freq))


def stats(r):
    if not r: return {}
    arr = np.array(r)
    t = float(arr.mean() / (arr.std() / np.sqrt(len(arr)))) if arr.std() > 0 else 0
    return {'n': len(arr), 'annual': float(arr.mean() * FREQ), 'sharpe': sharpe(r), 't': t}


def main():
    log("=" * 60); log("long-only TSMOM 筛因子选股 (分段+扣成本+WFO)"); log("=" * 60)
    ls = json.load(open(RET_LS))
    top = json.load(open(RET_TOP))
    factors = [f for f in ls if f in top]
    wks = sorted(set(w for f in factors for w in ls[f]))
    ls_by = {w: {} for w in wks}
    top_by = {w: {} for w in wks}
    for f in factors:
        for w, r in ls[f].items(): ls_by[w][f] = r
        for w, r in top[f].items(): top_by[w][f] = r

    rets, wks_used, active_sets, turnovers = [], [], [], []
    for i, w in enumerate(wks):
        if i < K: continue
        past = wks[i - K:i]
        port = 0.0; nf = 0; active = set()
        for f in factors:
            past_ls = [ls_by[p].get(f) for p in past]
            past_ls = [x for x in past_ls if x is not None]
            if len(past_ls) < K // 2: continue
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

    # 分段
    tr_r = [r for w, r in zip(wks_used, rets) if w <= TRAIN_END]
    oos_r = [r for w, r in zip(wks_used, rets) if w > TRAIN_END]
    log(f"全段: {stats(rets)}")
    log(f"训练(<=2022-W52): {stats(tr_r)}")
    log(f"OOS(>2022-W52): {stats(oos_r)}")
    log(f"平均保留因子: {np.mean([len(a) for a in active_sets]):.1f}/{len(factors)}")
    log(f"平均换手(因子变化率): {np.mean(turnovers):.1%}/周, 年换手: {np.mean(turnovers)*FREQ:.1f}")

    # 扣成本
    net = [r - COST_A * t for r, t in zip(rets, turnovers + [0])][:len(rets)]
    log(f"扣A股30bp后 net: {stats(net)}")

    # WFO 滚动52周
    if len(rets) >= 52:
        sh = [sharpe(rets[i:i+52]) for i in range(len(rets) - 51)]
        sh = np.array(sh)
        log(f"滚动52周夏普: min={sh.min():.2f} p25={np.percentile(sh,25):.2f} median={np.median(sh):.2f} p75={np.percentile(sh,75):.2f} max={sh.max():.2f}, 负窗口{(sh<0).mean():.0%}")
        # OOS 4段
        n4 = len(oos_r) // 4
        for j in range(4):
            seg = oos_r[j*n4:(j+1)*n4]
            log(f"  OOS段{j+1}({len(seg)}周): 夏普{sharpe(seg):.2f} 年化{np.mean(seg)*FREQ:.2%}")

    out = {'full': stats(rets), 'train': stats(tr_r), 'oos': stats(oos_r),
           'net_a30bp': stats(net), 'avg_turnover': float(np.mean(turnovers)),
           'returns': list(zip(wks_used, rets))}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")


if __name__ == '__main__':
    main()
