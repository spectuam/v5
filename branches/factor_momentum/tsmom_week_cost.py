#!/home/soso/v5/.venv/bin/python3
"""TSMOM 周度 + 扣成本（看 net 实盘可行性）
周度换手高，扣成本看 net 夏普。GK: TSFM 1-12 毛0.70->net0.63。
成本口径: round-trip 20bp (10bp单边×2，GK口径)；另算A股口径(10.2bp分项+冲击)
"""
import os, json
from datetime import datetime
import numpy as np

OUT = os.path.expanduser('~/v5/branches/factor_momentum/tsmom_week_cost_result.json')
RET_FILE = os.path.expanduser('~/v5/branches/factor_momentum/factor_returns_week.json')
K = 12
TRAIN_END = '2022-W52'
FREQ = 52
COST_GK = 0.0020  # round-trip 20bp (GK 10bp单边×2)
COST_A = 0.0030  # A股口径 round-trip ~30bp (佣金5+印花5+过户0.2+冲击, 多空更贵)


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
    log("=" * 60); log("TSMOM 周度 + 扣成本 (换手跟踪)"); log("=" * 60)
    factor_ret = json.load(open(RET_FILE))
    factors = list(factor_ret.keys())
    wks = sorted(set(w for f in factors for w in factor_ret[f]))
    ret_by_week = {w: {} for w in wks}
    for f in factors:
        for w, r in factor_ret[f].items():
            ret_by_week[w][f] = r

    ts_rets, turnovers = [], []
    prev_signs = None
    for i, w in enumerate(wks):
        if i < K: continue
        past = wks[i - K:i]
        cur = ret_by_week[w]
        signs, port = {}, 0.0; nf = 0
        for f in factors:
            past_rets = [ret_by_week[p].get(f) for p in past]
            past_rets = [x for x in past_rets if x is not None]
            if len(past_rets) < K // 2: continue
            if f not in cur: continue
            sign = 1.0 if np.mean(past_rets) > 0 else -1.0
            signs[f] = sign
            port += sign * cur[f]; nf += 1
        if nf == 0: continue
        port /= nf
        # 换手：sign变化（单边）
        if prev_signs is not None:
            common = set(signs) & set(prev_signs)
            if common:
                changed = sum(1 for f in common if signs[f] != prev_signs[f])
                turnover = changed / len(common)  # sign翻转的因子比例
                turnovers.append(turnover)
        prev_signs = signs
        ts_rets.append((w, port))

    avg_turnover = float(np.mean(turnovers)) if turnovers else 0
    log(f"平均换手(sign翻转率): {avg_turnover:.1%}/周, 年换手: {avg_turnover*FREQ:.1f}")

    all_r = [r for _, r in ts_rets]
    for name, cost in [('毛', 0), ('GK20bp', COST_GK), ('A股30bp', COST_A)]:
        net = [r - cost * t for r, t in zip(all_r, turnovers + [0])]  # 对齐（首期无换手）
        net = net[:len(all_r)]
        s = stats(net)
        log(f"  {name}: 全段{stats(all_r) if cost==0 else s}")
        if cost > 0:
            log(f"    net年化{s.get('annual',0):.2%} 夏普{s.get('sharpe',0):.3f} t{s.get('t',0):.2f}")

    out = {'avg_turnover_week': avg_turnover, 'avg_turnover_year': avg_turnover * FREQ,
           'gross': stats(all_r),
           'net_gk_20bp': stats([r - COST_GK * t for r, t in zip(all_r, turnovers + [0])][:len(all_r)]),
           'net_a_30bp': stats([r - COST_A * t for r, t in zip(all_r, turnovers + [0])][:len(all_r)])}
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)
    log(f"written:{OUT}")


if __name__ == '__main__':
    main()
