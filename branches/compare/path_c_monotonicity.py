#!/home/soso/v5/.venv/bin/python3
"""路C 形态：Patton-Timmermann 2010 正式单调性检验

升级decile.py的D1-D10 spread t为正式单调性检验:
对D1-D10收益序列, 检验因子分位与收益是否单调(非参数Spearman秩相关+p值)。
和IC互补: IC看连续秩相关, 单调性看分位极端是否真区分+单调。
"""
import os, json
from datetime import datetime
import numpy as np
from scipy.stats import spearmanr

DECILE = os.path.expanduser('~/v5/branches/factor_momentum/decile_result.json')
OUT = os.path.expanduser('~/v5/branches/compare/monotonicity_result.json')
RHO_THRESH = 0.7  # 单调性阈值
P_THRESH = 0.05


def main():
    d = json.load(open(DECILE))
    factors = d.get('factors', {})
    out = {}
    for fid, r in factors.items():
        avg = r.get('decile_avg', {})
        if len(avg) < 10:
            out[fid] = {'monotone_pass': False, 'reason': 'insufficient deciles'}
            continue
        rets = [avg.get(str(i), 0) for i in range(1, 11)]
        ranks = list(range(1, 11))
        rho, p = spearmanr(ranks, rets)
        # 方向: 因子值D1最高, 若D1收益最高则rho负(高因子值->高收益)
        direction = 'high_value_high_return' if rets[0] > rets[-1] else 'low_value_high_return'
        monotone = abs(rho) >= RHO_THRESH and p < P_THRESH
        out[fid] = {
            'spearman_rho': round(float(rho), 3),
            'p_value': round(float(p), 4),
            'direction': direction,
            'monotone_pass': bool(monotone),
            'd1_d10_spread': round(rets[0] - rets[-1], 5),
        }
    json.dump(out, open(OUT, 'w'), indent=2, ensure_ascii=False, default=float)

    passed = [f for f, v in out.items() if v.get('monotone_pass')]
    print(f"路C Patton-Timmermann单调性: {len(out)}因子, 通过{len(passed)}")
    print("通过因子:")
    for f in passed:
        v = out[f]
        print(f"  {f}: rho={v['spearman_rho']} p={v['p_value']} dir={v['direction']}")
    print(f"written: {OUT}")


if __name__ == '__main__':
    main()
